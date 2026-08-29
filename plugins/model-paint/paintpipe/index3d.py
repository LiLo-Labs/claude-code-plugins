"""Index repeating features by consensus over a GLOBAL index of tree nodes.

The merge tree gives every point on the surface a stable id at any chosen
scale: face -> base region -> the ancestor node whose area matches the family.
That id is the same id from every camera, so it is an index the whole survey
can vote into. Vision points at instances in a picture; the pixel becomes a
face; the face becomes a node; the node collects votes.

Consensus is the point of moving the camera. Azimuth, elevation, roll and
zoom are all varied, so two views of one instance are genuinely different
looks and not the same look twice. A node seen in several views and pointed
at in several is an instance. A node pointed at once and never again was a
misplaced click. And because a node's visibility is known exactly -- it is in
the depth buffer or it is not -- votes are scored against the views that could
actually have seen it, so an instance hidden in five views is not punished for
the five, only judged on the ones where it showed.

Nothing is flood filled. A unit's boundary is its node's boundary, which is
the geometry's own.
"""

import os

import numpy as np


FIND_PROMPT = """This is a %dx%d rendered view of a 3D model.

The piece: %s

Find every %s. %s

For each one, give the pixel coordinate of a point ON it, as close to its
centre as you can. x is measured from the left edge, y from the top edge. The
coordinate must land on the feature itself. Only include one if you can see it
in THIS image.

Reply with ONLY a JSON object, no prose:
{"found": [{"n": 1, "x": <int>, "y": <int>}, ...]}
An empty list is a correct answer if this view shows none."""


def cameras(mesh, up, pixels, views=6, zoom_tiles=3):
    """Genuinely different looks: azimuth, elevation, roll and zoom all move.

    Two cameras that differ only in azimuth see the same foreshortening and
    the same self-occlusion pattern, so agreeing with each other means less
    than it appears. Rolling the camera and changing the elevation makes each
    look an independent test of the same claim.
    """
    from . import preview, render as render_module

    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2 * 1.05
    axis = np.asarray(up, dtype=float)
    axis = axis / max(np.linalg.norm(axis), 1e-12)

    out = []
    for elevation, start, roll in ((14.0, 0.0, 0.0), (38.0, 27.0, 22.0),
                                   (-24.0, 53.0, -18.0)):
        for direction in preview.orbit(views, elevation, start_deg=start,
                                       up=axis):
            spun = axis
            if abs(roll) > 1e-6:
                angle = np.radians(roll)
                side = np.cross(axis, np.asarray(direction, float))
                norm = np.linalg.norm(side)
                if norm > 1e-9:
                    side = side / norm
                    spun = axis * np.cos(angle) + side * np.sin(angle)
            out.append((render_module.Camera(np.asarray(direction, float),
                                             spun, centre, radius, pixels),
                        np.asarray(direction, float), spun))
    return out, centre, radius


def node_index(mesh, tree, family):
    """The global index: every face -> the tree node that is its instance.

    One array, computed once, shared by every camera. Two views pointing at
    one instance return the same id without any matching step.
    """
    base = np.asarray(tree["base"], dtype=np.int64)
    children = tree["children"]
    node_area = np.asarray(tree["area"], dtype=float)
    parents = {}
    for node in range(len(children)):
        left, right = children[node]
        if left >= 0:
            parents[int(left)] = node
        if right >= 0:
            parents[int(right)] = node

    target = float(np.pi * family * family)
    region_node = np.full(int(base.max()) + 1, -1, dtype=np.int64)
    for region in range(len(region_node)):
        node, best, score = region, None, None
        while node is not None:
            area = float(node_area[node])
            if area > 4.0 * target:
                break
            here = abs(np.log(max(area, 1e-6) / target))
            if score is None or here < score:
                best, score = node, here
            node = parents.get(node)
        region_node[region] = best if best is not None else region
    return region_node[base], region_node


def survey(backend, mesh, frame, up, feature, hint, intent, out_dir, tree,
           characteristic, views=6, pixels=900, zoom_tiles=3, workers=8,
           min_votes=2, min_share=0.34, log=print):
    """Look from many different cameras; let tree nodes collect the votes."""
    import io
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image
    from . import entities as entities_module
    from . import render as render_module

    os.makedirs(out_dir, exist_ok=True)
    wide, centre, radius = cameras(mesh, up, pixels, views, zoom_tiles)

    # Wide views only AIM: their coordinates are worth millimetres on the
    # model, which is wider than the feature. Every ask happens in a zoom.
    jobs = []
    for index, (camera, direction, spun) in enumerate(wide):
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
                jobs.append((render_module.Camera(direction, spun, target,
                                                  radius / 2.6, pixels),
                             "%d-%d%d" % (index, row, col)))
    log("  %d looks over %d cameras (azimuth, elevation, roll, zoom)"
        % (len(jobs), len(wide)))

    def look(job):
        camera, tag = job
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        visible = bundle["visible"]
        if not visible.any():
            return None
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
            if 0 <= x < pixels and 0 <= y < pixels:
                face = int(bundle["hit_id"][y, x])
                if face >= 0:
                    hits.append(face)
        return hits, np.unique(bundle["hit_id"][visible])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = [r for r in pool.map(look, jobs) if r is not None]

    # The family's scale, from what the hits themselves measure. The 70th
    # percentile rather than the median: hits that land in the gaps between
    # instances measure small and drag a median down.
    every = [face for hits, _seen in results for face in hits]
    if not every:
        return np.full(len(mesh.faces), -1, dtype=np.int64), 0, 0.0
    family = float(np.percentile(characteristic[np.array(every)], 70.0))
    face_node, _region_node = node_index(mesh, tree, family)
    log("  family scale %.2fmm; %d hits over %d looks"
        % (family, len(every), len(results)))

    total = int(face_node.max()) + 1
    votes = np.zeros(total, dtype=np.int64)
    shown = np.zeros(total, dtype=np.int64)
    for hits, visible_faces in results:
        pointed = np.unique(face_node[np.array(hits, dtype=np.int64)]) \
            if hits else np.array([], dtype=np.int64)
        votes[pointed] += 1
        here = np.unique(face_node[visible_faces[visible_faces >= 0]])
        shown[here] += 1

    share = votes / np.maximum(shown, 1)
    winners = np.flatnonzero((votes >= min_votes) & (share >= min_share))
    log("  %d nodes pointed at; %d pass consensus (>=%d votes, >=%.0f%% of "
        "views that could see them)"
        % (int((votes > 0).sum()), len(winners), min_votes, 100 * min_share))

    unit = np.full(len(mesh.faces), -1, dtype=np.int64)
    for number, node in enumerate(winners):
        unit[face_node == node] = number
    return unit, len(winners), family
