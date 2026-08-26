"""Class objects by what they ARE, not by where they happen to sit.

Three identification defects were visible on the shell once every feature type was
given one colour and looked at from six sides. All three are classification errors
sitting on top of correct boundaries, and all three have generic causes.

**Height split every repeated feature in two.** Normalised height was a clustering
feature, so the barnacle cones above z=22mm and the identical cones below it became
two classes, and so did their throats, and so did the shell itself -- no class equalled
"the shell". Height is not a property of what a thing IS. A cup is a cup on the crown or
at the foot. It is gone from the feature set. The one thing it was there for, isolating
the flat underside, is done properly here by measurement: faces whose normal points
down and which sit at the model's lowest extent are invisible from every camera
direction, which is a fact about the model rather than a threshold.

**The exposed underlayer inside a break could not be separated from the outer shell.**
It is the same material, the same size and the same flatness; nothing measured at its
own scale distinguishes them. What distinguishes them is that one is a step BELOW its
surroundings and the other IS the surroundings. So the feature set gains
`parent-relative elevation`: the offset of an object measured not at its own scale but
at the scale of the thing it sits on, normalised by its own size. Positive means it
stands proud -- a barnacle on a shell, a boss on a plate. Negative means it is recessed
-- an underlayer revealed by a break, the floor of a groove. Zero means it is the
surface. This is the generic distinction between applied, revealed, and base, and it is
the one axis the earlier feature sets had no way to express.

**Classes that over-reach cannot be fixed by choosing k.** Splitting a bad class by
raising k re-cuts every good class too. `--split` re-clusters WITHIN one class and
leaves the rest untouched, so an agent that looks at a class render and says "this one
holds two things" gets that class divided and nothing else disturbed.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from patch_features import cluster                                   # noqa: E402

FEATURES = ["log size", "relief", "log area", "parent elevation"]
PALETTE = np.array([
    [0.90, 0.24, 0.20], [0.20, 0.55, 0.90], [0.30, 0.75, 0.35], [0.95, 0.65, 0.15],
    [0.65, 0.35, 0.85], [0.10, 0.70, 0.70], [0.95, 0.45, 0.65], [0.55, 0.45, 0.25],
    [0.45, 0.80, 0.20], [0.20, 0.35, 0.70], [0.85, 0.35, 0.45], [0.40, 0.65, 0.60],
    [0.75, 0.55, 0.90], [0.60, 0.60, 0.20], [0.25, 0.60, 0.45], [0.90, 0.50, 0.30],
])


def hidden_underside(session):
    """Faces that point down at the model's lowest extent: the printed footprint.

    Measured, not assumed: these are invisible from every direction, so they can never
    be clicked, never be judged from a render, and must never be painted.
    """
    faces, vertices, normals = session["faces"], session["vertices"], session["normals"]
    height = vertices[faces].mean(axis=1)[:, 2]
    span = max(float(np.ptp(height)), 1e-9)
    return (normals[:, 2] < -0.9) & (height < height.min() + 0.01 * span)


def object_rows(session, index, objects, parent_ratio):
    """One row per object. No position, no height -- only what the thing is."""
    count = int(objects.max()) + 1
    areas = session["areas"]
    radii = np.asarray(index["radii_mm"], dtype=np.float64)
    characteristic = np.asarray(index["characteristic_mm"], dtype=np.float64)
    signed = np.asarray(index["signed"], dtype=np.float64)
    offset = np.asarray(index["offset"], dtype=np.float64) if "offset" in index else None

    # The rung standing for "the scale of what this sits on": several times the face's
    # own scale, clipped to the ladder that exists.
    if offset is not None:
        own = np.searchsorted(radii, characteristic).clip(0, len(radii) - 1)
        parent = np.searchsorted(radii, characteristic * parent_ratio).clip(0, len(radii) - 1)
        rows_index = np.arange(len(characteristic))
        elevation = offset[parent, rows_index] / np.maximum(characteristic, 1e-6)
    else:
        elevation = np.zeros(len(characteristic))

    total = float(areas.sum())
    order = np.argsort(objects, kind="stable")
    bounds = np.searchsorted(objects[order], np.arange(count + 1))
    rows = np.zeros((count, 4))
    for node in range(count):
        members = order[bounds[node]:bounds[node + 1]]
        if not len(members):
            continue
        rows[node] = (np.median(np.log(np.maximum(characteristic[members], 1e-6))),
                      np.median(signed[members]),
                      np.log(max(areas[members].sum() / total, 1e-9)),
                      np.median(elevation[members]))
    return rows


def standardise(rows, live):
    out = rows - rows[live].mean(axis=0)
    return out / np.maximum(rows[live].std(axis=0), 1e-9)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--objects", default="index_objects.npy")
    parser.add_argument("--classes", type=int, default=8)
    parser.add_argument("--parent-ratio", type=float, default=4.0,
                        help="how many times an object's own scale counts as the scale "
                             "of what it sits on")
    parser.add_argument("--split", type=int, default=None,
                        help="re-cluster only this class id, leaving the others alone")
    parser.add_argument("--into", type=int, default=2, help="how many parts to split into")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--views", default="iso,front")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    index = np.load(os.path.join(args.session, "scale_space.npz"))
    objects = np.load(os.path.join(args.session, args.objects))
    faces, areas = session["faces"], session["areas"]
    total = float(areas.sum())

    rows = object_rows(session, index, objects, args.parent_ratio)
    under = hidden_underside(session)
    count = int(objects.max()) + 1
    share_under = np.array([under[objects == n].mean() if (objects == n).any() else 0.0
                            for n in range(count)])
    buried = share_under > 0.5
    live = ~buried

    existing = os.path.join(args.session, "object_classes.npy")
    if args.split is not None and os.path.exists(existing):
        labels = np.load(existing)
        target = np.flatnonzero((labels == args.split) & live)
        if len(target) < args.into:
            raise SystemExit("object_classes: class %d has too few objects to split"
                             % args.split)
        sub, _c = cluster(standardise(rows, target)[target], args.into, seed=args.seed)
        nxt = int(labels.max()) + 1
        for part in range(1, args.into):
            labels[target[sub == part]] = nxt + part - 1
        print("split class %d into %d; classes now %d"
              % (args.split, args.into, labels.max() + 1))
    else:
        labels = np.full(count, -1, dtype=np.int32)
        alive = np.flatnonzero(live)
        assignment, _c = cluster(standardise(rows, alive)[alive], args.classes,
                                 seed=args.seed)
        labels[alive] = assignment
        labels[buried] = args.classes
        print("%d objects -> %d classes plus the hidden underside"
              % (count, args.classes))

    np.save(existing, labels)
    face_class = labels[objects]
    np.save(os.path.join(args.session, "object_class_of_face.npy"), face_class)

    report = []
    for klass in sorted(set(int(v) for v in labels)):
        mask = face_class == klass
        if not mask.any():
            continue
        members = labels == klass
        report.append({"class": int(klass), "area": round(float(areas[mask].sum() / total), 5),
                       "objects": int(members.sum()),
                       "size_mm": round(float(np.exp(np.median(rows[members, 0]))), 2),
                       "relief": round(float(np.median(rows[members, 1])), 4),
                       "elevation": round(float(np.median(rows[members, 3])), 4),
                       "hidden": bool(share_under[members].mean() > 0.5)})
    report.sort(key=lambda r: -r["area"])
    with open(os.path.join(args.session, "object_classes.json"), "w") as handle:
        json.dump({"features": FEATURES, "classes": report}, handle, indent=2)
    for r in report:
        stands = "proud" if r["elevation"] > 0.02 else ("recessed" if r["elevation"] < -0.02
                                                        else "flush")
        print("  class-%-2d %6.2f%%  %4d obj  ~%6.2fmm  %-8s%s"
              % (r["class"], 100 * r["area"], r["objects"], r["size_mm"], stands,
                 "  HIDDEN" if r["hidden"] else ""))

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = PALETTE[np.maximum(face_class, 0) % len(PALETTE)]
    colours[face_class < 0] = (1.0, 0.0, 1.0)
    out = os.path.join(args.session, "objectclasses")
    os.makedirs(out, exist_ok=True)
    for view in args.views.split(","):
        if view.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()], 900)
            raster.save_png(os.path.join(out, "classes-%s.png" % view.strip()), image)
    print("  %s/classes-*.png" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
