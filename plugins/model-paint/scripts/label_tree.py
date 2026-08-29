"""A complete, hierarchical, addressable label map of the surface.

Colouring by clicking at pixels does not survive contact with a real model. A click
names one place, the selection around it is argued about, and nothing says whether
the rest of the surface was ever accounted for. What a colour plan actually needs is
a *map*: every face belongs to a named region, every region can be subdivided into
its own named parts, and each name carries coordinates so a person and an agent can
point at the same thing. Then "the barnacles are orange" is an instruction that can
be executed, and "the barnacle apertures are black" is the same instruction one level
down.

The levels are the scale ladder, which is not a coincidence -- it is the measured
reason this works. A patch scale is a zoom level, and features are only cleanly
separable near their own: on the shell the flank barnacle band comes apart cleanly at
400 patches and shatters at 12,800, while the upper whorl colony is clean at 12,800
and only partly found at 400. A single scale therefore cannot describe both a rib
band and the aperture of one barnacle sitting on it. A hierarchy can, by resolving
each level at the rung that suits it: coarse regions at a coarse rung, their
sub-features at a finer one.

Two properties are enforced rather than hoped for:

**Every level is a partition.** No face is unlabelled and no face carries two labels.
Independent selections measured 24.61% of the surface in no part and 26.86% claimed
twice, and painting from that pile means whichever selection was written last wins.
Here each level is built by clustering *all* of the parent's patches, so coverage is
total by construction; `fill_nearest` closes the few faces that clustering strands.

**Naming is the human's, geometry is the tool's.** This script never invents a name.
It proposes regions, renders them in distinct colours, and reports for each one an
area, a centroid and a `view:x,y` coordinate where it can be seen. A person or an
agent looks at that render and supplies the vocabulary -- "umbilicus", "limpet cap",
"shell shard" -- which no hardcoded anatomy list would have held. Regions keep their
`region-N` placeholder until someone names them, and an unnamed region is visible as
unnamed rather than quietly folded into its neighbour.

    label_tree.py --session work/ --rung 400 --regions 12          # level 0
    label_tree.py --session work/ --name "region-3" --new-name "barnacle field"
    label_tree.py --session work/ --parent "barnacle field" --rung 6400 --regions 5
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from patch_features import (DESCRIPTORS, CLUSTER_ON, describe_patches,   # noqa: E402
                            standardise, cluster)
from resolve_parts import fill_nearest                               # noqa: E402
from scale_ladder import ladder_path                                 # noqa: E402

TREE = "label_tree.json"
VIEWS_FOR_COORDS = ["front", "back", "left", "right", "top", "iso", "iso2"]

# Distinct, flat hues. Labels are being told apart, not shaded.
PALETTE = np.array([
    [0.90, 0.24, 0.20], [0.20, 0.55, 0.90], [0.30, 0.75, 0.35], [0.95, 0.65, 0.15],
    [0.65, 0.35, 0.85], [0.10, 0.70, 0.70], [0.95, 0.45, 0.65], [0.55, 0.45, 0.25],
    [0.45, 0.80, 0.20], [0.20, 0.35, 0.70], [0.85, 0.35, 0.45], [0.40, 0.65, 0.60],
    [0.75, 0.55, 0.90], [0.60, 0.60, 0.20], [0.25, 0.60, 0.45], [0.90, 0.50, 0.30],
])


def load_tree(session_dir):
    path = os.path.join(session_dir, TREE)
    if os.path.exists(path):
        with open(path) as handle:
            return json.load(handle)
    return {"nodes": []}


def save_tree(session_dir, tree):
    with open(os.path.join(session_dir, TREE), "w") as handle:
        json.dump(tree, handle, indent=2)


def find(tree, name):
    for node in tree["nodes"]:
        if node["name"] == name:
            return node
    return None


def visible_coordinate(session, faces_of_region):
    """A view:x,y where this region is actually visible, so the name is pointable.

    A centroid is not enough on its own: the centroid of a band wrapping a whorl can
    sit inside the model, and a coordinate nobody can see is not a handle.
    """
    wanted = set(int(f) for f in faces_of_region)
    best = None
    for view in VIEWS_FOR_COORDS:
        key = "pick_%s" % view
        if key not in session.files:
            continue
        pick = session[key]
        hits = np.isin(pick, list(wanted)[:200000])
        count = int(hits.sum())
        if count and (best is None or count > best[0]):
            ys, xs = np.nonzero(hits)
            middle = len(xs) // 2
            best = (count, "%s:%d,%d" % (view, xs[middle], ys[middle]))
    return best[1] if best else None


def describe(session, session_dir, labels_for_level, member_faces):
    """Cluster-ready descriptors for the patches covering `member_faces`."""
    faces = session["faces"]
    centres = session["vertices"][faces].mean(axis=1)
    diagonal = float(np.linalg.norm(np.ptp(session["vertices"], axis=0))) or 1.0
    relief_path = os.path.join(session_dir, "relief.npy")
    fields = {"relief": np.load(relief_path) if os.path.exists(relief_path)
              else np.zeros(len(faces)),
              "occlusion": session["occlusion"], "roughness": session["roughness"],
              "thickness": session["thickness"]}
    rows, stats = describe_patches(labels_for_level, centres, session["normals"],
                                   session["areas"], fields, diagonal)
    columns = [DESCRIPTORS.index(name) for name in CLUSTER_ON]
    return standardise(rows)[:, columns], stats


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--rung", type=int, help="ladder rung to resolve this level at")
    parser.add_argument("--regions", type=int, default=10,
                        help="how many regions to propose at this level")
    parser.add_argument("--parent", default=None,
                        help="subdivide this label instead of the whole surface")
    parser.add_argument("--name", default=None, help="rename: the label to rename")
    parser.add_argument("--new-name", default=None, help="rename: its new name")
    parser.add_argument("--show", action="store_true", help="print the tree and stop")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    tree = load_tree(args.session)
    faces, areas = session["faces"], session["areas"]
    total_area = float(areas.sum())

    if args.show:
        if not tree["nodes"]:
            print("no labels yet")
            return 0
        for node in tree["nodes"]:
            depth = 0
            walk = node
            while walk.get("parent"):
                walk = find(tree, walk["parent"])
                depth += 1
                if walk is None:
                    break
            print("%s%-38s rung %5d  %6.2f%%  %s"
                  % ("  " * depth, node["name"], node["rung"],
                     100 * node["area"], node.get("at") or "-"))
        covered = np.zeros(len(faces), dtype=bool)
        for node in tree["nodes"]:
            if not node.get("parent"):
                covered[node["face_indices"]] = True
        print("\nlevel 0 covers %.2f%% of faces" % (100 * covered.mean()))
        return 0

    if args.name:
        node = find(tree, args.name)
        if node is None:
            raise SystemExit("label_tree: no label %r" % args.name)
        if not args.new_name:
            raise SystemExit("label_tree: --name needs --new-name")
        if find(tree, args.new_name):
            raise SystemExit("label_tree: %r already exists" % args.new_name)
        for other in tree["nodes"]:
            if other.get("parent") == node["name"]:
                other["parent"] = args.new_name
        node["name"] = args.new_name
        save_tree(args.session, tree)
        print("renamed to %r" % args.new_name)
        return 0

    if args.rung is None:
        parser.error("--rung is required when building a level")
    path = ladder_path(args.session, args.rung)
    if not os.path.exists(path):
        raise SystemExit("label_tree: rung %d not built; run scale_ladder.py --build"
                         % args.rung)
    patch_labels = np.load(path)

    if args.parent:
        parent = find(tree, args.parent)
        if parent is None:
            raise SystemExit("label_tree: no label %r" % args.parent)
        member_faces = np.array(parent["face_indices"], dtype=np.int64)
        prefix = "%s/" % parent["name"]
    else:
        parent = None
        member_faces = np.arange(len(faces))
        prefix = ""

    inside = np.zeros(len(faces), dtype=bool)
    inside[member_faces] = True
    # Only patches genuinely within the parent take part, so a subdivision cannot
    # reach outside the region it is subdividing.
    counts = np.bincount(patch_labels[inside], minlength=int(patch_labels.max()) + 1)
    live = np.flatnonzero(counts > 0)
    if len(live) < 2:
        raise SystemExit("label_tree: rung %d gives only %d patch(es) inside %r; "
                         "use a finer rung" % (args.rung, len(live), args.parent))

    space, stats = describe(session, args.session, patch_labels, member_faces)
    groups = min(args.regions, len(live))
    assignment, _centres = cluster(space[live], groups, seed=args.seed)

    # Faces of the parent, grouped. Clustering assigns patches; a patch straddling
    # the parent boundary contributes only its inside faces.
    region_of_patch = {int(p): int(g) for p, g in zip(live, assignment)}
    face_region = np.full(len(faces), -1, dtype=np.int32)
    for face_index in member_faces:
        face_region[face_index] = region_of_patch.get(int(patch_labels[face_index]), -1)
    if (face_region[member_faces] < 0).any():
        filled = fill_nearest(face_region, session["pairs"])
        face_region[member_faces] = filled[member_faces]

    tree["nodes"] = [n for n in tree["nodes"]
                     if not (n.get("parent") == (parent["name"] if parent else None)
                             and n.get("auto"))]
    added = []
    for group in range(groups):
        mask = (face_region == group) & inside
        if not mask.any():
            continue
        indices = np.flatnonzero(mask)
        name = "%sregion-%d" % (prefix, group)
        while find(tree, name):
            name += "'"
        node = {"name": name, "parent": parent["name"] if parent else None,
                "rung": args.rung, "auto": True,
                "area": round(float(areas[mask].sum() / total_area), 5),
                "faces": int(mask.sum()),
                "at": visible_coordinate(session, indices),
                "centroid": [round(float(v), 2) for v in
                             session["vertices"][faces[indices]].mean(axis=(0, 1))],
                "face_indices": [int(v) for v in indices]}
        tree["nodes"].append(node)
        added.append(node)
    save_tree(args.session, tree)

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = np.tile(np.array([0.88, 0.88, 0.90]), (len(faces), 1))
    for index, node in enumerate(added):
        colours[node["face_indices"]] = PALETTE[index % len(PALETTE)]
    out = os.path.join(args.session, "labels")
    os.makedirs(out, exist_ok=True)
    slug = (parent["name"].replace("/", "-") if parent else "level0")
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug).strip("-")
    for view in (["iso", "front"] if not parent else ["iso"]):
        image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view], 900)
        raster.save_png(os.path.join(out, "%s-%s.png" % (slug, view)), image)

    print("%d regions inside %s at rung %d"
          % (len(added), parent["name"] if parent else "the whole surface", args.rung))
    for index, node in enumerate(added):
        rgb = PALETTE[index % len(PALETTE)]
        print("  %-22s %6.2f%%  at %-16s rgb(%3d,%3d,%3d)"
              % (node["name"], 100 * node["area"], node["at"] or "-",
                 *(int(255 * c) for c in rgb)))
    print("\n  render: %s/%s-*.png" % (out, slug))
    print("  LOOK at it, then name each region by its colour:")
    print("    label_tree.py --session %s --name '%s' --new-name '<what it is>'"
          % (args.session, added[0]["name"] if added else "region-0"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
