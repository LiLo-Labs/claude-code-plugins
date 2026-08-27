"""Patch assignment: the agent SELECTS surface patches instead of pointing at pixels.

Every propagation mechanism tried before this failed the same way, and the last one
failed after its structural defect was fixed -- the race with no length constant still
shattered compact parts. That established the real limiter: a cue-derived barrier cannot
tell a semantic boundary from a decorative crease, and neck-to-body leaves no trace in
any cue map at all. If the boundary is not in the image, no rule can find it there.

So the boundary question goes to the agent, as a DISCRETE choice:

    1. Over-segment the surface once into patches -- exact face sets, grown as a
       geodesic Voronoi diagram over the face graph with crease-weighted edges. Patches
       are deliberately smaller than any part, so a part boundary can always be traced
       by patch boundaries; the agent never has to split a patch, only group them.
    2. Render each view twice: shaded, and the same view with patch ids drawn on it.
    3. Ask: "which patch ids belong to <part>?" The answer is a set of integers.
    4. Fuse votes per patch across views. The patch is the atom -- there is no flood, no
       spread and no per-pixel decay, so there is nothing to smear.

The honest knob, named as such: GLYPH_PX, how large an id must be drawn to be legible.
It converts to millimetres through the camera exactly as `spread` did, and it sets the
finest patch a view can talk about. It is a property of the reading agent's eyesight,
not of the object, which is why it is a constant here and not something derived.
"""

import json

import numpy as np

GLYPH_PX = 22          # legible id size at the render resolutions in use
TILE_FACTOR = 3.0      # a patch should hold roughly a tile of TILE_FACTOR x glyph


def build_patches(mesh, target_mm, seed_offset=0):
    """Geodesic Voronoi patches over the face graph. Returns per-face patch ids.

    Farthest-point seeding, then one multi-source Dijkstra where each face is claimed by
    whichever seed reaches it first. Edge costs are centroid distances scaled up across
    creases, so patch borders prefer to lie in concavities -- the same cue information as
    before, but now only ADVISORY: it shapes patches, and the agent decides which
    patches make a part.
    """
    import scipy.sparse as sparse
    from scipy.sparse.csgraph import dijkstra

    centres = mesh.triangles.mean(axis=1)
    area = float(mesh.area)
    count = int(np.clip(round(area / (target_mm * target_mm)), 24, 900))

    adjacency = mesh.face_adjacency
    normals = mesh.face_normals
    step = np.linalg.norm(centres[adjacency[:, 0]] - centres[adjacency[:, 1]], axis=1)
    turn = 1.0 - np.einsum("ij,ij->i", normals[adjacency[:, 0]],
                           normals[adjacency[:, 1]])
    cost = step * (1.0 + 8.0 * np.clip(turn, 0.0, 2.0))
    n = len(mesh.faces)
    graph = sparse.coo_matrix(
        (np.concatenate([cost, cost]),
         (np.concatenate([adjacency[:, 0], adjacency[:, 1]]),
          np.concatenate([adjacency[:, 1], adjacency[:, 0]]))),
        shape=(n, n)).tocsr()

    # Farthest-point seeds: deterministic, spread, and one per connected body first so a
    # print-in-place model never loses a body to seeding.
    seeds = [int(seed_offset) % n]
    distance = dijkstra(graph, directed=False, indices=seeds[0], min_only=True)
    unreachable = ~np.isfinite(distance)
    while unreachable.any():
        extra = int(np.flatnonzero(unreachable)[0])
        seeds.append(extra)
        more = dijkstra(graph, directed=False, indices=extra, min_only=True)
        distance = np.minimum(distance, more)
        unreachable = ~np.isfinite(distance)
    while len(seeds) < count:
        far = int(np.argmax(distance))
        if not np.isfinite(distance[far]) or distance[far] <= 0:
            break
        seeds.append(far)
        more = dijkstra(graph, directed=False, indices=far, min_only=True)
        distance = np.minimum(distance, more)

    _dist, _pred, owner = dijkstra(graph, directed=False, indices=seeds,
                                   min_only=True, return_predecessors=True)
    lookup = {seed: i for i, seed in enumerate(seeds)}
    face_patch = np.array([lookup.get(int(s), 0) for s in owner], dtype=np.int32)
    return face_patch, len(seeds)


