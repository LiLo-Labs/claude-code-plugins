"""Group the index regions into classes: all the cups, all the ridges, all the whips.

`index_regions.py` produces regions whose boundaries are the surface's own, but a
region is an INSTANCE -- this cup, that ridge. A colour plan addresses CLASSES: "the
barnacles are orange" has to reach every barnacle at once. So the regions need
grouping, and the grouping has to be by something that survives.

The last three attempts to group anything on this model clustered patch descriptors and
all three died, because those descriptors were statistics of a SLIC cell: patch
elongation correlates 0.26 with itself under a reseed, and it alone supplied 22.3% of
the force tearing the smooth panel into confetti. The descriptors here are different in
kind. A region's characteristic scale and its band-passed relief are measured off the
surface in millimetres by `scale_space.py`, which has no seed at all, and the regions
they are aggregated over are themselves deterministic. Nothing in this chain can be
reshuffled by re-running it.

Three numbers per region, and deliberately only three:

  size      the region's own extent in millimetres, from the index -- a cup is 1mm,
            a ridge is 15mm, and that is most of what separates them
  form      band-passed relief: does it stand out of its surroundings, sit flush, or
            sink into them
  area      how much surface it covers, which distinguishes a broad flank from a
            narrow rope of identical curvature

Shape descriptors are deliberately absent. They were the noise last time, and the
region boundaries already carry the shape information that mattered.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from patch_features import cluster                                   # noqa: E402
from view_atlas import where_to_point                                # noqa: E402

PALETTE = np.array([
    [0.90, 0.24, 0.20], [0.20, 0.55, 0.90], [0.30, 0.75, 0.35], [0.95, 0.65, 0.15],
    [0.65, 0.35, 0.85], [0.10, 0.70, 0.70], [0.95, 0.45, 0.65], [0.55, 0.45, 0.25],
    [0.45, 0.80, 0.20], [0.20, 0.35, 0.70], [0.85, 0.35, 0.45], [0.40, 0.65, 0.60],
])


def region_rows(session, index, labels):
    """One row per region: log size, form, log area. Medians, so one odd face cannot
    move a region into the wrong class."""
    count = int(labels.max()) + 1
    areas = session["areas"]
    scale = np.log(np.maximum(index["characteristic_mm"], 1e-6))
    signed = np.asarray(index["signed"], dtype=np.float64)

    order = np.argsort(labels, kind="stable")
    starts = np.searchsorted(labels[order], np.arange(count))
    ends = np.searchsorted(labels[order], np.arange(count), side="right")
    rows = np.zeros((count, 3))
    total = float(areas.sum())
    for region in range(count):
        members = order[starts[region]:ends[region]]
        rows[region] = (np.median(scale[members]), np.median(signed[members]),
                        np.log(max(areas[members].sum() / total, 1e-9)))
    return rows


def standardise(rows):
    out = rows - rows.mean(axis=0)
    return out / np.maximum(out.std(axis=0), 1e-9)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--classes", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--views", default="iso,front")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    index = np.load(os.path.join(args.session, "scale_space.npz"))
    regions_path = os.path.join(args.session, "index_regions.npy")
    if not os.path.exists(regions_path):
        raise SystemExit("index_classes: no index_regions.npy; run index_regions.py")
    labels = np.load(regions_path)

    rows = region_rows(session, index, labels)
    assignment, _centres = cluster(standardise(rows), args.classes, seed=args.seed)
    face_class = assignment[labels]

    areas, faces = session["areas"], session["faces"]
    total = float(areas.sum())
    atlas_path = os.path.join(args.session, "view_atlas.npz")
    atlas = np.load(atlas_path) if os.path.exists(atlas_path) else None

    out_nodes = []
    print("%d classes over %d regions" % (args.classes, len(rows)))
    for klass in range(args.classes):
        members = np.flatnonzero(assignment == klass)
        if not len(members):
            continue
        mask = face_class == klass
        share = float(areas[mask].sum() / total)
        size = float(np.exp(np.median(rows[members, 0])))
        form = float(np.median(rows[members, 1]))
        word = "ridge" if form > 0.01 else ("groove" if form < -0.01 else "flat")
        at = None
        if atlas is not None:
            found, _n = where_to_point(atlas, np.flatnonzero(mask)[:200000], limit=1)
            if found:
                at = "el%+.0f az%.0f at %d,%d" % (found[0]["elevation"],
                                                 found[0]["azimuth"],
                                                 found[0]["at"][0], found[0]["at"][1])
        print("  class-%d  %6.2f%% of area  %3d region(s)  ~%5.2fmm %-6s  %s"
              % (klass, 100 * share, len(members), size, word, at or "-"))
        out_nodes.append({"name": "class-%d" % klass, "area": round(share, 5),
                          "regions": len(members), "size_mm": round(size, 3),
                          "form": round(form, 4), "at": at,
                          "region_ids": [int(m) for m in members]})

    with open(os.path.join(args.session, "index_classes.json"), "w") as handle:
        json.dump({"classes": out_nodes}, handle, indent=2)
    np.save(os.path.join(args.session, "index_class_of_face.npy"), face_class)

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = PALETTE[face_class % len(PALETTE)]
    out = os.path.join(args.session, "indexclasses")
    os.makedirs(out, exist_ok=True)
    for view in args.views.split(","):
        if view.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()], 900)
            raster.save_png(os.path.join(out, "c%d-%s.png" % (args.classes, view.strip())),
                            image)
    print("  %s/c%d-*.png -- LOOK, then name each class by its colour"
          % (out, args.classes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
