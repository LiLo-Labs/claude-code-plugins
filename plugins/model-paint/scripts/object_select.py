"""Point at one thing; get every other thing like it. No k, no partition.

Classes have been produced here by cutting the object feature space into k pieces, and
every version of that has failed the same way. Repeated instances of one feature do not
form a tidy island -- they form a continuum, because real barnacle cones run from 1.5mm
to 4mm and the population is dense in between. A partition must put its boundary
somewhere, and wherever it goes it runs through the middle of that continuum: measured
on the shell, one cone population was cut across four classes at 1.83, 2.14, 2.50 and
3.42mm, which is why some colonies came out a different colour from others.

Every repair attempted made it worse or moved it. Merging adjacent look-alikes fixed
four pairs and broke a hundred and fifty. Adaptive merging in feature space reached 100%
on that test by swallowing 51% of the model into one class. Dropping a feature traded
one defect for another. The pattern is not a bad algorithm, it is the wrong question:
"how many kinds of thing are on this model, and where are the boundaries between them"
is not answerable from geometry, because it is semantic.

So stop asking. A person -- or an agent with eyes -- points at one barnacle and says
"that". This finds every object like it, anywhere on the model, and renders the answer
so the judgement can be checked and the radius adjusted by looking. Nothing is
partitioned, nothing else is disturbed, and objects nobody claimed stay unclaimed and
show up in the residue rather than being silently swept into the nearest class.

That is the same shape as the rest of this pipeline: geometry proposes, vision decides.

    object_select.py --session work/ --at iso:430,300 --name "barnacle cones"
    object_select.py --session work/ --at iso:430,300 --radius 0.9 --name "..." --commit
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from object_classes import object_rows, hidden_underside, standardise  # noqa: E402

HIGHLIGHT = (0.95, 0.25, 0.10)
EXEMPLAR = (0.10, 0.85, 1.0)
DIMMED = (0.86, 0.86, 0.88)
CLAIMED = (0.62, 0.62, 0.66)


def load(session_dir):
    session = np.load(os.path.join(session_dir, "session.npz"))
    index = np.load(os.path.join(session_dir, "scale_space.npz"))
    objects = np.load(os.path.join(session_dir, "index_objects.npy"))
    rows = object_rows(session, index, objects, 4.0)
    buried = hidden_underside(session)
    count = int(objects.max()) + 1
    order = np.argsort(objects, kind="stable")
    bounds = np.searchsorted(objects[order], np.arange(count + 1))
    hidden = np.zeros(count, dtype=bool)
    for node in range(count):
        members = order[bounds[node]:bounds[node + 1]]
        if len(members):
            hidden[node] = buried[members].mean() > 0.5
    live = np.flatnonzero(~hidden)
    space = standardise(rows, live)
    return session, objects, space, live, hidden


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--at", action="append", required=True,
                        help="view:x,y pointing at one example; repeat for several")
    parser.add_argument("--radius", type=float, default=0.8,
                        help="how alike an object must be, in standard deviations of "
                             "the feature space; raise it until the render includes "
                             "what you meant and no more")
    parser.add_argument("--name", required=True)
    parser.add_argument("--commit", action="store_true",
                        help="write this into parts.json and mark its objects claimed")
    parser.add_argument("--parts", default="selected_parts.json")
    parser.add_argument("--views", default="iso,front")
    args = parser.parse_args()

    session, objects, space, live, hidden = load(args.session)
    faces, areas = session["faces"], session["areas"]
    total = float(areas.sum())

    chosen = []
    for spec in args.at:
        try:
            view, coords = spec.split(":", 1)
            x, y = (int(v) for v in coords.split(","))
        except ValueError:
            parser.error("--at wants view:x,y, got %r" % spec)
        key = "pick_%s" % view
        if key not in session.files:
            parser.error("session has no view %r" % view)
        face = raster.region_at(None, session[key], x, y)
        if face is None:
            parser.error("nothing under %s -- that pixel is background" % spec)
        chosen.append(int(objects[face]))
    chosen = sorted(set(chosen))

    parts_path = os.path.join(args.session, args.parts)
    document = {"parts": []}
    if os.path.exists(parts_path):
        with open(parts_path) as handle:
            document = json.load(handle)
    claimed = set()
    for part in document.get("parts", []):
        if part["name"] != args.name:
            claimed.update(part.get("object_ids", []))

    # Distance to the NEAREST exemplar, so several clicks describe a population with
    # some spread rather than forcing one average that nothing actually matches.
    distance = np.min([np.linalg.norm(space - space[node], axis=1) for node in chosen],
                      axis=0)
    like = distance <= args.radius
    like[hidden] = False
    for node in chosen:
        like[node] = True
    taken = np.array([node in claimed for node in range(len(like))])
    fresh = like & ~taken

    mask = np.isin(objects, np.flatnonzero(fresh))
    share = float(areas[mask].sum() / total)
    print("%s: %d objects, %.2f%% of the surface (radius %.2f)"
          % (args.name, int(fresh.sum()), 100 * share, args.radius))
    if (like & taken).any():
        print("  %d matching objects already belong to another part; left alone"
              % int((like & taken).sum()))
    nearest = np.sort(distance[~like & ~hidden])
    if len(nearest):
        print("  next nearest unselected object sits at %.2f -- raise the radius past "
              "that to include it" % nearest[0])

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = np.tile(np.array(DIMMED), (len(faces), 1))
    if taken.any():
        colours[np.isin(objects, np.flatnonzero(taken))] = CLAIMED
    colours[mask] = HIGHLIGHT
    for node in chosen:
        colours[objects == node] = EXEMPLAR
    checks = os.path.join(args.session, "selected")
    os.makedirs(checks, exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in args.name).strip("-").lower()
    views = list(dict.fromkeys([spec.split(":", 1)[0] for spec in args.at]
                               + args.views.split(",")))
    for view in views:
        if view.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()], 900)
            raster.save_png(os.path.join(checks, "%s-%s.png" % (slug, view.strip())),
                            image)
    print("  %s/%s-*.png -- cyan is what you pointed at, orange is everything like it,"
          % (checks, slug))
    print("  grey is already claimed by another part. LOOK before committing.")

    if args.commit:
        document["parts"] = [p for p in document.get("parts", []) if p["name"] != args.name]
        document["parts"].append({
            "name": args.name, "radius": args.radius, "exemplars": list(args.at),
            "objects": int(fresh.sum()), "area": round(share, 5),
            "object_ids": [int(v) for v in np.flatnonzero(fresh)],
            "face_indices": [int(v) for v in np.flatnonzero(mask)]})
        with open(parts_path, "w") as handle:
            json.dump(document, handle, indent=2)
        done = set()
        for part in document["parts"]:
            done.update(part.get("object_ids", []))
        rest = np.array([node for node in np.flatnonzero(~hidden) if node not in done])
        left = float(areas[np.isin(objects, rest)].sum() / total) if len(rest) else 0.0
        print("  committed. %d objects (%.2f%% of the surface) still unclaimed"
              % (len(rest), 100 * left))
    return 0


if __name__ == "__main__":
    sys.exit(main())