def patch_adjacency(mesh, face_patch, count):
    """Which patches touch, over face adjacency."""
    a = face_patch[mesh.face_adjacency[:, 0]]
    b = face_patch[mesh.face_adjacency[:, 1]]
    cross = a != b
    pairs = np.unique(np.stack([np.minimum(a[cross], b[cross]),
                                np.maximum(a[cross], b[cross])], axis=1), axis=0)
    neighbours = [[] for _ in range(count)]
    for x, y in pairs:
        neighbours[int(x)].append(int(y))
        neighbours[int(y)].append(int(x))
    return neighbours


def patch_colours(count, seed=7):
    """Distinct-ish colours for the id render. Legibility, not beauty."""
    rng = np.random.default_rng(seed)
    hues = rng.permutation(count) / max(count, 1)
    out = np.zeros((count, 3))
    for i, h in enumerate(hues):
        x = h * 6.0
        c = np.array([np.clip(2 - abs(x - 3), 0, 1),
                      np.clip(2 - abs((x + 2) % 6 - 3), 0, 1),
                      np.clip(2 - abs((x + 4) % 6 - 3), 0, 1)])
        out[i] = 0.35 + 0.55 * c
    return out


def render_id_view(mesh, face_patch, count, camera, lit, glyph_px=GLYPH_PX,
                   only=None):
    """The shaded view with patch ids drawn where each patch is big enough to name.

    Returns (png bytes, visible patch ids). A patch too small on screen for a legible
    glyph simply is not asked about in this view -- another view will see it larger.
    """
    import io
    from PIL import Image, ImageDraw

    origins, rays = camera.rays()
    size = camera.pixels
    hit = mesh.ray.intersects_first(ray_origins=origins,
                                    ray_directions=rays).reshape(size, size)
    visible = hit >= 0
    patch_px = np.full((size, size), -1, dtype=np.int32)
    patch_px[visible] = face_patch[hit[visible]]

    colours = patch_colours(count)
    image = np.ones((size, size, 3))
    image[visible] = colours[patch_px[visible]] * (0.45 + 0.55 * lit[visible, None])
    # Patch borders in black so grouping is readable.
    border = np.zeros((size, size), dtype=bool)
    for dy, dx in ((0, 1), (1, 0)):
        shifted = np.roll(np.roll(patch_px, dy, axis=0), dx, axis=1)
        border |= visible & (shifted != patch_px)
    image[border] *= 0.25

    picture = Image.fromarray((image * 255).astype(np.uint8))
    draw = ImageDraw.Draw(picture)
    listed = []
    wanted = range(count) if only is None else sorted(only)
    for pid in wanted:
        ys, xs = np.nonzero(patch_px == pid)
        if len(xs) < glyph_px * glyph_px:
            continue
        cx, cy = int(np.median(xs)), int(np.median(ys))
        if patch_px[cy, cx] != pid:
            k = np.argmin((xs - cx) ** 2 + (ys - cy) ** 2)
            cx, cy = int(xs[k]), int(ys[k])
        text = str(pid)
        tw = draw.textlength(text)
        draw.rectangle([cx - tw / 2 - 3, cy - 8, cx + tw / 2 + 3, cy + 8],
                       fill=(255, 255, 255))
        draw.text((cx - tw / 2, cy - 7), text, fill=(0, 0, 0))
        listed.append(pid)
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue(), listed


ASSIGN_PROMPT = """You are labelling a 3D model for painting. You get two images of the \
SAME view: first the plain shaded model, second the same view divided into numbered \
patches (black borders, white id tags).

The parts to find:
%s

What the piece is: %s

For each part VISIBLE in this view, list the patch ids that belong to it. Rules:
- A patch belongs to the part covering MOST of it. Every id you list must be readable \
in the second image.
- Paired features (eyes, horns, ears, fins, tusks) exist on BOTH sides. If you list one \
side, look for the other in this view too; single-sided answers are usually misses.
- Omit parts you cannot see. Omit patches you are unsure about -- another view will \
catch them; a wrong assignment pollutes every view's evidence.
- Ids you do not mention stay unassigned. That is fine.

Reply with ONLY a JSON object, no prose, no code fences:
{"assignments": [{"part": str, "patch_ids": [int, ...]}]}"""


