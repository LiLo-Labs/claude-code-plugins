"""Atom-level consensus: neighbour fill, weak-vote smoothing, correction loop.

The bleed this module removes had one cause: labels were allowed to move at FACE
granularity. The old fill grew label fronts face-by-face across the mesh, so
wherever two fronts raced, the part boundary landed on an arbitrary jagged line
through the middle of a feature -- a grey wedge across a shoulder, a half-white
spike. Here a label only ever moves a whole atom at a time, so every boundary in
the result is an atom boundary, and atom boundaries are the concave junctions
and relief edges the 3D segmentation found. Parts stay crisp by construction;
blending across parts becomes a choice a later stage could make, never an
accident of fill order.

Three passes, in order:

    fill    -- an unvoted atom adopts the label holding the most of its shared
               boundary with already-labelled neighbours; iterated to closure.
    smooth  -- an atom whose own votes were weak (or absent) and whose boundary
               is dominated by a single different label flips to it. This kills
               isolated misvotes without eroding genuine boundaries, because an
               atom with a confident vote is never touched.
    audit   -- the agent is shown the CURRENT assignment (each part in a legend
               colour) next to the numbered id render, and files corrections:
               the barnacle left unpainted, the second horn labelled as an ear,
               the spike wearing two colours. Corrections are heavy votes; the
               loop refuses, refills, resmooths, and repeats until the agent
               has nothing left to correct. Coverage of every instance is
               something someone has to LOOK for; this is where it is looked
               for.
"""

import io
import os

import numpy as np


def boundary_weights(mesh, atom_map, count):
    """Sparse atom-adjacency matrix weighted by shared-edge counts."""
    import scipy.sparse as sparse
    edges = mesh.face_adjacency
    a = atom_map[edges[:, 0]].astype(np.int64)
    b = atom_map[edges[:, 1]].astype(np.int64)
    ok = (a >= 0) & (b >= 0) & (a != b)
    ones = np.ones(int(ok.sum()))
    matrix = sparse.coo_matrix((ones, (a[ok], b[ok])), shape=(count, count))
    return (matrix + matrix.T).tocsr()


def fill(assigned, weights, label_count, rounds=64):
    """Unvoted atoms adopt the boundary-majority label of their neighbours."""
    assigned = assigned.copy()
    for _ in range(rounds):
        missing = assigned < 0
        if not missing.any():
            break
        onehot = np.zeros((len(assigned), label_count))
        has = assigned >= 0
        onehot[has, assigned[has]] = 1.0
        support = weights @ onehot
        strength = support.max(axis=1)
        adopt = missing & (strength > 0)
        if not adopt.any():
            break
        assigned[adopt] = np.argmax(support[adopt], axis=1)
    return assigned


def smooth(assigned, votes, weights, flip_margin=0.5, surround=0.7, sweeps=3):
    """Flip weak atoms surrounded by one label; confident atoms never move."""
    assigned = assigned.copy()
    total = np.asarray(weights.sum(axis=1)).ravel()
    top = votes.max(axis=1)
    second = (np.partition(votes, -2, axis=1)[:, -2]
              if votes.shape[1] >= 2 else np.zeros_like(top))
    weak = (top <= 0) | ((top - second) < flip_margin * top)
    for _ in range(sweeps):
        has = assigned >= 0
        onehot = np.zeros((len(assigned), votes.shape[1]))
        onehot[has, assigned[has]] = 1.0
        support = weights @ onehot
        dominant = np.argmax(support, axis=1)
        dominance = support.max(axis=1)
        flip = (weak & has & (dominant != assigned)
                & (dominance >= surround * np.maximum(total, 1e-9)))
        if not flip.any():
            break
        assigned[flip] = dominant[flip]
    return assigned


