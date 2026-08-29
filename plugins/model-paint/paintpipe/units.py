"""Repeating units, segmented by AGREEMENT rather than by a chosen threshold.

A model covered in repeating things -- barnacles on a shell, colonies on a
reef panel, rivets on a hull -- needs those things as units before anything
can name or paint them. Geometry can propose them, but only at some setting:
how enclosed a pocket must be to count, how far a unit's collar reaches, what
crease ends it. Picking those numbers by hand is how a pipeline becomes a pile
of magic constants tuned to one model.

So propose SEVERAL segmentations and let the agent choose. Each candidate is
rendered with its units in distinct colours, zoomed where the repeats are
densest, and the reviewer picks the panel where each unit is whole, none
merged and none split. A second angle must agree before the choice stands --
the same two-view rule every other decision in this pipeline obeys. The
constants below are the SPREAD of the search, not an answer.
"""

import numpy as np

# `fine` is the percentile of feature scale below which a pocket counts as
# one of the model's REPEATING units rather than a crevice in its body: a
# barnacle sits at a small characteristic radius, the gap between two ribs
# at a large one, and without that filter a rib crevice swallows the rib.
GRID = [
    {"pocket": 12.0, "fine": 25.0, "collar": 1.0, "crease": 26.0},
    {"pocket": 12.0, "fine": 40.0, "collar": 1.0, "crease": 26.0},
    {"pocket": 20.0, "fine": 25.0, "collar": 1.0, "crease": 26.0},
    {"pocket": 20.0, "fine": 25.0, "collar": 1.5, "crease": 26.0},
    {"pocket": 20.0, "fine": 40.0, "collar": 1.5, "crease": 30.0},
    {"pocket": 30.0, "fine": 25.0, "collar": 1.2, "crease": 26.0},
]


def _neighbours(count, adjacency, angles, convex, crease):
    nbr = [[] for _ in range(count)]
    blocked = (~convex) & (angles > crease)
    for (a, b), stop in zip(adjacency, blocked):
        nbr[a].append((b, stop))
        nbr[b].append((a, stop))
    return nbr


def detect_units(mesh, occlusion, characteristic, pocket, collar, crease,
                 fine=25.0, nbr=None, tri=None):
    """Hollow-topped bumps: an enclosed pocket, then its collar out to a crease.

    Generic on purpose -- it knows nothing about barnacles. Anything with a
    recess and a raised rim (a tube coral, a rivet head, a socket) answers to
    the same description.
    """
    import scipy.sparse as sparse
    from collections import deque

    areas = np.asarray(mesh.area_faces, dtype=float)
    adjacency = mesh.face_adjacency
    if tri is None:
        tri = mesh.triangles.mean(axis=1)
    if nbr is None:
        angles = np.degrees(np.asarray(mesh.face_adjacency_angles))
        convex = np.asarray(mesh.face_adjacency_convex)
        nbr = _neighbours(len(areas), adjacency, angles, convex, crease)

    scale = float(np.median(characteristic)) * 1.6
    hollow = (occlusion < np.percentile(occlusion, pocket)) \
        & (characteristic < scale)
    seats = np.flatnonzero(hollow)
    if len(seats) < 10:
        return np.full(len(areas), -1, dtype=np.int64), 0
    lookup = np.full(len(areas), -1, dtype=np.int64)
    lookup[seats] = np.arange(len(seats))
    inner = hollow[adjacency[:, 0]] & hollow[adjacency[:, 1]]
    edges = adjacency[inner]
    graph = sparse.coo_matrix(
        (np.ones(len(edges)), (lookup[edges[:, 0]], lookup[edges[:, 1]])),
        shape=(len(seats), len(seats)))
    pockets, which = sparse.csgraph.connected_components(graph, directed=False)
    pocket_area = np.bincount(which, weights=areas[seats], minlength=pockets)
    typical = float(np.median(pocket_area[pocket_area > 0]))
    real = np.flatnonzero((pocket_area > 0.25 * typical)
                          & (pocket_area < 12.0 * typical))
    ceiling = float(np.percentile(characteristic, fine))
    real = np.array([i for i in real
                     if float(np.median(characteristic[seats[which == i]]))
                     <= ceiling], dtype=np.int64)

    unit = np.full(len(areas), -1, dtype=np.int64)
    made = 0
    for index in real:
        seed = seats[which == index]
        if unit[seed].max() >= 0:
            continue
        centre = tri[seed].mean(axis=0)
        # The unit's reach comes from the FEATURE scale the index measured at
        # this pocket -- the size of the thing the hole sits in -- not from
        # the hole's own radius, which only says how big the hole is.
        reach = max(float(np.median(characteristic[seed])) * collar, 0.6)
        # The flood must be able to climb out of its own pocket: the join
        # from a cavity floor to its wall is itself concave, so a crease stop
        # applied from the first step traps every unit inside its hole.
        found, seen = [], set(int(f) for f in seed)
        queue = deque(seen)
        escaped = set(seen)
        while queue:
            face = queue.popleft()
            found.append(face)
            if np.linalg.norm(tri[face] - centre) > reach:
                continue
            inside_pocket = face in escaped
            for other, stop in nbr[face]:
                if (stop and not inside_pocket) or other in seen \
                        or unit[other] >= 0:
                    continue
                if np.linalg.norm(tri[other] - centre) > reach:
                    continue
                seen.add(other)
                queue.append(other)
        found = np.array(found, dtype=np.int64)
        found = found[unit[found] < 0]
        if len(found) < 12:
            continue
        unit[found] = made
        made += 1
    return unit, made