def ask_assignments(backend, shaded_png, id_png, listed, vocabulary, intent, key):
    """One view's question. Returns {part: [patch ids]} filtered to legible ids."""
    import os
    shaded_path = os.path.join(backend.directory, "%s-shaded.png" % key)
    id_path = os.path.join(backend.directory, "%s-ids.png" % key)
    for path, blob in ((shaded_path, shaded_png), (id_path, id_png)):
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(blob)
    lines = "\n".join("- %s: %s" % (p["label"], p.get("note", "")) for p in vocabulary)
    prompt = ASSIGN_PROMPT % (lines, intent or "not stated")
    answer = backend._run([shaded_path, id_path], prompt, key)
    if not answer:
        return {}
    legible = set(int(i) for i in listed)
    out = {}
    for entry in answer.get("assignments", []):
        part = entry.get("part", "")
        ids = [int(i) for i in entry.get("patch_ids", []) if int(i) in legible]
        if part and ids:
            out[part] = ids
    return out


def fuse_votes(vote_rounds, count, labels):
    """Tally per-patch votes across views. The patch is the atom; ties stay open."""
    index = {label: i for i, label in enumerate(labels)}
    votes = np.zeros((count, len(labels)))
    for round_votes, weight in vote_rounds:
        for part, ids in round_votes.items():
            if part not in index:
                continue
            for pid in ids:
                if 0 <= pid < count:
                    votes[pid, index[part]] += weight
    assigned = np.full(count, -1, dtype=np.int32)
    voted = votes.sum(axis=1) > 0
    assigned[voted] = np.argmax(votes[voted], axis=1)
    return assigned, votes


def fill_unassigned(assigned, neighbours):
    """Unvoted patches take the majority label of their assigned neighbours.

    Pure graph hops on the patch graph -- no length, no constant. A patch nobody ever
    saw (an interior surface) ends where its surroundings end, which is the only
    defensible guess and is marked as a guess by having zero votes.
    """
    out = assigned.copy()
    for _ in range(64):
        missing = np.flatnonzero(out < 0)
        if not len(missing):
            break
        changed = False
        for pid in missing:
            near = [out[q] for q in neighbours[pid] if out[q] >= 0]
            if near:
                values, counts = np.unique(near, return_counts=True)
                out[pid] = int(values[np.argmax(counts)])
                changed = True
        if not changed:
            break
    return out


def contested(votes, assigned):
    """Which patches the statistics do not settle (spec §9: variance drives resampling).

    Two ways a patch is unsettled: nobody ever voted for it, or the margin between its
    top two labels is thin. A thin margin over many views is a real disagreement, not
    noise -- the views are looking at the same surface and reading it differently -- so
    the remedy is the one §9 prescribes for high variance anywhere: aim more looks at
    exactly that surface, closer.
    """
    top = votes.max(axis=1)
    second = np.partition(votes, -2, axis=1)[:, -2] if votes.shape[1] >= 2 else 0 * top
    never = top <= 0
    thin = (top > 0) & ((top - second) < 0.5 * top)
    return np.flatnonzero(never | thin)


def contested_views(mesh, face_patch, ids, views=6):
    """Cameras aimed at clusters of contested patches, framed close.

    The clusters come from the patch centroids themselves -- the same
    spatial-grouping-by-place lesson the deficit cameras learned: a direction alone
    localises nothing.
    """
    centres = np.zeros((len(ids), 3))
    normals = np.zeros((len(ids), 3))
    patch_centres = {}
    face_centres = mesh.triangles.mean(axis=1)
    for k, pid in enumerate(ids):
        mine = np.flatnonzero(face_patch == pid)
        centres[k] = face_centres[mine].mean(axis=0)
        normals[k] = mesh.face_normals[mine].mean(axis=0)
    out = []
    remaining = np.ones(len(ids), dtype=bool)
    for _ in range(views):
        if not remaining.any():
            break
        seed = int(np.flatnonzero(remaining)[0])
        near = np.linalg.norm(centres - centres[seed], axis=1)
        group = remaining & (near < np.percentile(near[remaining], 40) + 1e-9)
        cluster = centres[group]
        pooled = normals[group].sum(axis=0)
        norm = np.linalg.norm(pooled)
        direction = -pooled / norm if norm > 1e-9 else np.array([0.0, -1.0, -0.3])
        centre = cluster.mean(axis=0)
        radius = max(float(np.abs(cluster - centre).max()) * 1.6, 1e-3)
        out.append((direction, centre, radius))
        remaining &= ~group
    return out