def absorb_islands(assigned, weights, atom_area, label_count, min_share=0.15,
                   dominance=0.6, sweeps=3, log=None):
    """Satellite fragments join the label that surrounds them.

    An audit correction is deliberately immune to smoothing, which means a
    stray correction leaves a confident orphan -- nine "ear" pieces where the
    ears are two. The discriminator between an orphan and a legitimate
    instance is SIZE RELATIVE TO ITS OWN LABEL: hooves come four to a cow but
    all four are the same size, while a satellite is a sliver next to its
    label's real component. A component smaller than `min_share` of its
    label's largest component, bordered mostly (`dominance`) by one other
    label, is absorbed into that label. Repeated parts survive because their
    instances are peers.
    """
    import scipy.sparse as sparse
    assigned = assigned.copy()
    coo = weights.tocoo()
    for _sweep in range(sweeps):
        ok = (assigned[coo.row] >= 0) & (assigned[coo.row] == assigned[coo.col])
        same = sparse.coo_matrix((coo.data[ok], (coo.row[ok], coo.col[ok])),
                                 shape=weights.shape).tocsr()
        count, component = sparse.csgraph.connected_components(same,
                                                               directed=False)
        comp_area = np.bincount(component, weights=atom_area, minlength=count)
        comp_label = np.full(count, -1, dtype=np.int64)
        has = assigned >= 0
        comp_label[component[has]] = assigned[has]
        largest = np.zeros(label_count)
        for comp in range(count):
            label = comp_label[comp]
            if label >= 0:
                largest[label] = max(largest[label], comp_area[comp])
        moved = 0
        for comp in range(count):
            label = comp_label[comp]
            if label < 0 or comp_area[comp] >= min_share * largest[label]:
                continue
            members = np.flatnonzero(component == comp)
            inside = np.isin(coo.row, members) & ~np.isin(coo.col, members)
            outside_ok = inside & (assigned[coo.col] >= 0)
            if not outside_ok.any():
                continue
            tally = np.bincount(assigned[coo.col[outside_ok]],
                                weights=coo.data[outside_ok],
                                minlength=label_count)
            neighbour = int(np.argmax(tally))
            if neighbour != label and tally[neighbour] >= dominance * tally.sum():
                assigned[members] = neighbour
                moved += 1
        if log and moved:
            log("  absorbed %d satellite fragment(s)" % moved)
        if not moved:
            break
    return assigned


def smooth_boundaries(mesh, face_part, iterations=12, crease_deg=None):
    """Relax label boundaries at face level where the surface is smooth.

    Atom borders are honest where they follow creases and relief; on smooth
    blended skin they are diffusion-tile scribbles, and a staircase edge
    between two contrasting filaments is glaring on the print. A face flips
    to the label carried by the majority of its neighbours only when none of
    the crossed edges is a real crease, so a boundary that sits on a feature
    stays exactly where the 3D segmentation put it and a boundary crossing
    open skin straightens out.
    """
    adjacency = mesh.face_adjacency
    angles = mesh.face_adjacency_angles
    if crease_deg is None:
        # "Crease" means sharp FOR THIS SURFACE: a fixed number froze a
        # gently-blended sculpt solid. The threshold is the tail of the
        # mesh's own dihedral distribution.
        crease_deg = max(float(np.degrees(np.quantile(angles, 0.90))), 10.0)
    smooth_edge = angles < np.radians(crease_deg)
    face_part = face_part.copy()
    neighbours = [[] for _ in range(len(mesh.faces))]
    for (a, b), ok in zip(adjacency, smooth_edge):
        if ok:
            neighbours[int(a)].append(int(b))
            neighbours[int(b)].append(int(a))
    for _sweep in range(iterations):
        left = face_part[adjacency[:, 0]]
        right = face_part[adjacency[:, 1]]
        on_boundary = np.zeros(len(mesh.faces), dtype=bool)
        cross = left != right
        on_boundary[adjacency[cross, 0]] = True
        on_boundary[adjacency[cross, 1]] = True
        changed = 0
        for face in np.flatnonzero(on_boundary):
            near = neighbours[face]
            if len(near) < 2:
                continue
            votes = {}
            for other in near:
                votes[face_part[other]] = votes.get(face_part[other], 0) + 1
            best, count = max(votes.items(), key=lambda item: item[1])
            if count >= 2 and best != face_part[face] and best >= 0:
                face_part[face] = best
                changed += 1
        if not changed:
            break
    return face_part


