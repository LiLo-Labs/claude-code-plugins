"""Over-segment a model into surface patches whose edges follow what you can see.

Threshold-grown selections have the wrong boundary by construction. The edge lands
on a contour of whatever was measured -- roughness, thickness, relief -- and that
contour is not the edge of the thing. Measured on a real model, selections grown
this way smeared across neighbouring surfaces and left a fringe of stray triangles
around every feature.

The edges are unambiguous in the image. Depth steps at a silhouette, the surface
normal swings at a crease, shading drops in a crevice: the same cues a person uses
to see where one thing stops and the next begins. So:

1. Render the model from several views, keeping depth, normal, relief and cavity
   buffers alongside the pick map.
2. Over-segment each view with SLIC into superpixels. These snap to visible edges,
   because that is what the feature stack encodes.
3. Carry each view's superpixels back to triangles through the pick map, and merge
   adjacent triangles that land in the same superpixel in MOST of the views that
   can see them both.

That last word is the whole algorithm. Merging on agreement in any one view fails
outright -- tried, and it produced a single patch covering 37% of the model with
94.5% of the rest left as single triangles, because one unlucky view welds
together what every other view separates. A viewpoint is evidence, not truth: it
suffers foreshortening, occlusion and grazing angles, and any one of those puts a
superpixel boundary in the wrong place.

So views vote. Each pair of adjacent triangles accumulates the number of views in
which both are visible, and the number in which both fall in the same superpixel.
The pair is merged only when the second is a clear majority of the first. A
boundary that only one view sees is noise; a boundary that every view that can see
it agrees on is a real edge.

Viewpoints are sampled quasi-randomly over the sphere rather than taken from the
six axes, because axis views systematically miss surfaces angled between them --
which is where a sculpted model keeps most of its detail. The sampling is seeded,
so the same model always gives the same patches.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                        # noqa: E402


class DisjointSet(object):
    def __init__(self, size):
        self.parent = np.arange(size, dtype=np.int64)

    def find(self, item):
        parent = self.parent
        root = item
        while parent[root] != root:
            root = parent[root]
        while parent[item] != root:      # path compression, iterative
            parent[item], item = root, parent[item]
        return root

    def union(self, left, right):
        left, right = self.find(left), self.find(right)
        if left != right:
            self.parent[max(left, right)] = min(left, right)


def feature_stack(channels, visible):
    """The cues an eye uses, packed as image channels for SLIC."""
    def scaled(values, low=2, high=98):
        values = np.asarray(values, dtype=float)
        mask = np.isfinite(values) & visible
        if not mask.any():
            return np.zeros_like(values)
        lo, hi = np.nanpercentile(values[mask], [low, high])
        out = np.clip((values - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
        out[~mask] = 0.0
        return out

    layers = [channels["normals"] * 0.5 + 0.5]
    for name in ("relief", "occlusion", "depth"):
        if name in channels:
            layers.append(scaled(channels[name])[..., None])
    return np.dstack(layers)


def sample_views(count, seed=11):
    """Quasi-uniform viewpoints on a sphere, plus the axis views for familiarity.

    A Fibonacci lattice spreads directions evenly without the clustering that
    uniform random angles produce near the poles. Seeded and deterministic: the
    same model must always segment the same way, or nothing downstream can be
    iterated on.
    """
    named = [raster.VIEWS[name] for name in ("front", "back", "left", "right", "iso", "iso2")]
    extra = max(0, count - len(named))
    if not extra:
        return named

    golden = np.pi * (3.0 - np.sqrt(5.0))
    rng = np.random.default_rng(seed)
    offset = rng.random()
    out = list(named)
    for index in range(extra):
        # Bias away from directly overhead and underneath, where a terrain-style
        # model shows least and self-occludes most.
        z = 1.0 - 2.0 * (index + offset) / max(extra, 1)
        z = np.clip(z, -0.75, 0.85)
        elevation = np.degrees(np.arcsin(z))
        azimuth = np.degrees((index * golden) % (2.0 * np.pi)) - 180.0
        out.append((float(elevation), float(azimuth)))
    return out


def patches_for_model(mesh, views, size, extras, n_segments, compactness,
                      agreement=0.6, min_votes=2):
    """Merge adjacent triangles that most views agree belong together."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from skimage.segmentation import slic

    faces = len(mesh.faces)
    pairs = mesh.face_adjacency
    seen = np.zeros(len(pairs), dtype=np.int32)      # views where both are visible
    agreed = np.zeros(len(pairs), dtype=np.int32)    # views that put them together

    for position, (elevation, azimuth) in enumerate(views, start=1):
        channels = raster.render_channels(mesh, elevation, azimuth, size=size,
                                          extras=extras)
        visible = channels["visible"]
        if not visible.any():
            continue
        segments = slic(feature_stack(channels, visible), n_segments=n_segments,
                        compactness=compactness, channel_axis=-1, mask=visible,
                        start_label=1, enforce_connectivity=True, sigma=1.0)

        # Each face takes the superpixel covering most of its pixels; -1 if unseen.
        owner = np.full(faces, -1, dtype=np.int32)
        picks, labels_flat = channels["picks"][visible], segments[visible]
        order = np.argsort(picks, kind="stable")
        picks, labels_flat = picks[order], labels_flat[order]
        boundaries = np.flatnonzero(np.diff(picks)) + 1
        for chunk in np.split(np.arange(len(picks)), boundaries):
            if not len(chunk):
                continue
            values, counts = np.unique(labels_flat[chunk], return_counts=True)
            owner[picks[chunk[0]]] = values[np.argmax(counts)]

        left, right = owner[pairs[:, 0]], owner[pairs[:, 1]]
        both = (left >= 0) & (right >= 0)
        seen += both
        agreed += both & (left == right)
        print("  view %2d/%d  el %6.1f az %7.1f  %5d superpixels  %6d px on model"
              % (position, len(views), elevation, azimuth,
                 len(np.unique(segments)) - 1, int(visible.sum())))

    votes = np.maximum(seen, 1)
    merge = (seen >= min_votes) & ((agreed / votes) >= agreement)

    graph = coo_matrix((np.ones(int(merge.sum())),
                        (pairs[merge, 0], pairs[merge, 1])), shape=(faces, faces))
    _, labels = connected_components(graph, directed=False)
    print("\n  merged %d of %d adjacent pairs (%.1f%%)"
          % (merge.sum(), len(pairs), 100.0 * merge.mean()))

    # Faces no view resolved get no votes and would otherwise each become their own
    # patch. Merging their pairs blindly is worse -- it chains unrelated regions
    # through unseen pockets -- so instead they adopt the patch of the nearest
    # neighbour that WAS seen, spreading outward across the surface.
    unseen = np.ones(faces, dtype=bool)
    voted = pairs[seen > 0].ravel()
    unseen[voted] = False
    if unseen.any():
        sizes = np.bincount(labels)
        confident = ~unseen
        frontier = np.flatnonzero(confident)
        neighbours = [[] for _ in range(faces)]
        for left, right in pairs:
            neighbours[left].append(int(right))
            neighbours[right].append(int(left))
        adopted = labels.copy()
        pending = set(int(f) for f in np.flatnonzero(unseen))
        frontier = list(frontier)
        while frontier and pending:
            nxt = []
            for face in frontier:
                for neighbour in neighbours[face]:
                    if neighbour in pending:
                        adopted[neighbour] = adopted[face]
                        pending.discard(neighbour)
                        nxt.append(neighbour)
            frontier = nxt
        labels = adopted
        print("  %d faces were never resolved by any view; adopted a neighbour's patch"
              % int(unseen.sum()))

    _, labels = np.unique(labels, return_inverse=True)
    return labels.astype(np.int32)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="directory from inspect_model.py")
    parser.add_argument("--output", default=None, help="patches.npz (default: in session)")
    parser.add_argument("--views", type=int, default=18,
                        help="how many viewpoints to vote with (6 axis + the rest sampled)")
    parser.add_argument("--agreement", type=float, default=0.6,
                        help="share of co-visible views that must agree to merge")
    parser.add_argument("--min-votes", type=int, default=2,
                        help="fewest co-visible views before a pair may be merged")
    parser.add_argument("--size", type=int, default=900)
    parser.add_argument("--n-segments", type=int, default=1400,
                        help="superpixels per view; higher = finer patches")
    parser.add_argument("--compactness", type=float, default=0.09,
                        help="lower lets patches follow edges more freely")
    args = parser.parse_args()

    session_path = os.path.join(args.session, "session.npz")
    if not os.path.exists(session_path):
        parser.error("no session.npz in %s; run inspect_model.py first" % args.session)
    session = np.load(session_path)

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=session["faces"],
                           process=False)

    extras = {}
    for name in ("occlusion", "roughness", "thickness"):
        if name in session.files:
            extras[name] = session[name]
    relief_path = os.path.join(args.session, "relief.npy")
    if os.path.exists(relief_path):
        extras["relief"] = np.load(relief_path)
    else:
        from paintlib.signals import relief as compute_relief
        extras["relief"] = compute_relief(session["vertices"], session["faces"])
        np.save(relief_path, extras["relief"])

    views = sample_views(args.views)
    print("segmenting %d triangles; %d viewpoints vote, %.0f%% must agree"
          % (len(mesh.faces), len(views), 100 * args.agreement))
    labels = patches_for_model(mesh, views, args.size, extras,
                               args.n_segments, args.compactness,
                               args.agreement, args.min_votes)

    areas = session["areas"]
    sizes = np.bincount(labels)
    print("\n%d patches" % len(sizes))
    print("  size: median %d faces, p10 %d, p90 %d, largest %d"
          % (np.median(sizes), np.percentile(sizes, 10), np.percentile(sizes, 90),
             sizes.max()))
    print("  largest patch is %.2f%% of surface area"
          % (100 * areas[labels == int(np.argmax(sizes))].sum() / areas.sum()))
    singletons = int((sizes == 1).sum())
    if singletons:
        print("  %d single-triangle patches (%.1f%%)"
              % (singletons, 100.0 * singletons / len(sizes)))

    out = args.output or os.path.join(args.session, "patches.npz")
    np.savez_compressed(out, labels=labels)
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
