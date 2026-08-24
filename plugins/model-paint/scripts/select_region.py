"""Turn something an agent can see into triangles it can paint.

Point at a pixel in one of the session views, choose how the selection should
spread from there, and get back a named part plus a highlight render to check the
selection actually covers the thing that was pointed at. Getting it wrong is
cheap and visible, which is the whole idea: the agent looks, selects, looks again,
and corrects, instead of trusting a threshold it cannot see the effect of.

    python3 select_region.py --session work/ --at iso:562,247 \
        --grow rough --name "barnacle cluster, upper right"

Growth strategies, and when each is the right instrument:

  rough    spread while the surface stays bumpy -- crust, scales, gravel
  relief   spread while the surface stays proud of its surroundings -- a single
           dome, stud, rivet or boss, and any compact cluster of them. This is the
           one to reach for when `rough` floods: a field of texture is continuous
           in roughness even where a person sees separate clumps, but each clump
           still stands proud on its own.
  thin     spread while the solid stays thin -- horns, spikes, tube worms, fins
  cavity   spread while the surface stays recessed -- inside a crack or an opening
  smooth   spread while the surface stays flat and open -- panels, plates
  patch    spread until a crease stops it -- anything with a hard edge round it

--radius-mm bounds any strategy to a sphere around the seed. Most things a person
points at are local, and a bound is a cheaper, more honest fix than loosening a
threshold until the selection happens to stop in the right place.

--connect decides whether the selection has to be one connected surface:
  flood   (default) spread across neighbours, so the result is one piece
  radius  take every face within --radius-mm that satisfies the strategy, whether
          or not it connects to the seed
The difference matters for a CLUMP of separate things -- a patch of barnacles, a
row of rivets, a cluster of studs. Each item stands proud on its own but the
surface dips between them, so flood growth reaches one item and stops. What a
person means by pointing at the clump is "these, around here", which is what
radius gives.

Every strategy is seeded from the picked triangle and bounded by a share of the
model, so a runaway selection fails loudly instead of quietly swallowing the model.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                       # noqa: E402

HIGHLIGHT = np.array([1.0, 0.25, 0.15])
DIMMED = np.array([0.80, 0.80, 0.83])


def neighbours_of(pairs, count):
    order = np.argsort(pairs[:, 0], kind="stable")
    return order


def grow(seed, pairs, values, mode, tolerance, limit, angles=None, centres=None,
         radius=None):
    """Flood from `seed` across the face graph while the strategy allows it."""
    count = int(pairs.max()) + 1 if len(pairs) else 0
    adjacency = [[] for _ in range(count)]
    for left, right in pairs:
        adjacency[left].append(right)
        adjacency[right].append(left)

    within = None
    if radius is not None and centres is not None:
        within = np.linalg.norm(centres - centres[seed], axis=1) <= radius

    reference = float(values[seed]) if values is not None else 0.0
    if mode in ("rough", "cavity", "relief"):
        floor = reference * (1.0 - tolerance)
        allowed = lambda face: values[face] >= floor                 # noqa: E731
    elif mode == "thin":
        ceiling = reference * (1.0 + tolerance)
        allowed = lambda face: 0 <= values[face] <= ceiling          # noqa: E731
    elif mode == "smooth":
        ceiling = max(reference, 1e-6) * (1.0 + tolerance)
        allowed = lambda face: values[face] <= ceiling               # noqa: E731
    elif mode == "patch":
        allowed = lambda face: True                                  # noqa: E731
    else:
        raise ValueError("unknown growth mode %r" % mode)

    crease = None
    if mode == "patch":
        if angles is None:
            raise ValueError("patch growth needs dihedral angles")
        crease = {}
        for index, (left, right) in enumerate(pairs):
            crease[(int(left), int(right))] = float(angles[index])
            crease[(int(right), int(left))] = float(angles[index])

    region = {int(seed)}
    queue = [int(seed)]
    while queue:
        face = queue.pop()
        for neighbour in adjacency[face]:
            neighbour = int(neighbour)
            if neighbour in region:
                continue
            if within is not None and not within[neighbour]:
                continue
            if crease is not None:
                if abs(crease.get((face, neighbour), 0.0)) > tolerance:
                    continue
            elif not allowed(neighbour):
                continue
            region.add(neighbour)
            if len(region) > limit:
                return None
            queue.append(neighbour)
    return np.array(sorted(region), dtype=np.int64)


def _compact_pieces(indices, pairs, centres, max_span):
    """Keep only the connected pieces whose longest dimension fits in `max_span`.

    Relief cannot tell a stud from a ridge: both stand proud. Extent can. A model
    is full of long proud things -- ribs, seams, mouldings -- and they are almost
    never what someone means when they point at a cluster of small ones.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    member = np.zeros(int(pairs.max()) + 1, dtype=bool)
    member[indices] = True
    both = member[pairs[:, 0]] & member[pairs[:, 1]]
    if not both.any():
        return indices
    size = len(member)
    graph = coo_matrix((np.ones(int(both.sum())), (pairs[both, 0], pairs[both, 1])),
                       shape=(size, size))
    _, labels = connected_components(graph, directed=False)

    keep = []
    for cluster in np.unique(labels[indices]):
        piece = indices[labels[indices] == cluster]
        span = np.ptp(centres[piece], axis=0).max() if len(piece) else 0.0
        if span <= max_span:
            keep.extend(int(f) for f in piece)
    return np.array(sorted(keep), dtype=np.int64)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, help="directory from inspect_model.py")
    parser.add_argument("--at", required=True, action="append",
                        help="view:x,y -- repeatable, all seeds join one part")
    parser.add_argument("--grow", default="patch",
                        choices=["rough", "relief", "thin", "cavity", "smooth", "patch"])
    parser.add_argument("--radius-mm", type=float, default=None,
                        help="bound the selection to this distance from the seed")
    parser.add_argument("--max-span-mm", type=float, default=None,
                        help="drop selected pieces longer than this. Separates "
                             "compact items (studs, cones, domes) from long ones "
                             "(ribs, ridges, seams) that score the same on relief")
    parser.add_argument("--connect", default="flood", choices=["flood", "radius"],
                        help="flood: one connected piece. radius: every qualifying "
                             "face within --radius-mm, for a clump of separate items")
    parser.add_argument("--tolerance", type=float, default=None,
                        help="band width; for 'patch' it is the crease angle in radians")
    parser.add_argument("--name", required=True, help="what this part is")
    parser.add_argument("--max-share", type=float, default=0.25,
                        help="fail if the selection exceeds this share of the model")
    parser.add_argument("--replace", action="store_true",
                        help="overwrite an existing part with the same name")
    args = parser.parse_args()

    session_path = os.path.join(args.session, "session.npz")
    if not os.path.exists(session_path):
        parser.error("no session.npz in %s; run inspect_model.py first" % args.session)
    session = np.load(session_path)

    if args.grow == "relief":
        # Cached beside the session the first time it is asked for: two seconds on
        # 600k faces, and every later selection reuses it.
        cache = os.path.join(args.session, "relief.npy")
        if os.path.exists(cache):
            relief_values = np.load(cache)
        else:
            from paintlib.signals import relief as compute_relief
            relief_values = compute_relief(session["vertices"], session["faces"])
            try:
                np.save(cache, relief_values)
            except OSError:
                pass
    else:
        relief_values = None

    values = {"rough": session["roughness"], "thin": session["thickness"],
              "cavity": session["occlusion"], "smooth": session["roughness"],
              "relief": relief_values, "patch": None}[args.grow]
    tolerance = args.tolerance
    if tolerance is None:
        tolerance = {"rough": 0.45, "thin": 0.9, "cavity": 0.35,
                     "smooth": 0.6, "relief": 0.6, "patch": 0.6}[args.grow]

    faces = session["faces"]
    limit = int(len(faces) * args.max_share)
    pairs = session["pairs"]

    selected = set()
    seeds = []
    for spec in args.at:
        try:
            view, coords = spec.split(":", 1)
            x, y = (int(part) for part in coords.split(","))
        except ValueError:
            parser.error("--at wants view:x,y, got %r" % spec)
        key = "pick_%s" % view
        if key not in session:
            parser.error("session has no view %r (has %s)" % (
                view, ", ".join(k[5:] for k in session.files if k.startswith("pick_"))))
        seed = raster.region_at(None, session[key], x, y)
        if seed is None:
            parser.error("nothing under %s -- that pixel is background" % spec)
        seeds.append((spec, seed))
        centres = None
        if args.connect == "radius":
            if args.radius_mm is None:
                parser.error("--connect radius needs --radius-mm")
            verts, faces_ = session["vertices"], session["faces"]
            centres = verts[faces_].mean(axis=1)
            near = np.linalg.norm(centres - centres[seed], axis=1) <= args.radius_mm
            if values is None:
                grown = np.where(near)[0]
            else:
                reference = float(values[seed])
                finite = np.isfinite(values)
                if args.grow in ("rough", "cavity", "relief"):
                    ok = finite & (values >= reference * (1.0 - tolerance))
                elif args.grow == "thin":
                    ok = finite & (values >= 0) & (values <= reference * (1.0 + tolerance))
                else:
                    ok = finite & (values <= max(reference, 1e-6) * (1.0 + tolerance))
                grown = np.where(near & ok)[0]
            if args.max_span_mm is not None and len(grown):
                grown = _compact_pieces(grown, pairs, centres, args.max_span_mm)
                if not len(grown):
                    sys.stderr.write(
                        "select: nothing within --max-span-mm %.1f at %s\n"
                        % (args.max_span_mm, spec))
                    return 2
            if len(grown) > limit:
                sys.stderr.write(
                    "select: %s selected %.0f%% of the model; reduce --radius-mm\n"
                    % (spec, 100.0 * len(grown) / len(faces)))
                return 2
            selected.update(int(f) for f in grown)
            continue

        if args.radius_mm is not None:
            verts, faces_ = session["vertices"], session["faces"]
            centres = verts[faces_].mean(axis=1)
        grown = grow(seed, pairs, values, args.grow, tolerance, limit,
                     session["angles"] if args.grow == "patch" else None,
                     centres, args.radius_mm)
        if grown is None:
            sys.stderr.write(
                "select: growth from %s ran past %.0f%% of the model and was "
                "discarded. Tighten --tolerance, bound it with --radius-mm, or "
                "use a different --grow (relief is usually the answer when rough "
                "floods).\n"
                % (spec, 100 * args.max_share))
            return 2
        selected.update(int(f) for f in grown)

    indices = np.array(sorted(selected), dtype=np.int64)
    areas = session["areas"]
    share = float(areas[indices].sum() / areas.sum())

    parts_path = os.path.join(args.session, "parts.json")
    document = {"parts": []}
    if os.path.exists(parts_path):
        with open(parts_path) as handle:
            document = json.load(handle)
    document["parts"] = [part for part in document.get("parts", [])
                         if part["name"] != args.name or not args.replace]
    if any(part["name"] == args.name for part in document["parts"]):
        sys.stderr.write("select: a part named %r already exists; pass --replace\n"
                         % args.name)
        return 2

    document["parts"].append({
        "name": args.name,
        "grow": args.grow,
        "tolerance": tolerance,
        "seeds": [spec for spec, _ in seeds],
        "faces": len(indices),
        "area": round(share, 4),
        "face_indices": [int(v) for v in indices],
    })
    with open(parts_path, "w") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")

    # The verification render: the point of this tool is that a wrong selection is
    # visible immediately rather than surviving into a paint plan.
    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = np.tile(DIMMED, (len(faces), 1))
    colours[indices] = HIGHLIGHT
    checks = os.path.join(args.session, "selections")
    os.makedirs(checks, exist_ok=True)
    slug = "".join(ch if ch.isalnum() else "-" for ch in args.name).strip("-").lower()
    for view in dict.fromkeys(spec.split(":", 1)[0] for spec, _ in seeds):
        elevation, azimuth = raster.VIEWS[view]
        image, _ = raster.render_view(mesh, colours, elevation, azimuth, 900)
        raster.save_png(os.path.join(checks, "%s-%s.png" % (slug, view)), image)

    print("%s: %d triangles, %.2f%% of surface area" % (args.name, len(indices), 100 * share))
    print("check %s/%s-*.png" % (checks, slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
