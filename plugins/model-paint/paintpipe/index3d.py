"""Index every instance of a repeating feature, by looking and pointing.

Segmentation can propose regions, but it cannot tell a barnacle from the
crevice beside it -- that is a question about what the thing IS, and the only
honest way to answer it is to look. So the agent looks and POINTS: it returns
the pixel coordinate of each instance it can see, and the render's own buffers
turn that pixel into a face on the mesh. Vision answers where and which;
geometry answers how far the instance extends.

One look is never enough, and that is the point of rotating. The same field is
visited from many directions and at two scales -- the whole piece, then zoomed
quarters where small instances are legible -- and every hit is reduced to a 3D
POINT. A coordinate in space is invariant to the camera that found it, so an
instance seen from four angles is one instance, not four, and an instance
hidden in three views only has to be visible in the fourth.
"""

import os

import numpy as np


FIND_PROMPT = """This is a %dx%d rendered view of part of a 3D model.

The piece: %s

Find every %s. %s

For each one, give the pixel coordinate of a point ON it -- as close to its
centre as you can. x is measured from the left edge, y from the top edge. The
coordinate must land on the feature itself, not beside it. Include one only if
you can actually see it in THIS image; a partly hidden one counts if its
centre is visible. Do not guess at things off the edge of the frame.

Reply with ONLY a JSON object, no prose:
{"found": [{"n": 1, "x": <int>, "y": <int>}, ...]}
An empty list is a correct answer if this view shows none."""


