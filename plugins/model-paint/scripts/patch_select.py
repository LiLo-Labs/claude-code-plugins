"""Select by example: point at one patch, get every patch like it.

With the surface tiled into patches whose boundaries are already right, selection
stops being a matter of tuning a threshold until the edge lands somewhere
acceptable. Each patch is a discrete object with a size, a shape, a depth and a
texture, so the useful question becomes "which other patches are the same kind of
thing as this one" -- and that is answerable by distance in descriptor space.

    python3 patch_select.py --session work/ --at iso:562,247 \\
        --name "barnacle cone" --tolerance 0.18

Two modes, and the difference matters more than it looks:

  --grow local  (default) spread from the exemplar to patches that TOUCH it and
                resemble it, stopping where the resemblance stops. This is what
                someone means by pointing at a barnacle field.
  --grow class  take every patch on the model resembling the exemplar, touching
                or not.

Class mode is the seductive one and it measures worse. Six shape descriptors
cannot define "barnacle cone" across a whole model: tried on the shell, one click
scored F1 35% against hand-verified selections, picking some cones while missing
identical ones beside them and firing on shell fragments. The descriptors are
noisy at the scale of a single patch, and a global threshold turns that noise into
scattered false positives everywhere.

Locally the same descriptors work, because the comparison is against a neighbour
rather than against the whole model, and because a real feature is contiguous.
Growth stopping at the edge of the field is a feature, not a limitation: it is
what makes the selection something a person can predict and correct.

Every run writes a verification render, because a selection nobody looked at is
not a selection anyone should paint from.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                        # noqa: E402
from patch_features import (DESCRIPTORS, CLUSTER_ON, describe_patches,   # noqa: E402
                            standardise)

HIGHLIGHT = (1.0, 0.30, 0.10)
EXEMPLAR = (0.10, 0.85, 1.0)
DIMMED = (0.86, 0.86, 0.88)


def load_context(session_dir):
    session = np.load(os.path.join(session_dir, "session.npz"))
    patch_path = os.path.join(session_dir, "mesh_patches.npy")
    if not os.path.exists(patch_path):
        raise SystemExit("patch_select: no mesh_patches.npy; run the segmentation first")
    labels = np.load(patch_path)

    relief_path = os.path.join(session_dir, "relief.npy")
    fields = {"relief": np.load(relief_path) if os.path.exists(relief_path)
              else np.zeros(len(session["faces"])),
              "occlusion": session["occlusion"],
              "roughness": session["roughness"],
              "thickness": session["thickness"]}
    return session, labels, fields


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--at", action="append", required=True,
                        help="view:x,y pointing at an example; repeat for several")
    parser.add_argument("--name", required=True)
    parser.add_argument("--grow", default="local", choices=["local", "class"],
                        help="local: spread to touching, similar patches. "
                             "class: every similar patch on the model")
    parser.add_argument("--tolerance", type=float, default=0.18,
                        help="how alike a patch must be, 0 (identical) to 1 (anything)")
    parser.add_argument("--near-mm", type=float, default=None,
                        help="also require the patch to sit within this distance")
    parser.add_argument("--same-height", type=float, default=None,
                        help="also require a similar height, as a fraction 0..1")
    parser.add_argument("--max-share", type=float, default=0.35,
                        help="refuse a selection larger than this share of the model")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    session, labels, fields = load_context(args.session)
    vertices, faces, areas = session["vertices"], session["faces"], session["areas"]
    centres = vertices[faces].mean(axis=1)
    diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0))) or 1.0

    rows, stats = describe_patches(labels, centres, session["normals"], areas,
                                   fields, diagonal)
    columns = [DESCRIPTORS.index(name) for name in CLUSTER_ON]
    space = standardise(rows)[:, columns]

    chosen = []
    for spec in args.at:
        try:
            view, coords = spec.split(":", 1)
            x, y = (int(part) for part in coords.split(","))
        except ValueError:
            parser.error("--at wants view:x,y, got %r" % spec)
        key = "pick_%s" % view
        if key not in session.files:
            parser.error("session has no view %r" % view)
        face = raster.region_at(None, session[key], x, y)
        if face is None:
            parser.error("nothing under %s -- that pixel is background" % spec)
        chosen.append(int(labels[face]))
    chosen = sorted(set(chosen))

    # Distance to the nearest exemplar, so several clicks describe a class with
    # some spread rather than forcing one average nothing actually matches.
    distance = np.min([np.linalg.norm(space - space[patch], axis=1)
                       for patch in chosen], axis=0)
    scale = float(np.sqrt(len(columns)))
    similar = distance <= (args.tolerance * scale)

    if args.grow == "local":
        # Which patches touch which, from the face graph.
        pairs = session["pairs"]
        left, right = labels[pairs[:, 0]], labels[pairs[:, 1]]
        crossing = left != right
        touching = {}
        for a, b in zip(left[crossing], right[crossing]):
            touching.setdefault(int(a), set()).add(int(b))
            touching.setdefault(int(b), set()).add(int(a))

        reached = set(chosen)
        queue = list(chosen)
        while queue:
            patch = queue.pop()
            for neighbour in touching.get(patch, ()):
                if neighbour in reached or not similar[neighbour]:
                    continue
                reached.add(neighbour)
                queue.append(neighbour)
        keep = np.zeros(len(similar), dtype=bool)
        keep[sorted(reached)] = True
        similar = keep

    patch_centres = np.array([stat["centre"] if stat else [0.0, 0.0, 0.0]
                              for stat in stats])
    if args.near_mm is not None:
        near = np.min([np.linalg.norm(patch_centres - patch_centres[patch], axis=1)
                       for patch in chosen], axis=0)
        similar &= near <= args.near_mm
    if args.same_height is not None:
        heights = rows[:, DESCRIPTORS.index("height")]
        gap = np.min([np.abs(heights - heights[patch]) for patch in chosen], axis=0)
        similar &= gap <= args.same_height

    picked = np.flatnonzero(similar)
    mask = np.isin(labels, picked)
    share = float(areas[mask].sum() / areas.sum())
    if share > args.max_share:
        sys.stderr.write(
            "patch_select: %r matched %.1f%% of the model, past the %.0f%% limit.\n"
            "Lower --tolerance, or constrain it with --near-mm / --same-height.\n"
            % (args.name, 100 * share, 100 * args.max_share))
        return 2

    parts_path = os.path.join(args.session, "patch_parts.json")
    document = {"parts": []}
    if os.path.exists(parts_path):
        with open(parts_path) as handle:
            document = json.load(handle)
    existing = [part for part in document.get("parts", []) if part["name"] == args.name]
    if existing and not args.replace:
        sys.stderr.write("patch_select: %r already exists; pass --replace\n" % args.name)
        return 2
    document["parts"] = [part for part in document.get("parts", [])
                         if part["name"] != args.name]
    document["parts"].append({
        "name": args.name, "patches": len(picked), "faces": int(mask.sum()),
        "area": round(share, 5), "tolerance": args.tolerance,
        "exemplars": [spec for spec in args.at],
        "face_indices": [int(v) for v in np.flatnonzero(mask)]})
    with open(parts_path, "w") as handle:
        json.dump(document, handle, indent=2)

    import trimesh
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    colours = np.tile(np.array(DIMMED), (len(faces), 1))
    colours[mask] = HIGHLIGHT
    for patch in chosen:
        colours[labels == patch] = EXEMPLAR
    checks = os.path.join(args.session, "selections")
    os.makedirs(checks, exist_ok=True)
    slug = "".join(ch if ch.isalnum() else "-" for ch in args.name).strip("-").lower()
    views = list(dict.fromkeys([spec.split(":", 1)[0] for spec in args.at] + ["iso"]))
    for view in views:
        if view not in raster.VIEWS:
            continue
        image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view], 900)
        raster.save_png(os.path.join(checks, "%s-%s.png" % (slug, view)), image)

    print("%s: %d patches, %d triangles, %.2f%% of surface area"
          % (args.name, len(picked), mask.sum(), 100 * share))
    print("  from %d exemplar(s) at tolerance %.2f" % (len(chosen), args.tolerance))
    print("  check %s/%s-*.png (cyan = what you pointed at, orange = the class)"
          % (checks, slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
