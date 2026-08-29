"""Index every instance of a repeating feature, by looking and pointing.

Segmentation can propose regions, but it cannot tell a barnacle from the
crevice beside it -- that is a question about what the thing IS, and the only
honest way to answer it is to look. So the agent looks and POINTS: it returns
the pixel coordinate of each instance it can see, and the render's own buffers
turn that pixel into a face on the mesh. Vision answers where and which;
geometry answers how far the instance extends.

No region is painted until it has been SEEN and confirmed as one instance:
the tree extracts exact parts, and a look decides which of them are the thing.

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


def units_from_tree(mesh, tree, seeds, family, log=print):
    """Each seed resolves to the merge-tree node that IS its instance.

    A flood needs a reach and a stopping rule, and both are guesses that
    over- or under-paint. The tree already holds the answer: walking up from
    the seed's own base region, each ancestor is a larger real piece of the
    surface, and the one whose area matches the family's scale is the
    instance. Its boundary is the geometry's boundary -- nothing spills,
    nothing is cut short -- and two seeds on one instance land on one node,
    so duplicates collapse for free.
    """
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts = os.path.join(here, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import index_persist

    children = tree["children"]
    base = np.asarray(tree["base"], dtype=np.int64)
    regions = int(tree["regions"])
    node_area = np.asarray(tree["area"], dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    parents = {}
    for node in range(len(children)):
        left, right = children[node]
        if left >= 0:
            parents[int(left)] = node
        if right >= 0:
            parents[int(right)] = node

    from collections import defaultdict
    region_faces = defaultdict(list)
    for face, region in enumerate(base):
        region_faces[int(region)].append(face)

    target = float(np.pi * family * family)
    chosen = {}
    for seed in seeds:
        node = int(base[int(seed)])
        best, best_score = None, None
        while node is not None:
            area = float(node_area[node])
            if area <= 4.0 * target:
                score = abs(np.log(max(area, 1e-6) / target))
                if best_score is None or score < best_score:
                    best, best_score = node, score
            else:
                break
            node = parents.get(node)
        if best is not None:
            chosen.setdefault(best, 0)
            chosen[best] += 1
    log("  %d seeds -> %d distinct tree nodes (target %.1f mm2)"
        % (len(seeds), len(chosen), target))

    unit = np.full(len(areas), -1, dtype=np.int64)
    made = 0
    for node in chosen:
        leaves = []
        index_persist.leaves_of(children, int(node), regions, leaves)
        faces = []
        for leaf in leaves:
            faces.extend(region_faces[int(leaf)])
        faces = np.array([f for f in faces if unit[f] < 0], dtype=np.int64)
        if len(faces) < 8:
            continue
        unit[faces] = made
        made += 1
    return unit, made


CONFIRM_PROMPT = """Each numbered panel shows the same 3D piece with ONE \
candidate region highlighted in red, seen close up.

The piece: %s

Which numbered panels show exactly ONE complete %s and nothing else? \
Reject a panel if the red covers bare surface around the feature, if it \
covers several of them at once, if it covers only part of one, or if it is \
not that feature at all.

Reply with ONLY a JSON object, no prose: {"yes": [<numbers>]}
An empty list is a correct answer."""


def confirm_units(backend, mesh, frame, up, unit, count, feature, intent,
                  out_dir, occlusion=None, per_sheet=12, pixels=300,
                  workers=8, log=print):
    """Show every extracted part; keep only the ones confirmed as the feature."""
    import io
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image, ImageDraw
    from . import entities as entities_module
    from . import preview, render as render_module

    tri = mesh.triangles.mean(axis=1)
    extent = float(np.linalg.norm(np.ptp(mesh.vertices, axis=0)))

    def tile(number):
        faces = np.flatnonzero(unit == number)
        if len(faces) < 6:
            return None
        centre = tri[faces].mean(axis=0)
        span = float(np.linalg.norm(np.ptp(tri[faces], axis=0)))
        normal = mesh.face_normals[faces].mean(axis=0)
        norm = np.linalg.norm(normal)
        direction = -normal / norm if norm > 1e-9 else np.array([0., -1., -.3])
        camera = render_module.Camera(direction, up, centre,
                                      max(span * 2.0, 0.03 * extent), pixels)
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        visible, hit = bundle["visible"], bundle["hit_id"]
        mask = np.zeros(len(mesh.faces), dtype=bool)
        mask[faces] = True
        red = visible & mask[np.clip(hit, 0, len(mask) - 1)]
        if int(red.sum()) < 40:
            return None
        lit = np.clip(bundle["rgb_lit"], 0, 1)
        image = np.ones((pixels, pixels, 3))
        image[visible] = (0.35 + 0.55 * lit)[visible, None]
        image[red] = np.stack([0.40 + 0.55 * lit[red], 0.12 * lit[red],
                               0.08 * lit[red]], axis=1)
        return (image * 255).astype(np.uint8)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        drawn = list(pool.map(tile, range(count)))
    ready = [(n, art) for n, art in enumerate(drawn) if art is not None]
    log("  %d of %d parts renderable for confirmation" % (len(ready), count))

    keep = set()
    for start in range(0, len(ready), per_sheet):
        chunk = ready[start:start + per_sheet]
        tiles, numbers = [], []
        for offset, (number, art) in enumerate(chunk):
            picture = Image.fromarray(art)
            draw = ImageDraw.Draw(picture)
            draw.rectangle([3, 3, 27, 21], fill=(255, 255, 255))
            draw.text((8, 6), str(offset), fill=(0, 0, 0))
            tiles.append(picture)
            numbers.append(number)
        columns = 4
        rows = (len(tiles) + columns - 1) // columns
        board = Image.new("RGB", (columns * pixels, rows * pixels),
                          (255, 255, 255))
        for i, picture in enumerate(tiles):
            board.paste(picture, ((i % columns) * pixels,
                                  (i // columns) * pixels))
        buffer = io.BytesIO()
        board.save(buffer, format="PNG")
        prompt = CONFIRM_PROMPT % (intent or "a model", feature)
        key = "confirm-%s" % entities_module.digest_of(
            buffer.getvalue() + prompt.encode("utf-8"))[7:19]
        path = os.path.join(out_dir, "%s.png" % key)
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(buffer.getvalue())
        answer = backend._run([path], prompt, key)
        for value in (answer or {}).get("yes", []) or []:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(numbers):
                keep.add(numbers[index])
    log("  confirmed %d of %d parts as %s" % (len(keep), len(ready), feature))
    out = np.full(len(unit), -1, dtype=np.int64)
    for new, number in enumerate(sorted(keep)):
        out[unit == number] = new
    return out, len(keep)