def feather_lab(mesh, lab_face, face_part, iterations=6, crease_deg=None):
    """Soften colour across smooth part boundaries; stay crisp at creases.

    A painted figure blends where the anatomy blends -- the muzzle fades into
    the head -- and breaks hard only where the surface itself breaks. Colour
    diffuses across smooth edges within a narrow band around label
    boundaries; a crease edge never mixes, so an eye rim or a shell lip stays
    a clean line. Geometry is untouched; this shades the CONTINUOUS design
    only.
    """
    adjacency = mesh.face_adjacency
    angles = mesh.face_adjacency_angles
    if crease_deg is None:
        crease_deg = max(float(np.degrees(np.quantile(angles, 0.90))), 10.0)
    smooth = angles < np.radians(crease_deg)
    pairs = adjacency[smooth]
    differs = face_part[pairs[:, 0]] != face_part[pairs[:, 1]]
    band = np.zeros(len(mesh.faces), dtype=bool)
    band[pairs[differs].ravel()] = True
    for _ring in range(iterations):
        touched = band[pairs[:, 0]] | band[pairs[:, 1]]
        band[pairs[touched].ravel()] = True
    lab = np.asarray(lab_face, dtype=float).copy()
    for _sweep in range(iterations):
        total = lab.copy()
        counts = np.ones(len(lab))
        np.add.at(total, pairs[:, 0], lab[pairs[:, 1]])
        np.add.at(total, pairs[:, 1], lab[pairs[:, 0]])
        np.add.at(counts, pairs[:, 0], 1.0)
        np.add.at(counts, pairs[:, 1], 1.0)
        mixed = total / counts[:, None]
        lab[band] = mixed[band]
    return lab


def render_label_view(mesh, atom_map, assigned, camera, lit):
    """The current assignment as the agent will judge it: legend colours, atom
    borders, unassigned in neutral."""
    from PIL import Image
    from . import atlas
    origins, rays = camera.rays()
    size = camera.pixels
    hit = mesh.ray.intersects_first(ray_origins=origins,
                                    ray_directions=rays).reshape(size, size)
    visible = hit >= 0
    label_px = np.full((size, size), -1, dtype=np.int32)
    label_px[visible] = assigned[atom_map[hit[visible]]]
    atom_px = np.full((size, size), -1, dtype=np.int32)
    atom_px[visible] = atom_map[hit[visible]]

    table = np.array([atlas.DISTINCT[i % len(atlas.DISTINCT)]
                      for i in range(max(int(assigned.max()) + 1, 1))])
    image = np.ones((size, size, 3))
    shade = (0.45 + 0.55 * lit[visible, None])
    coloured = label_px[visible] >= 0
    pixel = np.tile(np.asarray(atlas.NEUTRAL), (int(visible.sum()), 1))
    pixel[coloured] = table[label_px[visible][coloured]]
    image[visible] = pixel * shade
    border = np.zeros((size, size), dtype=bool)
    for dy, dx in ((0, 1), (1, 0)):
        shifted = np.roll(np.roll(atom_px, dy, axis=0), dx, axis=1)
        border |= visible & (shifted != atom_px)
    image[border] *= 0.25
    picture = Image.fromarray((image * 255).astype(np.uint8))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


