"""Vote on 3D boundaries from many angles and many scales, accumulating on the mesh.

Segmenting a render and fusing the result back to triangles is a recorded dead end: at
1600px a 626k-triangle model gets about five pixels per face, the per-face vote flips
between viewpoints, and the surface shatters -- 60% of it in one patch and 77% of the
rest single triangles. That failure is real and this is not a retry of it.

The difference is where the decision is made. Nothing here segments an image. Each view
only ever contributes EVIDENCE about one already-existing 3D quantity: for a pair of
faces that touch on the mesh, is there a visible edge between them? A single view
answers badly -- the pair may be edge-on, in shadow, occluded, or a few pixels wide --
which is exactly why one view was never enough. Thirty-two views spread over the sphere
answer well, because the failure modes are per-viewpoint and independent while a real
crease is visible from most directions that can see it at all. So the vote is taken per
face-pair, normalised by how many views could actually see that pair, and a boundary
nobody can see from anywhere simply has no evidence rather than a fabricated value.

Scale enters the same way. Shading gradients at full resolution find the fine creases
between barnacle cups; the same gradients after blurring find the broad edge where a
ridge meets a panel and ignore the texture inside both. Accumulating at several blurs
gives each pair a small profile across scale rather than one number, which is the same
reason the geometric index sweeps radii rather than picking one.

This is meant to be added to the geometric edge weight in `index_regions.py`, not to
replace it. Geometry knows about surfaces it can measure and cannot see; the camera
knows about edges a person would notice. They fail in different places, which is the
only good reason to combine two signals.

    view_evidence.py --session work/            # needs view_atlas.npz
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402

EVIDENCE = "view_evidence.npz"
BLURS = (0.0, 2.0, 5.0)


def pair_keys(pairs, count):
    """Sorted lookup keys for undirected face pairs, for vectorised matching."""
    low = np.minimum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    high = np.maximum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    keys = low * np.int64(count) + high
    order = np.argsort(keys, kind="stable")
    return keys[order], order


def accumulate(picks, image, keys, order, totals, seen, count, blur_index):
    """Add this view's edge evidence to every mesh pair visible as adjacent pixels."""
    from scipy import ndimage
    grey = image.astype(np.float64).mean(axis=2) / 255.0

    for blur_slot, sigma in enumerate(BLURS):
        field = grey if sigma <= 0 else ndimage.gaussian_filter(grey, sigma)
        for axis in (0, 1):
            if axis == 0:
                a, b = picks[:-1, :], picks[1:, :]
                da, db = field[:-1, :], field[1:, :]
            else:
                a, b = picks[:, :-1], picks[:, 1:]
                da, db = field[:, :-1], field[:, 1:]
            live = (a >= 0) & (b >= 0) & (a != b)
            if not live.any():
                continue
            fa, fb = a[live].astype(np.int64), b[live].astype(np.int64)
            low, high = np.minimum(fa, fb), np.maximum(fa, fb)
            key = low * np.int64(count) + high
            slot = np.searchsorted(keys, key)
            slot = np.clip(slot, 0, len(keys) - 1)
            good = keys[slot] == key
            if not good.any():
                continue
            target = order[slot[good]]
            step = np.abs(da[live] - db[live])[good]
            np.add.at(totals[blur_slot], target, step)
            if blur_slot == 0:
                np.add.at(seen, target, 1.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--size", type=int, default=900,
                        help="pixels per view; finer resolves finer creases")
    parser.add_argument("--views", type=int, default=None,
                        help="use only the first N atlas directions (default: all)")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    atlas_path = os.path.join(args.session, "view_atlas.npz")
    if not os.path.exists(atlas_path):
        raise SystemExit("view_evidence: no view_atlas.npz; run view_atlas.py first")
    directions = np.load(atlas_path)["directions"]
    if args.views:
        directions = directions[:args.views]

    faces, pairs = session["faces"], session["pairs"]
    count = len(faces)
    keys, order = pair_keys(pairs, count)
    totals = np.zeros((len(BLURS), len(pairs)))
    seen = np.zeros(len(pairs))

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    grey = np.tile(np.array([0.75, 0.75, 0.75]), (count, 1))

    for index, (elevation, azimuth) in enumerate(directions):
        image, picks = raster.render_view(mesh, grey, float(elevation), float(azimuth),
                                          args.size)
        accumulate(picks, image, keys, order, totals, seen, count, index)
        sys.stdout.write("\r  view %2d/%d" % (index + 1, len(directions)))
        sys.stdout.flush()
    sys.stdout.write("\n")

    # Mean per observation, so a pair seen from twenty angles is not ranked above an
    # equally sharp one seen from three merely for being easier to look at.
    observed = seen > 0
    evidence = np.zeros_like(totals)
    evidence[:, observed] = totals[:, observed] / seen[observed]

    np.savez_compressed(os.path.join(args.session, EVIDENCE),
                        evidence=evidence.astype(np.float32),
                        seen=seen.astype(np.int32),
                        blurs=np.array(BLURS, dtype=np.float32))
    print("%d pairs; %.1f%% seen from at least one direction, median %d views each"
          % (len(pairs), 100 * observed.mean(), int(np.median(seen[observed]))))
    for slot, sigma in enumerate(BLURS):
        strong = evidence[slot] > np.percentile(evidence[slot][observed], 95)
        print("  blur %.0f: strongest 5%% of pairs mean %.4f, all-pairs mean %.4f"
              % (sigma, evidence[slot][strong].mean(), evidence[slot][observed].mean()))
    print("  %d pairs (%.2f%%) never observed -- interior geometry, no camera evidence"
          % (int((~observed).sum()), 100 * (~observed).mean()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
