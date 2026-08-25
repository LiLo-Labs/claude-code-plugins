"""Monte Carlo over camera angles, so every label is pointable and nothing is hidden.

A label is only usable if someone can point at it, and a pixel coordinate is only
meaningful together with the view it was taken from. Seven fixed views do not settle
that: a barnacle tucked under a whorl lip may be visible from one oblique angle and
from nothing else, and a face no view ever sees cannot be labelled, checked, or
verified as painted -- it is a hole in the map that no per-view render reveals,
because each render only ever shows what it can see.

So sample the view sphere instead of assuming it. Directions are drawn on a
Fibonacci spiral, which spreads them evenly rather than clumping the way independent
random draws do, and every face is traced from every direction. That gives two things
a fixed view set cannot:

**Coverage, stated as a number.** How many of the sampled directions see each face,
and which faces are seen from none. Faces with zero visibility are reported rather
than quietly dropped -- on an interlocking model they are usually real: interior
walls of a shell, the underside of a flexi joint, surfaces that only exist for the
print. They still need a colour, and they can only get one by inheritance from a
label, never by anyone clicking at them.

**A coordinate per view, not one coordinate.** For each label this records every
direction that sees it, with a pixel inside it and how much of it that direction
shows. The best view for pointing at a feature is then a measurement rather than a
guess, and agreement across independent directions is what makes the pixel trustworthy:
a coordinate confirmed from six angles is describing a real region in 3D, while one
that only ever appears from a single grazing angle is usually a sliver seen edge-on.

    view_atlas.py --session work/ --views 32
    view_atlas.py --session work/ --label "barnacle field"    # where to point, ranked
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402

ATLAS = "view_atlas.npz"


def fibonacci_directions(count):
    """Evenly spread directions on the sphere, as (elevation, azimuth) degrees.

    The spiral is used rather than uniform random draws because random directions
    clump, and a clump is wasted tracing: it re-sees what the neighbouring direction
    already saw while leaving a gap somewhere else on the sphere.
    """
    indices = np.arange(count) + 0.5
    z = 1.0 - 2.0 * indices / count                     # cosine-uniform in z
    elevation = np.degrees(np.arcsin(np.clip(z, -1.0, 1.0)))
    azimuth = np.degrees((indices * np.pi * (1.0 + 5.0 ** 0.5)) % (2 * np.pi))
    return list(zip(elevation, azimuth))


def build(session, session_dir, count, size):
    import trimesh
    faces = session["faces"]
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    grey = np.tile(np.array([0.8, 0.8, 0.8]), (len(faces), 1))
    directions = fibonacci_directions(count)

    picks = np.full((count, size, size), -1, dtype=np.int32)
    seen = np.zeros(len(faces), dtype=np.int32)
    for index, (elevation, azimuth) in enumerate(directions):
        _image, pick = raster.render_view(mesh, grey, elevation, azimuth, size)
        picks[index] = pick
        visible = np.unique(pick[pick >= 0])
        seen[visible] += 1
        sys.stdout.write("\r  view %2d/%d  %6d faces visible"
                         % (index + 1, count, len(visible)))
        sys.stdout.flush()
    sys.stdout.write("\n")

    np.savez_compressed(os.path.join(session_dir, ATLAS),
                        picks=picks, seen=seen,
                        directions=np.array(directions, dtype=np.float32),
                        size=np.int32(size))
    return seen, directions


def where_to_point(atlas, face_indices, limit=5):
    """Every sampled direction that sees this label, best first."""
    picks, directions = atlas["picks"], atlas["directions"]
    wanted = np.zeros(int(picks.max()) + 2, dtype=bool)
    wanted[np.asarray(face_indices, dtype=np.int64)] = True

    found = []
    for index in range(len(picks)):
        pick = picks[index]
        on_model = pick >= 0
        hit = np.zeros_like(on_model)
        hit[on_model] = wanted[pick[on_model]]
        count = int(hit.sum())
        if not count:
            continue
        ys, xs = np.nonzero(hit)
        # The pixel closest to the label's own centre in this view, so the
        # coordinate lands inside the region rather than on its ragged edge.
        cx, cy = xs.mean(), ys.mean()
        best = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
        found.append({"view": index,
                      "elevation": round(float(directions[index][0]), 1),
                      "azimuth": round(float(directions[index][1]), 1),
                      "pixels": count,
                      "at": [int(xs[best]), int(ys[best])]})
    found.sort(key=lambda row: -row["pixels"])
    return found[:limit], len(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--views", type=int, default=32)
    parser.add_argument("--size", type=int, default=700)
    parser.add_argument("--label", default=None,
                        help="report where to point at this label instead of building")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    atlas_path = os.path.join(args.session, ATLAS)

    if args.label:
        if not os.path.exists(atlas_path):
            raise SystemExit("view_atlas: no atlas; build it first")
        with open(os.path.join(args.session, "label_tree.json")) as handle:
            tree = json.load(handle)
        node = next((n for n in tree["nodes"] if n["name"] == args.label), None)
        if node is None:
            raise SystemExit("view_atlas: no label %r" % args.label)
        atlas = np.load(atlas_path)
        rows, total = where_to_point(atlas, node["face_indices"])
        print("%s: seen from %d of %d directions"
              % (args.label, total, len(atlas["directions"])))
        for row in rows:
            print("  el %+6.1f az %6.1f  %7d px  at %d,%d"
                  % (row["elevation"], row["azimuth"], row["pixels"],
                     row["at"][0], row["at"][1]))
        if total <= 1:
            print("  ^ one direction only: usually a sliver seen edge-on, not a region")
        return 0

    print("tracing %d directions over %d faces" % (args.views, len(session["faces"])))
    seen, _directions = build(session, args.session, args.views, args.size)
    hidden = int((seen == 0).sum())
    print("coverage: %.2f%% of faces seen from at least one direction"
          % (100 * (seen > 0).mean()))
    print("  median directions per face: %d" % int(np.median(seen)))
    print("  %d faces (%.2f%%) seen from none -- interior or enclosed geometry."
          % (hidden, 100 * hidden / len(seen)))
    if hidden:
        print("  These can only be coloured by inheriting a label; nobody can click them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
