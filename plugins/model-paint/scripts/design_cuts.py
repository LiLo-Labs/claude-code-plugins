"""Draw a boundary where the surface does not have one. Paint only; geometry untouched.

Some boundaries are not in the model. Where this shell meets the reef it stands on, the
two surfaces run tangent at the same brightness: there is no crease, no shading step and
nothing for any measurement to find. It is a boundary of MATERIAL, and the model records
material nowhere.

Measured, and the reason this file exists: tripling the camera directions from 32 to 96
made that merge WORSE, not better. Area held in regions straddling rock and shell went
11.51% -> 16.14%, and the largest such region 3.23% -> 5.26%, while pair coverage
improved exactly as expected (19.82% -> 5.47% never observed). More angles photograph
the same absence of an edge more times. Detection was never the problem.

So stop asking geometry for it and draw it. The cut is a plane through what was drawn on
screen: two points picked on a rendered view, swept along that view's own axis. That is
the slice every 3D tool offers, and it is the right primitive because a person looking at
the render can place it in one gesture -- along the waterline where rock becomes shell --
where no amount of measurement can.

**Nothing here touches the mesh.** A cut only ever reassigns which named part a triangle
belongs to. Vertices, triangle indices and build placement are untouched, which the paint
codec then preserves byte-for-byte. That is what makes an invented boundary safe on a
model whose interlocking parts must print exactly as designed: the design lives in the
label, and the label is only ever a colour.

    design_cuts.py --session work/ --parts parts.json \\
        --split "smooth surface" --cut "front:60,past;840,590" --names "shell body,reef rock"
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402


def screen_plane(view, ax, ay, bx, by, size, centre, radius):
    """The plane through two screen points, swept along the view axis.

    Returns (point on plane, unit normal). The normal is perpendicular to both the
    drawn line and the direction of view, so the plane contains everything the line
    covers however deep it sits -- which is what "cut along this line" means when the
    line is drawn on a picture of a solid.
    """
    forward, right, up = raster._camera(*raster.VIEWS[view])
    span = 2.0 * radius / max(size - 1, 1)

    def to_world(x, y):
        return (np.asarray(centre, dtype=float)
                + right * ((x - (size - 1) / 2.0) * span)
                + up * (-(y - (size - 1) / 2.0) * span))

    start, end = to_world(ax, ay), to_world(bx, by)
    along = end - start
    length = np.linalg.norm(along)
    if length < 1e-9:
        raise SystemExit("design_cuts: the two points are the same pixel")
    normal = np.cross(along / length, forward)
    norm = np.linalg.norm(normal)
    if norm < 1e-9:
        raise SystemExit("design_cuts: degenerate cut for this view")
    return start, normal / norm


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--parts", required=True, help="parts JSON to cut")
    parser.add_argument("--split", required=True, help="name of the part to divide")
    parser.add_argument("--cut", required=True,
                        help="view:x1,y1;x2,y2 -- the line you drew on that view")
    parser.add_argument("--names", required=True,
                        help="two names, comma separated: negative side, positive side")
    parser.add_argument("--output", default=None, help="default: overwrite --parts")
    parser.add_argument("--views", default="iso")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    with open(args.parts) as handle:
        document = json.load(handle)
    parts = document.get("parts") or document.get("segments")
    if parts is None:
        raise SystemExit("design_cuts: %s has no 'parts' array" % args.parts)
    target = next((p for p in parts if p["name"] == args.split), None)
    if target is None:
        raise SystemExit("design_cuts: no part %r (have %s)"
                         % (args.split, ", ".join(p["name"] for p in parts)[:200]))

    try:
        view, rest = args.cut.split(":", 1)
        first, second = rest.split(";")
        ax, ay = (int(v) for v in first.split(","))
        bx, by = (int(v) for v in second.split(","))
    except ValueError:
        parser.error("--cut wants view:x1,y1;x2,y2, got %r" % args.cut)
    if view not in raster.VIEWS:
        parser.error("unknown view %r" % view)
    low_name, high_name = (n.strip() for n in args.names.split(","))

    vertices, faces, areas = session["vertices"], session["faces"], session["areas"]
    centre = vertices.mean(axis=0)
    radius = float(np.ptp(vertices, axis=0).max()) / 2.0 * 1.05
    size = int(np.sqrt(session["pick_%s" % view].size))
    point, normal = screen_plane(view, ax, ay, bx, by, size, centre, radius)

    members = np.asarray(target["face_indices"], dtype=np.int64)
    centres = vertices[faces[members]].mean(axis=1)
    side = (centres - point) @ normal
    below, above = members[side < 0], members[side >= 0]
    total = float(areas.sum())
    if not len(below) or not len(above):
        raise SystemExit("design_cuts: the cut leaves one side empty; move the line")

    parts = [p for p in parts if p["name"] != args.split]
    for name, group in ((low_name, below), (high_name, above)):
        parts.append({"name": name, "faces": int(len(group)),
                      "area": round(float(areas[group].sum() / total), 5),
                      "cut_from": args.split, "cut": args.cut,
                      "face_indices": [int(v) for v in group]})
    document["parts"] = parts
    out = args.output or args.parts
    with open(out, "w") as handle:
        json.dump(document, handle, indent=2)

    print("cut %r along %s" % (args.split, args.cut))
    print("  %-28s %6.2f%% of the model  (%d faces)"
          % (low_name, 100 * areas[below].sum() / total, len(below)))
    print("  %-28s %6.2f%% of the model  (%d faces)"
          % (high_name, 100 * areas[above].sum() / total, len(above)))
    print("  geometry untouched -- only which part each triangle belongs to changed")
    print("  wrote %s" % out)

    import trimesh
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    colours = np.tile(np.array([0.88, 0.88, 0.90]), (len(faces), 1))
    colours[below] = (0.20, 0.55, 0.90)
    colours[above] = (0.95, 0.55, 0.15)
    checks = os.path.join(args.session, "designcuts")
    os.makedirs(checks, exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in args.split).strip("-").lower()
    for name in dict.fromkeys([view] + args.views.split(",")):
        if name.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[name.strip()], 900)
            raster.save_png(os.path.join(checks, "%s-%s.png" % (slug, name.strip())),
                            image)
    print("  check %s/%s-*.png -- blue is %r, orange is %r"
          % (checks, slug, low_name, high_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