def densest_repeat(mesh, unit, tri=None):
    """Where the repeats crowd together -- the honest place to judge them."""
    from scipy.cluster.vq import kmeans2
    if tri is None:
        tri = mesh.triangles.mean(axis=1)
    seen = np.flatnonzero(unit >= 0)
    if len(seen) < 50:
        return mesh.vertices.mean(axis=0), np.array([0.0, -1.0, -0.3])
    centres, which = kmeans2(tri[seen], 6, seed=1, minit="++", iter=40)
    crowd = int(np.argmax(np.bincount(which, minlength=6)))
    normal = mesh.face_normals[seen[which == crowd]].mean(axis=0)
    norm = np.linalg.norm(normal)
    return centres[crowd], (-normal / norm if norm > 1e-9
                            else np.array([0.0, -1.0, -0.3]))


CHOOSE_PROMPT = """Each numbered panel shows the SAME close-up of one piece, \
segmented a different way. Colour marks the separate units the segmentation \
found; pale grey is whatever it left unsegmented.

The piece: %s

The piece carries many repeating units of one kind. Pick the panel where those \
units are segmented CORRECTLY: each whole unit is one colour, neighbouring \
units are different colours, no unit is split into pieces, no colour spills \
onto the surface between or around them, and none are missed.

Reply with ONLY a JSON object, no prose: {"choice": <number>, "why": str} \
or {"choice": -1} if none segment the units correctly."""

NAME_PROMPT = """The coloured units in this close-up were all segmented as the \
same kind of repeating feature on this piece.

The piece: %s

What are they? Name the feature a maker would recognise, singular.

Reply with ONLY a JSON object, no prose: {"unit": str, "material": str}"""


def choose_segmentation(backend, mesh, frame, up, occlusion, characteristic,
                        intent, out_dir, pixels=430, log=print):
    """Render the candidates, let the reviewer pick, confirm from a 2nd angle."""
    import os
    import colorsys
    from PIL import Image, ImageDraw
    from . import entities as entities_module
    from . import preview

    tri = mesh.triangles.mean(axis=1)
    angles = np.degrees(np.asarray(mesh.face_adjacency_angles))
    convex = np.asarray(mesh.face_adjacency_convex)
    adjacency = mesh.face_adjacency

    made = []
    for setting in GRID:
        nbr = _neighbours(len(mesh.faces), adjacency, angles, convex,
                          setting["crease"])
        unit, count = detect_units(mesh, occlusion, characteristic,
                                   setting["pocket"], setting["collar"],
                                   setting["crease"], fine=setting["fine"],
                                   nbr=nbr, tri=tri)
        made.append((setting, unit, count))
        log("  candidate pocket %.0f%% fine %.0f%% collar %.1f -> %d units"
            % (setting["pocket"], setting["fine"], setting["collar"], count))
    usable = [m for m in made if m[2] >= 8]
    if not usable:
        return None, None, "no candidate found repeating units"

    centre, facing = densest_repeat(mesh, usable[0][1], tri=tri)
    rng = np.random.default_rng(21)

    def sheet(direction, tag):
        tiles = []
        for number, (_setting, unit, count) in enumerate(usable):
            table = np.array([colorsys.hsv_to_rgb(h, 0.95, 0.95)
                              for h in rng.uniform(0, 1, max(count, 1))])
            rgb = np.tile(np.array([[0.87, 0.87, 0.85]]), (len(unit), 1))
            shown = unit >= 0
            rgb[shown] = table[unit[shown]]
            image = preview.render_asset(mesh, rgb, direction, size=pixels,
                                         occlusion=occlusion, up=up,
                                         centre=centre, zoom=3.4)
            picture = Image.fromarray(image)
            draw = ImageDraw.Draw(picture)
            draw.rectangle([4, 4, 30, 24], fill=(255, 255, 255))
            draw.text((10, 8), str(number), fill=(0, 0, 0))
            tiles.append(picture)
        columns = 3
        rows = (len(tiles) + columns - 1) // columns
        board = Image.new("RGB", (columns * pixels, rows * pixels),
                          (255, 255, 255))
        for i, picture in enumerate(tiles):
            board.paste(picture, ((i % columns) * pixels,
                                  (i // columns) * pixels))
        path = os.path.join(out_dir, "unit-choice-%s.png" % tag)
        board.save(path)
        return path

    axis = np.asarray(up, dtype=float)
    axis = axis / max(np.linalg.norm(axis), 1e-12)
    other = np.cross(axis, facing)
    other = other / max(np.linalg.norm(other), 1e-12) * 0.6 + facing * 0.8
    picks = []
    for tag, direction in (("a", facing), ("b", other)):
        path = sheet(direction, tag)
        key = "unitpick-%s-%s" % (
            tag, entities_module.digest_of(open(path, "rb").read())[7:17])
        answer = backend._run([path], CHOOSE_PROMPT % (intent or "a model"),
                              key)
        try:
            picks.append(int((answer or {}).get("choice", -1)))
        except (TypeError, ValueError):
            picks.append(-1)
    log("  picks from two angles: %s" % picks)
    if picks[0] < 0 or picks[0] != picks[1]:
        return None, None, "views disagreed %s -- nothing adopted" % picks
    setting, unit, count = usable[picks[0]]
    return unit, setting, "%d units agreed from two angles" % count
