"""Show the instances inside a class, so an agent can tell them apart and split them.

`index_classes.py` groups regions by geometry, and geometry has a hard limit: it cannot
tell a shell from the rock it sits on. Both are large, both are smooth, both are flat at
their own scale, and they differ by MATERIAL, which no measurement in this pipeline
takes. On the shell that put 67% of the surface in one class holding two different
things.

That limit is not a reason to hand the problem to a person. It is a reason to LOOK,
which is what the eye is for and what geometry is not. A render of one class, with each
of its instances in its own colour and each labelled with an id, is enough to say "these
six lumps are the rock, those four are the shell body" -- an easy judgement from a
picture and an impossible one from a table of curvature.

So this prints the instances of a class with their ids, sizes, and where to point at
each, and renders them apart. What comes back is a split: a list of ids per new name.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from view_atlas import where_to_point                                # noqa: E402

PALETTE = np.array([
    [0.90, 0.24, 0.20], [0.20, 0.55, 0.90], [0.30, 0.75, 0.35], [0.95, 0.65, 0.15],
    [0.65, 0.35, 0.85], [0.10, 0.70, 0.70], [0.95, 0.45, 0.65], [0.55, 0.45, 0.25],
    [0.45, 0.80, 0.20], [0.20, 0.35, 0.70], [0.85, 0.35, 0.45], [0.40, 0.65, 0.60],
    [0.75, 0.55, 0.90], [0.60, 0.60, 0.20], [0.25, 0.60, 0.45], [0.90, 0.50, 0.30],
])


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--class-name", required=True,
                        help="a name from index_classes.json, e.g. class-1")
    parser.add_argument("--top", type=int, default=16,
                        help="show this many instances, largest first")
    parser.add_argument("--views", default="iso,front")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    regions = np.load(os.path.join(args.session, "index_regions.npy"))
    with open(os.path.join(args.session, "index_classes.json")) as handle:
        classes = json.load(handle)["classes"]
    node = next((c for c in classes if c["name"] == args.class_name), None)
    if node is None:
        raise SystemExit("index_inspect: no class %r (have %s)"
                         % (args.class_name, ", ".join(c["name"] for c in classes)))

    faces, areas = session["faces"], session["areas"]
    total = float(areas.sum())
    centres = session["vertices"][faces].mean(axis=1)
    height = centres[:, 2]
    low, span = float(height.min()), max(float(np.ptp(height)), 1e-9)

    atlas_path = os.path.join(args.session, "view_atlas.npz")
    atlas = np.load(atlas_path) if os.path.exists(atlas_path) else None

    rows = []
    for region in node["region_ids"]:
        mask = regions == region
        if not mask.any():
            continue
        share = float(areas[mask].sum() / total)
        rows.append({"region": int(region), "area": share,
                     "height": float((height[mask].mean() - low) / span),
                     "faces": int(mask.sum())})
    rows.sort(key=lambda r: -r["area"])
    shown = rows[:args.top]

    print("%s: %d instances, %.2f%% of the model"
          % (args.class_name, len(rows), 100 * node["area"]))
    print("  id     area    height  where to point")
    for index, row in enumerate(shown):
        at = "-"
        if atlas is not None:
            found, _n = where_to_point(atlas, np.flatnonzero(regions == row["region"]),
                                       limit=1)
            if found:
                at = "el%+.0f az%.0f  %d,%d" % (found[0]["elevation"],
                                                found[0]["azimuth"],
                                                found[0]["at"][0], found[0]["at"][1])
        rgb = PALETTE[index % len(PALETTE)]
        print("  %-5d %6.2f%%  %5.2f   %-22s rgb(%3d,%3d,%3d)"
              % (row["region"], 100 * row["area"], row["height"], at,
                 *(int(255 * c) for c in rgb)))
    if len(rows) > len(shown):
        print("  ... and %d smaller instances not shown or coloured"
              % (len(rows) - len(shown)))

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = np.tile(np.array([0.90, 0.90, 0.92]), (len(faces), 1))
    for index, row in enumerate(shown):
        colours[regions == row["region"]] = PALETTE[index % len(PALETTE)]
    out = os.path.join(args.session, "indexclasses")
    os.makedirs(out, exist_ok=True)
    for view in args.views.split(","):
        if view.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()], 900)
            raster.save_png(os.path.join(out, "%s-instances-%s.png"
                                         % (args.class_name, view.strip())), image)
    print("  %s/%s-instances-*.png -- LOOK, then say which ids are which thing"
          % (out, args.class_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