AUDIT_PROMPT = """You are checking a finished part-labelling of a 3D model \
before it is painted. Three images of the SAME view:
1. the plain shaded model
2. the current assignment -- each part in its legend colour, unassigned areas \
in plain light grey, black borders between segmentation atoms
3. the same view with numbered atom ids

Parts and their legend colours (sRGB hex):
%s

What the piece is: %s

This model will be PRINTED, and every part prints in exactly one filament, so \
uniformity is the contract: every instance of a repeated part (all hooves, all \
spikes, all barnacles) and both sides of every pair must end up in the same \
part -- one odd hoof ruins the print.

Compare image 2 against images 1 and 3 and report ONLY what is wrong:
- an atom wearing the wrong part's colour for what it depicts
- an instance of a repeated part (a barnacle, a spike, a stud, a scale) left \
unassigned or absorbed into a neighbouring part
- a paired feature (eyes, horns, ears, fins, tusks) treated differently on \
the two sides -- correct the wrong side to match its partner
- a single feature split between two colours -- give ALL its atoms to the one \
part it belongs to

Rules: every atom id you use must be readable in image 3. Do not confirm what \
is already right. If nothing in this view is wrong, return an empty list.

Reply with ONLY a JSON object, no prose, no code fences:
{"corrections": [{"part": str, "atom_ids": [int, ...]}]}"""


def ask_corrections(backend, shaded_png, label_png, id_png, listed, vocabulary,
                    labels, intent, key):
    """One audit view. Returns {part: [atom ids]} filtered to legible ids."""
    from . import atlas
    paths = []
    for suffix, blob in (("shaded", shaded_png), ("labels", label_png),
                         ("ids", id_png)):
        path = os.path.join(backend.directory, "%s-%s.png" % (key, suffix))
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(blob)
        paths.append(path)
    legend = "\n".join(
        "- %s: #%02X%02X%02X" % ((label,) + tuple(
            int(round(channel * 255))
            for channel in atlas.DISTINCT[i % len(atlas.DISTINCT)]))
        for i, label in enumerate(labels))
    prompt = AUDIT_PROMPT % (legend, intent or "not stated")
    answer = backend._run(paths, prompt, key)
    if not answer:
        return {}
    legible = set(int(i) for i in listed)
    out = {}
    for entry in answer.get("corrections", []):
        part = entry.get("part", "")
        ids = [int(i) for i in entry.get("atom_ids", []) if int(i) in legible]
        if part in labels and ids:
            out.setdefault(part, []).extend(ids)
    return out


def audit(mesh, frame, backend, atom_map, count, assigned, votes, labels,
          vocabulary, intent, up, weights, pixels=900, views=6, rounds=3,
          workers=3, correction_weight=3.0, log=print):
    """Show, correct, refuse, repeat -- until the agent has nothing to fix."""
    from concurrent.futures import ThreadPoolExecutor
    from . import patches, preview, render as render_module, vision

    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.05
    index = {label: i for i, label in enumerate(labels)}
    history = []
    # The base rounds are COVERAGE (each rotates the cameras 40 degrees, so
    # counts can rise while new angles surface new atoms). After them, extra
    # verify rounds run only while the loop is converging fast -- the last
    # round at most half the one before -- so a run that is nearly clean gets
    # to reach zero, and a plateauing organic sculpt stops burning views.
    hard_cap = rounds + 2
    round_id = 0
    while round_id < hard_cap:
        directions = preview.orbit(views, 22.0, start_deg=30.0 + 40.0 * round_id,
                                   up=up)
        cameras = [render_module.Camera(np.asarray(d, float), up, centre,
                                        radius, pixels) for d in directions]

        # The cache key carries the assignment state: a replayed round must
        # never answer for renders it was not actually shown.
        from . import entities
        state = entities.digest_of(assigned.tobytes())[7:15]

        def one(view_id, camera):
            bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
            shaded = vision.render_png(bundle)
            lit = np.clip(bundle["rgb_lit"], 0, 1)
            label_png = render_label_view(mesh, atom_map, assigned, camera, lit)
            id_png, listed = patches.render_id_view(mesh, atom_map, count,
                                                    camera, lit)
            return ask_corrections(backend, shaded, label_png, id_png, listed,
                                   vocabulary, labels, intent,
                                   "audit-%d-%02d-%s" % (round_id, view_id,
                                                         state))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            answers = list(pool.map(lambda kc: one(kc[0], kc[1]),
                                    enumerate(cameras)))
        corrections = sum(len(ids) for answer in answers
                          for ids in answer.values())
        history.append(corrections)
        log("audit round %d: %d corrections" % (round_id, corrections))
        if not corrections:
            break
        # A correction was made looking at the FUSED result, so it overrides:
        # it must beat whatever vote mass put the atom where it is, or the next
        # round just re-files the same complaint.
        for answer in answers:
            for part, ids in answer.items():
                for atom in ids:
                    votes[atom, index[part]] += (votes[atom].max()
                                                 + correction_weight)
        voted = votes.sum(axis=1) > 0
        assigned = np.where(voted, np.argmax(votes, axis=1), -1).astype(np.int32)
        assigned = fill(assigned, weights, len(labels))
        assigned = smooth(assigned, votes, weights)
        round_id += 1
        if round_id >= rounds and (len(history) < 2
                                   or history[-1] * 2 > history[-2]):
            break
    return assigned, votes, history


