"""A nested hierarchy: sub-features, the objects they belong to, and the fields of those.

The flat partition has a defect that no amount of better boundaries fixes. A barnacle
cup is not one region -- it is a rim, a wall and a throat, at genuinely different
characteristic scales, and the region step is right to separate them. But classing
assigns every region independently, so one cup's own parts scatter into different
classes: measured on the shell, 120 of the 254 regions touching the barnacle class were
split between classes and only 53 sat wholly inside one. Painted, that reads as damage,
because a rim and the throat inside it end up on different filaments with nothing saying
they are the same cup.

The missing thing is a parent. So merge twice. The first pass groups faces into regions
whose boundaries are real. The second pass runs the SAME adaptive agglomeration again
over those regions, using the strength of the border between them, and a cup falls out
as one object -- because the boundary between a rim and its own throat is weak compared
with the boundary between the cup and the shell it sits on. Run it once more and cups
group into a colony.

The nesting is by construction rather than by hope: each level merges the level below,
so a child is always wholly inside its parent, and a label at any level can be resolved
to faces without ambiguity. That is what lets a plan say "all barnacles orange" and,
independently, "their throats black" -- the two statements address different levels of
one tree instead of competing for the same triangles.

Classing then happens on OBJECTS, not on raw regions, which is the actual repair: a cup
is classified once, as a cup, and its rim and throat inherit rather than being voted on
separately.

    index_hierarchy.py --session work/ --levels 15,60,240
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from index_regions import edge_weights, felzenszwalb                 # noqa: E402


def coarsen(labels, pairs, weights, k, min_faces, face_counts):
    """Merge the current regions into larger ones, using their shared borders.

    A border's strength is the MEAN of the mesh edges crossing it, not the minimum: one
    weak edge somewhere along a rim is not evidence that the rim is not a boundary, and
    taking the minimum would let a single soft pixel dissolve an otherwise clean edge.
    """
    left, right = labels[pairs[:, 0]], labels[pairs[:, 1]]
    crossing = left != right
    if not crossing.any():
        return labels, 0
    count = int(labels.max()) + 1
    key = np.minimum(left[crossing], right[crossing]).astype(np.int64) * count \
        + np.maximum(left[crossing], right[crossing]).astype(np.int64)
    unique, inverse = np.unique(key, return_inverse=True)
    totals = np.bincount(inverse, weights=weights[crossing])
    seen = np.bincount(inverse)
    region_pairs = np.stack([unique // count, unique % count], axis=1).astype(np.int64)
    region_weights = totals / np.maximum(seen, 1)

    # k is divided by node size inside the merge, and a node here stands for hundreds
    # of faces rather than one, so a k that means something at face level means almost
    # nothing at region level -- k=60 against a 900-face region is a threshold of 0.067
    # and nothing merges at all. Scaling by the mean node size keeps one number
    # comparable across levels, which is what makes the ladder readable.
    scaled = k * float(np.mean(face_counts))
    merged = felzenszwalb(region_pairs, region_weights, count, scaled, min_faces,
                          sizes=face_counts)
    return merged[labels], int(merged.max()) + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--levels", default="15,60,240",
                        help="k for each level, finest first: sub-features, objects, "
                             "then groups of objects")
    parser.add_argument("--min-faces", type=int, default=60)
    parser.add_argument("--camera-weight", type=float, default=2.0)
    parser.add_argument("--views", default="iso")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    index = np.load(os.path.join(args.session, "scale_space.npz"))
    evidence_path = os.path.join(args.session, "view_evidence.npz")
    evidence = np.load(evidence_path) if (args.camera_weight > 0
                                          and os.path.exists(evidence_path)) else None
    weights = edge_weights(session, index, evidence, args.camera_weight)

    faces, areas, pairs = session["faces"], session["areas"], session["pairs"]
    ks = [float(v) for v in args.levels.split(",")]

    levels = []
    labels = felzenszwalb(pairs, weights, len(faces), ks[0], args.min_faces)
    levels.append(labels.copy())
    print("level 0 (k=%g): %d sub-features" % (ks[0], labels.max() + 1))
    for depth, k in enumerate(ks[1:], start=1):
        counts = np.bincount(levels[-1])
        labels, total = coarsen(levels[-1], pairs, weights, k, args.min_faces, counts)
        levels.append(labels.copy())
        print("level %d (k=%g): %d %s" % (depth, k, total,
                                          "objects" if depth == 1 else "groups"))

    stack = np.stack(levels)
    np.save(os.path.join(args.session, "index_hierarchy.npy"), stack)

    # Nesting is the property the whole thing rests on, so check it rather than assert
    # it: every child must sit wholly inside one parent.
    for depth in range(len(levels) - 1):
        child, parent = levels[depth], levels[depth + 1]
        order = np.argsort(child, kind="stable")
        bounds = np.searchsorted(child[order], np.arange(child.max() + 2))
        broken = 0
        for node in range(child.max() + 1):
            members = order[bounds[node]:bounds[node + 1]]
            if len(members) and len(np.unique(parent[members])) > 1:
                broken += 1
        print("  level %d in %d: %d of %d children straddle a parent"
              % (depth, depth + 1, broken, child.max() + 1))

    top = levels[-1]
    summary = []
    total = float(areas.sum())
    for node in range(top.max() + 1):
        mask = top == node
        summary.append({"node": node, "area": round(float(areas[mask].sum() / total), 5),
                        "children": int(len(np.unique(levels[-2][mask])))})
    summary.sort(key=lambda r: -r["area"])
    with open(os.path.join(args.session, "index_hierarchy.json"), "w") as handle:
        json.dump({"levels": ks, "top": summary}, handle, indent=2)
    print("  largest top-level nodes: %s"
          % ", ".join("%.1f%%" % (100 * r["area"]) for r in summary[:6]))

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    rng = np.random.default_rng(5)
    out = os.path.join(args.session, "hierarchy")
    os.makedirs(out, exist_ok=True)
    for depth, labelling in enumerate(levels):
        palette = rng.uniform(0.15, 0.95, size=(max(labelling.max() + 1, 1), 3))
        colours = palette[labelling]
        for view in args.views.split(","):
            if view.strip() in raster.VIEWS:
                image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()],
                                              900)
                raster.save_png(os.path.join(out, "level%d-%s.png"
                                             % (depth, view.strip())), image)
    print("  %s/level*-*.png" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