def _look(backend, mesh, frame, camera, feature, hint, intent, pixels,
          out_dir, tag):
    """One view: render, ask for coordinates, backproject to faces."""
    from PIL import Image
    from . import entities as entities_module
    from . import render as render_module

    bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
    visible = bundle["visible"]
    if not visible.any():
        return []
    lit = np.clip(bundle["rgb_lit"], 0, 1)
    image = np.ones((pixels, pixels, 3))
    image[visible] = (0.32 + 0.60 * lit)[visible, None]
    path = os.path.join(out_dir, "look-%s.png" % tag)
    Image.fromarray((image * 255).astype(np.uint8)).save(path)

    prompt = FIND_PROMPT % (pixels, pixels, intent or "a model", feature,
                            hint or "")
    key = "find-%s" % entities_module.digest_of(
        open(path, "rb").read() + prompt.encode("utf-8"))[7:19]
    answer = backend._run([path], prompt, key)
    hits = []
    for entry in (answer or {}).get("found", []) or []:
        try:
            x, y = int(entry["x"]), int(entry["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= x < pixels and 0 <= y < pixels):
            continue
        face = int(bundle["hit_id"][y, x])
        if face < 0:
            continue
        hits.append((face, np.asarray(bundle["point"][y, x], dtype=float)))
    return hits


def survey(backend, mesh, frame, up, feature, hint, intent, out_dir,
           characteristic, views=6, pixels=900, zoom_tiles=2, workers=8,
           log=print):
    """Look from many directions at two scales; return deduped seed faces.

    Instances are merged by 3D PROXIMITY relative to their own feature size,
    so the same one found from six cameras stays one.
    """
    from concurrent.futures import ThreadPoolExecutor
    from . import preview, render as render_module

    os.makedirs(out_dir, exist_ok=True)
    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2 * 1.05
    directions = list(preview.orbit(views, 18.0, up=up)) \
        + list(preview.orbit(max(2, views // 2), 55.0, start_deg=30.0, up=up))

    # Build every camera first -- wide plus zoomed quarters per direction --
    # then look through all of them at once. The asks are independent.
    jobs = []
    for index, direction in enumerate(directions):
        camera = render_module.Camera(np.asarray(direction, float), up,
                                      centre, radius, pixels)
        # The wide view only AIMS: a coordinate returned from it is worth a
        # few millimetres on the model, which is wider than the feature.
        # Indexing happens in the zoom, where a barnacle is a hundred pixels.
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        points, seen = bundle["point"], bundle["visible"]
        for row in range(zoom_tiles):
            for col in range(zoom_tiles):
                ys = slice(row * pixels // zoom_tiles,
                           (row + 1) * pixels // zoom_tiles)
                xs = slice(col * pixels // zoom_tiles,
                           (col + 1) * pixels // zoom_tiles)
                block, mask = points[ys, xs], seen[ys, xs]
                if mask.sum() < 400:
                    continue
                target = np.median(block[mask], axis=0)
                jobs.append((render_module.Camera(
                    np.asarray(direction, float), up, target,
                    radius / 2.3, pixels), "z%d-%d%d" % (index, row, col)))
    log("  %d zoomed views over %d directions" % (len(jobs), len(directions)))
    seeds = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for hits in pool.map(lambda job: _look(backend, mesh, frame, job[0],
                                               feature, hint, intent, pixels,
                                               out_dir, job[1]), jobs):
            seeds.extend(hits)

    # The feature's own scale is whatever the CONSENSUS of hits measures --
    # learned from what vision found, not assumed. A hit that lands on
    # something far coarser than that consensus is a misplaced click on the
    # host body, and growing from it would swallow the host.
    if not seeds:
        return np.array([], dtype=np.int64), np.array([]), 0.0
    # One scale for the whole family, taken as the 70th percentile of what the
    # hits measure: the median is dragged down by hits that land in the gaps
    # between instances, and a family of one kind of thing IS one size.
    scales = np.array([float(characteristic[f]) for f, _p in seeds])
    family = float(np.percentile(scales, 70.0))
    log("  family scale %.2fmm from %d hits" % (family, len(seeds)))
    kept_face, kept_point = [], []
    for face, point in seeds:
        if any(np.linalg.norm(point - other) < family * 0.9
               for other in kept_point):
            continue
        kept_face.append(face)
        kept_point.append(point)
    log("  %d hits over %d views -> %d distinct instances"
        % (len(seeds), len(directions), len(kept_face)))
    return (np.array(kept_face, dtype=np.int64), np.array(kept_point), family)


def grow(mesh, seeds, characteristic, family, base=None, reach_scale=1.35,
         foot_deg=32.0):
    """Each seed becomes a unit, out to the crease at the feature's foot."""
    from collections import deque

    areas = np.asarray(mesh.area_faces, dtype=float)
    tri = mesh.triangles.mean(axis=1)
    adjacency = mesh.face_adjacency
    angles = np.degrees(np.asarray(mesh.face_adjacency_angles))
    convex = np.asarray(mesh.face_adjacency_convex)
    nbr = [[] for _ in range(len(areas))]
    for (a, b), is_convex, angle in zip(adjacency, convex, angles):
        nbr[a].append((b, is_convex, angle))
        nbr[b].append((a, is_convex, angle))

    unit = np.full(len(areas), -1, dtype=np.int64)
    made = 0
    for seed in seeds:
        if unit[seed] >= 0:
            continue
        # Every instance of one kind grows to the same reach -- uniformity
        # by construction, not by a repair afterwards.
        scale = family
        reach = max(scale * reach_scale, 0.8)
        origin = tri[seed]
        seen, queue, found = {int(seed)}, deque([int(seed)]), []
        while queue:
            face = queue.popleft()
            found.append(face)
            for other, is_convex, angle in nbr[face]:
                if other in seen or unit[other] >= 0:
                    continue
                if np.linalg.norm(tri[other] - origin) > reach:
                    continue
                # Never leave the feature's own scale. A face on the host
                # body measures far coarser than a face on the feature, so
                # this is what stops a unit bleeding out over the surface
                # it sits on when no crease happens to be in the way.
                if characteristic[other] > scale * 2.0:
                    continue
                # Leave the feature's own recess freely; beyond it, a concave
                # crease is the foot where the feature meets what it sits on.
                if (not is_convex) and angle > foot_deg \
                        and np.linalg.norm(tri[face] - origin) > scale * 0.55:
                    continue
                seen.add(other)
                queue.append(other)
        found = np.array([f for f in found if unit[f] < 0], dtype=np.int64)
        if len(found) < 8:
            continue
        unit[found] = made
        made += 1
    # A ball of reach spills wherever no crease falls. Trim every unit to the
    # mesh's OWN regions: a base region joins the unit only if the unit holds
    # most of it, so a unit ends where the geometry says a region ends. This
    # is the same law the label field obeys -- boundaries are region edges.
    if base is not None and made:
        base = np.asarray(base, dtype=np.int64)
        regions = int(base.max()) + 1
        for number in range(made):
            inside = unit == number
            if not inside.any():
                continue
            held = np.bincount(base[inside], weights=areas[inside],
                               minlength=regions)
            total = np.bincount(base, weights=areas, minlength=regions)
            share = held / np.maximum(total, 1e-9)
            unit[inside] = -1
            take = np.isin(base, np.flatnonzero(share >= 0.5)) & \
                (unit < 0)
            unit[take] = number

    # A unit far larger than its peers grew somewhere it should not have.
    if made:
        sizes = np.bincount(unit[unit >= 0], weights=areas[unit >= 0],
                            minlength=made)
        typical = float(np.median(sizes[sizes > 0]))
        for number in np.flatnonzero(sizes > 4.0 * typical):
            unit[unit == number] = -1
        order = -np.ones(made, dtype=np.int64)
        alive = [n for n in range(made) if (unit == n).any()]
        for new, old in enumerate(alive):
            order[old] = new
        keep = unit >= 0
        unit[keep] = order[unit[keep]]
        made = len(alive)
    return unit, made