def unify_blades(mesh, face_part, log=None):
    """A thin blade is ONE thing: both sides and the rim wear one label.

    Fins, ears, frills and flexi tabs are two-sided sheets. Labels drift per
    side and per rim -- the fish's tail-fin label ended up on the dorsal
    blade's back face and the pectoral label ran down the flank as a rim
    stripe. Thickness is measured by casting each face's ray inward; a face
    whose opposite wall is closer than a few face-lengths is sheet material,
    the ray pairing welds the two sides into one unit, and each unit takes
    its area-majority label. Every threshold is relative to the face's own
    scale; the mesh is untouched.
    """
    import scipy.sparse as sparse
    normals = mesh.face_normals
    centres = mesh.triangles.mean(axis=1)
    scale = np.sqrt(np.maximum(mesh.area_faces, 1e-12))
    origins = centres - normals * (scale[:, None] * 0.05)
    locations, ray_ids, hit_faces = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=-normals, multiple_hits=False)
    thickness = np.full(len(mesh.faces), np.inf)
    partner = np.full(len(mesh.faces), -1, dtype=np.int64)
    if len(ray_ids):
        travel = np.linalg.norm(locations - origins[ray_ids], axis=1)
        thickness[ray_ids] = travel
        partner[ray_ids] = hit_faces
    local = 3.0 * scale
    sheet = thickness < local
    if log:
        log("  blades: %.1f%% of faces are sheet material"
            % (100.0 * sheet.mean()))
    if not sheet.any():
        return face_part
    adjacency = mesh.face_adjacency
    a, b = adjacency[:, 0], adjacency[:, 1]
    keep = sheet[a] & sheet[b]
    rows = list(a[keep])
    cols = list(b[keep])
    pair_ok = sheet & (partner >= 0)
    pair_ok &= np.where(partner >= 0, sheet[np.clip(partner, 0, None)], False)
    rows += list(np.flatnonzero(pair_ok))
    cols += list(partner[pair_ok])
    graph = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)),
                              shape=(len(mesh.faces), len(mesh.faces)))
    count, component = sparse.csgraph.connected_components(graph,
                                                           directed=False)
    face_part = face_part.copy()
    areas = np.asarray(mesh.area_faces)
    changed = 0
    for comp in np.unique(component[sheet]):
        members = np.flatnonzero((component == comp) & sheet)
        if len(members) < 12:
            continue
        held = face_part[members]
        ok = held >= 0
        if not ok.any():
            continue
        tally = np.bincount(held[ok], weights=areas[members][ok])
        majority = int(tally.argmax())
        flips = int((held[ok] != majority).sum())
        if flips:
            face_part[members] = majority
            changed += flips
    if log and changed:
        log("  blades: %d faces unified onto their blade's label" % changed)
    return face_part
