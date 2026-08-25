"""Resolve one click at every scale at once, so an agent can pick by looking.

The diagnosis on record is that a patch scale is a zoom level and **a feature is
only cleanly separable near its own scale**: at 400 patches a whole rib is one
object, at 13,000 a single barnacle cone is several. Two things were tried against
that and both dodged it. Segmenting at one fixed scale and searching for a tolerance
that suits every feature cannot work, because the features differ in size, not in
threshold. Averaging a Monte Carlo ensemble over scales does not work either: it
blurs the ladder into one consensus instead of choosing a rung, which is why its
selections came out small but still mixed -- a barnacle field and the rib beside it
average into something that is neither.

So stop collapsing the ladder and expose it. One click, resolved independently at
every rung, rendered side by side in a single contact sheet. Then the choice of
scale is made by looking at the alternatives, which is the one part of this that
vision is genuinely better at than any statistic: "the third one is the colony, the
fourth has swallowed the rib" is an easy judgement from an image and a hard one from
an area percentage. The numbers alongside each rung are there to describe what was
picked, not to pick it.

Build the ladder once per session (minutes, one segmentation per rung, cached), then
every click is seconds.

    scale_ladder.py --session work/ --build
    scale_ladder.py --session work/ --at iso:562,247 --name "barnacle colony"
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from paintlib.mesh_slic import superpatches                          # noqa: E402
from patch_features import (DESCRIPTORS, CLUSTER_ON, describe_patches,   # noqa: E402
                            standardise)
from patch_select import patch_contacts, grow_local                  # noqa: E402
from oversegment import load_fields                                  # noqa: E402

DEFAULT_LADDER = [400, 800, 1600, 3200, 6400, 12800]
HIGHLIGHT = (1.0, 0.30, 0.10)
EXEMPLAR = (0.10, 0.85, 1.0)
DIMMED = (0.86, 0.86, 0.88)


def ladder_path(session_dir, scale):
    return os.path.join(session_dir, "ladder_%d.npy" % scale)


def build(session_dir, session, scales, iterations, seed):
    faces = session["faces"]
    centres = session["vertices"][faces].mean(axis=1)
    fields = load_fields(session_dir, session)
    import time
    for scale in scales:
        path = ladder_path(session_dir, scale)
        if os.path.exists(path):
            print("  %5d patches  cached" % scale)
            continue
        start = time.time()
        labels = superpatches(centres, session["normals"], session["pairs"],
                              target_patches=scale, fields=fields,
                              iterations=iterations, seed=seed)
        np.save(path, labels)
        print("  %5d patches  %4d actual  %.0fs"
              % (scale, labels.max() + 1, time.time() - start))
        sys.stdout.flush()


def depth_gates(session, labels, centres, forward, max_depth, max_drop):
    """Per-contact geometric gaps: along the view axis, and in world height.

    This is a different kind of cut from the ensemble edge statistic that failed,
    and the difference is why it can work where that could not. That statistic
    scattered its blocked edges across the surface -- 4.66% of contacts against a
    patch graph of mean degree 5.8 -- and a scattered subset never closes a curve,
    so growth routed around every gap.

    A depth step does not scatter. Where the surface turns away and something else
    stands in front of it, the jump runs along the whole silhouette, so the blocked
    contacts already form a curve. Height works the same way: the shell meets its
    rock base along a line, not at isolated points, which is exactly where the worst
    selections leaked -- barnacles on the shell reaching down into the base rock and
    the coral standing on it.

    Both gaps are means over each patch, so a gradual slope crosses freely and only a
    genuine step blocks. Returns {(a, b): True} for contacts growth may not cross.
    """
    count = int(labels.max()) + 1
    depth = centres @ forward
    height = centres[:, 2]
    sums = np.bincount(labels, weights=depth, minlength=count)
    highs = np.bincount(labels, weights=height, minlength=count)
    sizes = np.maximum(np.bincount(labels, minlength=count), 1)
    mean_depth, mean_height = sums / sizes, highs / sizes

    left, right = labels[session["pairs"][:, 0]], labels[session["pairs"][:, 1]]
    crossing = left != right
    blocked = {}
    for a, b in zip(left[crossing], right[crossing]):
        key = (int(min(a, b)), int(max(a, b)))
        if key in blocked:
            continue
        if max_depth > 0 and abs(mean_depth[key[0]] - mean_depth[key[1]]) > max_depth:
            blocked[key] = True
        elif max_drop > 0 and abs(mean_height[key[0]] - mean_height[key[1]]) > max_drop:
            blocked[key] = True
    return blocked


def select_at(session, labels, fields, click_faces, tolerance, forward=None,
              max_depth=0.0, max_drop=0.0):
    """Grow from the click on one rung. Returns (face mask, patch count)."""
    faces = session["faces"]
    centres = session["vertices"][faces].mean(axis=1)
    diagonal = float(np.linalg.norm(np.ptp(session["vertices"], axis=0))) or 1.0
    rows, _stats = describe_patches(labels, centres, session["normals"],
                                    session["areas"], fields, diagonal)
    columns = [DESCRIPTORS.index(name) for name in CLUSTER_ON]
    space = standardise(rows)[:, columns]
    chosen = sorted({int(labels[face]) for face in click_faces})
    distance = np.min([np.linalg.norm(space - space[patch], axis=1)
                       for patch in chosen], axis=0)
    similar = distance <= (tolerance * float(np.sqrt(len(columns))))
    touching, _ = patch_contacts(labels, session["pairs"], None)

    blocked = {}
    if forward is not None and (max_depth > 0 or max_drop > 0):
        blocked = depth_gates(session, labels, centres, forward, max_depth, max_drop)
    # grow_local blocks a contact whose value is at or below the threshold, so a
    # gated contact carries 0 and an ungated one infinity.
    strengths = {key: 0.0 for key in blocked}
    keep = grow_local(chosen, similar, touching, strengths, 0.5 if strengths else 0)
    return keep[labels], int(keep.sum())


def contact_sheet(images, columns=3):
    """Tile renders into one image so the rungs are compared, not remembered."""
    if not images:
        return None
    rows = (len(images) + columns - 1) // columns
    height, width, _ = images[0].shape
    sheet = np.full((rows * height, columns * width, 3), 255, dtype=np.uint8)
    for index, image in enumerate(images):
        r, c = divmod(index, columns)
        sheet[r * height:(r + 1) * height, c * width:(c + 1) * width] = image
    return sheet


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--build", action="store_true",
                        help="segment each rung and cache it, then stop")
    parser.add_argument("--scales", default=",".join(str(s) for s in DEFAULT_LADDER))
    parser.add_argument("--at", action="append",
                        help="view:x,y pointing at an example; repeat for several")
    parser.add_argument("--name", default="ladder")
    parser.add_argument("--tolerance", type=float, default=0.30)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-depth-mm", type=float, default=0.0,
                        help="refuse to grow across a step this large along the "
                             "view axis; 0 disables")
    parser.add_argument("--max-drop-mm", type=float, default=0.0,
                        help="refuse to grow across a step this large in world "
                             "height; 0 disables")
    parser.add_argument("--size", type=int, default=460,
                        help="pixels per rung in the contact sheet")
    args = parser.parse_args()

    scales = [int(p) for p in args.scales.split(",") if p.strip()]
    session_path = os.path.join(args.session, "session.npz")
    if not os.path.exists(session_path):
        parser.error("no session.npz in %s; run inspect_model.py first" % args.session)
    session = np.load(session_path)

    if args.build:
        print("building scale ladder over %d faces" % len(session["faces"]))
        build(args.session, session, scales, args.iterations, args.seed)
        return 0

    if not args.at:
        parser.error("--at is required unless --build")
    missing = [s for s in scales if not os.path.exists(ladder_path(args.session, s))]
    if missing:
        raise SystemExit("scale_ladder: rungs %s not built; run --build first"
                         % ", ".join(str(s) for s in missing))

    click_faces = []
    for spec in args.at:
        try:
            view, coords = spec.split(":", 1)
            x, y = (int(part) for part in coords.split(","))
        except ValueError:
            parser.error("--at wants view:x,y, got %r" % spec)
        face = raster.region_at(None, session["pick_%s" % view], x, y)
        if face is None:
            parser.error("nothing under %s -- that pixel is background" % spec)
        click_faces.append(int(face))

    fields = {"relief": np.load(os.path.join(args.session, "relief.npy"))
              if os.path.exists(os.path.join(args.session, "relief.npy"))
              else np.zeros(len(session["faces"])),
              "occlusion": session["occlusion"],
              "roughness": session["roughness"],
              "thickness": session["thickness"]}

    import trimesh
    vertices, faces, areas = session["vertices"], session["faces"], session["areas"]
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    view = args.at[0].split(":", 1)[0]
    elevation, azimuth = raster.VIEWS[view]
    forward, _right, _up = raster._camera(elevation, azimuth)

    images, rungs = [], []
    for scale in scales:
        labels = np.load(ladder_path(args.session, scale))
        mask, patches = select_at(session, labels, fields, click_faces,
                                  args.tolerance, forward,
                                  args.max_depth_mm, args.max_drop_mm)
        share = float(areas[mask].sum() / areas.sum())
        colours = np.tile(np.array(DIMMED), (len(faces), 1))
        colours[mask] = HIGHLIGHT
        for face in click_faces:
            colours[face] = EXEMPLAR
        image, _ = raster.render_view(mesh, colours, elevation, azimuth, args.size)
        images.append(image)
        rungs.append({"scale": scale, "patches": patches,
                      "faces": int(mask.sum()), "area": round(share, 5)})
        print("  rung %5d: %4d patches, %7d triangles, %6.2f%% of surface"
              % (scale, patches, mask.sum(), 100 * share))
        sys.stdout.flush()

    checks = os.path.join(args.session, "ladders")
    os.makedirs(checks, exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in args.name).strip("-").lower()
    sheet = contact_sheet(images)
    sheet_path = os.path.join(checks, "%s.png" % slug)
    raster.save_png(sheet_path, sheet)
    with open(os.path.join(checks, "%s.json" % slug), "w") as handle:
        json.dump({"name": args.name, "at": list(args.at),
                   "tolerance": args.tolerance, "rungs": rungs}, handle, indent=2)

    print("\ncontact sheet: %s" % sheet_path)
    print("  reading order is left to right, top to bottom: %s"
          % ", ".join(str(s) for s in scales))
    print("  LOOK at it and pick the rung where the feature is whole and stops where")
    print("  it stops. The area column cannot tell you that; the picture can.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
