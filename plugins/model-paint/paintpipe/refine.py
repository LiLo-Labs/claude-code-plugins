"""Sub-part refinement and agentic review of the finished scheme (spec §10 Critic).

Two gaps this closes, both found by a person looking at a result the pipeline had
called done:

SUB-PARTS BELOW PATCH RESOLUTION. Eye sockets, horns, snout and belly plates came back
with zero area -- each is smaller than one patch at the overview camera, so no view
could ever assign them. The fix is the hierarchy the identity agent already provides:
zoom a camera onto the PARENT part, re-patch only the parent's own faces at the finer
footprint the closer camera affords, and ask the same question again. Same mechanism,
smaller glyphs; nothing new to tune.

THE CRITIC MUST LOOK. The deterministic stand-in reviews thresholds; a painter reviews
the render. "Why are the eyes not black?" is not answerable by any posterior statistic
-- it is a judgement about what a finished piece needs, and it is asked of the agent by
showing it the finished piece.
"""

import json
import os

import numpy as np


def parent_of(vocabulary):
    out = {}
    for part in vocabulary or []:
        name = part.get("label")
        if name:
            above = (part.get("parent") or "").strip()
            out[name] = above if above and above != name else None
    return out


def refine_subparts(mesh, face_part, labels, vocabulary, backend, intent,
                    frame=None, views=4, pixels=760):
    """Zoom onto each parent whose children came back empty; re-patch, re-ask, splice.

    Returns the updated per-face part index and a report of what was recovered. Faces
    are only ever moved from a parent to one of its own children, so a bad answer can
    misplace detail within the parent but can never leak it across a part boundary the
    coarse pass already settled.
    """
    from . import patches as patch_module
    from . import render as render_module
    from . import vision as vision_module
    import trimesh

    index = {label: i for i, label in enumerate(labels)}
    hierarchy = parent_of(vocabulary)
    areas = np.bincount(face_part[face_part >= 0], minlength=len(labels)).astype(float)
    empty = [label for label in labels if areas[index[label]] == 0]
    present = [label for label in labels if areas[index[label]] > 0]
    by_parent = {}
    orphans = []
    for label in empty:
        parent = hierarchy.get(label)
        if parent and parent in index and areas[index[parent]] > 0:
            by_parent.setdefault(parent, []).append(label)
        else:
            orphans.append(label)
    # A missing part with no usable declared parent gets one by ASKING (tail of the
    # cow, tusks of the ogre, eyes of the fish -- all empty, all with no parent that
    # held area, all previously unreachable by any zoom).
    if orphans and present:
        adopted = adopt_hosts(backend, orphans, present, intent)
        for label, host in adopted.items():
            by_parent.setdefault(host, []).append(label)

    report = {}
    notes = {part["label"]: part.get("note", "") for part in vocabulary or []}
    adjacency = mesh.face_adjacency
    for parent, children in by_parent.items():
        host_faces = np.flatnonzero(face_part == index[parent])
        if len(host_faces) < 50:
            continue
        # THE SEARCH REGION IS SPATIAL, NOT LABEL-BOUND. Restricting the zoom to the
        # host's own faces assumed the missing part's geometry currently carries the
        # host's label -- but the ogre's tusks were labelled skull dome, so a zoom onto
        # "lips and mouth" could not contain a single tusk face and returned nothing,
        # honestly, forever. The region is now the host plus adjacency rings out to
        # roughly 2.5x the host's area, so anatomy mislabelled to a NEIGHBOUR is inside
        # the frame. Claims still move faces only INTO the missing children, and the
        # visual confirm gate still stands between a claim and the model.
        inside = np.zeros(len(mesh.faces), dtype=bool)
        inside[host_faces] = True
        host_area = float(mesh.area_faces[host_faces].sum())
        for _ring in range(12):
            if float(mesh.area_faces[inside].sum()) >= 2.5 * host_area:
                break
            touch = inside[adjacency[:, 0]] | inside[adjacency[:, 1]]
            grow = np.unique(adjacency[touch].ravel())
            before = int(inside.sum())
            inside[grow] = True
            if int(inside.sum()) == before:
                break
        parent_faces = np.flatnonzero(inside)
        sub = trimesh.Trimesh(vertices=mesh.vertices,
                              faces=mesh.faces[parent_faces], process=False)
        centre = sub.triangles.mean(axis=1).mean(axis=0)
        radius = float(np.linalg.norm(
            np.ptp(sub.triangles.reshape(-1, 3), axis=0)) / 2.0) * 1.25
        footprint = 2 * radius / pixels
        target = patch_module.TILE_FACTOR * patch_module.GLYPH_PX * footprint
        local_patch, count = patch_module.build_patches(sub, target)

        # Every label actually present in the frame is offered, so the agent is not
        # forced to launder neighbouring anatomy through the host's name; but only
        # claims for the MISSING children ever move a face.
        local_labels = sorted({labels[int(face_part[f])] for f in parent_faces
                               if face_part[f] >= 0})
        vocab_here = ([{"label": l, "note": notes.get(l, "")} for l in local_labels]
                      + [{"label": c, "note": notes.get(c, "")} for c in children])
        rounds = []
        for k, direction in enumerate(render_module.fibonacci_directions(views)):
            camera = render_module.Camera(-direction, [0, 0, 1], centre, radius, pixels)
            bundle = render_module.render_bundle(sub, camera, "zenithal", frame)
            shaded = vision_module.render_png(bundle)
            lit = np.clip(bundle["rgb_lit"], 0, 1)
            id_png, listed = patch_module.render_id_view(sub, local_patch, count,
                                                         camera, lit)
            from . import entities as entities_module
            state = entities_module.digest_of(
                {"faces": parent_faces, "children": children})[7:17]
            key = "refine-%s-%s-%d" % (parent.replace(" ", "_"), state, k)
            votes = patch_module.ask_assignments(backend, shaded, id_png, listed,
                                                 vocab_here, intent, key)
            rounds.append((votes, 1.0))
        names = local_labels + children
        child_ids = {names.index(c) for c in children}
        assigned, _votes = patch_module.fuse_votes(rounds, count, names)
        # Splice: only faces claimed for a CHILD move; everything else stays parent. A
        # recovery can therefore never award faces to an already-healthy label -- the
        # candidate set is the parent's faces and the destinations are its missing
        # children, nothing else.
        recovered = {}
        moved = {}
        for local_face in range(len(parent_faces)):
            claim = assigned[local_patch[local_face]]
            if claim >= 0 and int(claim) in child_ids:
                child = names[int(claim)]
                moved.setdefault(child, []).append(local_face)
        # VERIFY BEFORE KEEPING. Two of three recoveries on the CC0 set failed while
        # reporting success: faces landed on the wrong anatomy (a fish's "eyes" as a
        # blob on its flank) or nothing landed at all while the log still printed a
        # recovered dict. So each claim is now shown back to the agent -- the claimed
        # faces highlighted red on the parent -- and kept only on a yes. A no reverts
        # the faces and is logged as the failure it is.
        for child, local_faces in moved.items():
            ok = _confirm_claim(backend, sub, local_faces, child, intent, centre,
                                radius, pixels, frame)
            if ok:
                for local_face in local_faces:
                    face_part[parent_faces[local_face]] = index[child]
                recovered[child] = len(local_faces)
            else:
                report.setdefault("_rejected", {})[child] = len(local_faces)
        report[parent] = recovered
    # Loud failure beats a quiet wrong answer: name every part still empty.
    final_areas = np.bincount(face_part[face_part >= 0], minlength=len(labels))
    for label in labels:
        if final_areas[index[label]] == 0:
            report.setdefault("_failed", []).append(label)
    return face_part, report


def _confirm_claim(backend, sub, local_faces, child, intent, centre, radius, pixels,
                   frame):
    """Show the claimed faces highlighted and ask if they are the named part."""
    import io
    from PIL import Image
    from . import render as render_module

    mask = np.zeros(len(sub.faces), dtype=bool)
    mask[local_faces] = True
    best = None
    # View the claim from the claimed faces' own pooled facing, so it is visible.
    normals = sub.face_normals[mask].mean(axis=0)
    norm = np.linalg.norm(normals)
    direction = -normals / norm if norm > 1e-9 else np.array([0.0, -1.0, -0.3])
    camera = render_module.Camera(direction, [0, 0, 1], centre, radius, pixels)
    bundle = render_module.render_bundle(sub, camera, "zenithal", frame)
    lit = np.clip(bundle["rgb_lit"], 0, 1)
    visible = bundle["visible"]
    hit = bundle["hit_id"]
    image = np.ones((pixels, pixels, 3))
    grey = 0.35 + 0.55 * lit
    image[visible] = grey[visible, None]
    claimed_px = visible & mask[np.clip(hit, 0, len(mask) - 1)]
    image[claimed_px] = np.stack([0.35 + 0.6 * lit[claimed_px],
                                  0.15 * lit[claimed_px],
                                  0.10 * lit[claimed_px]], axis=1)
    buffer = io.BytesIO()
    Image.fromarray((image * 255).astype(np.uint8)).save(buffer, format="PNG")
    from . import entities as entities_module
    key = "confirm-%s-%s" % (child.replace(" ", "_"),
                             entities_module.digest_of(buffer.getvalue())[7:17])
    path = os.path.join(backend.directory, "%s.png" % key)
    with open(path, "wb") as handle:
        handle.write(buffer.getvalue())
    prompt = ("The RED region on this model is claimed to be: %s\n"
              "The piece: %s\n\n"
              "Is the red region actually the %s -- on the right anatomy, in the right "
              "place? Answer strictly.\n\n"
              'Reply with ONLY a JSON object, no prose: {"correct": true} or '
              '{"correct": false}' % (child, intent or "a model", child))
    answer = backend._run([path], prompt, key)
    return bool(answer and answer.get("correct"))


ADOPT_PROMPT = """You are locating missing parts on a 3D model so a zoom camera can go find them. These parts were named but never found:
%s

These parts WERE found and hold surface area:
%s

The piece: %s

For each missing part, name the ONE found part that physically contains it or that it sits directly on. Look at the images if given.

Reply with ONLY a JSON object, no prose, no code fences:
{"adoptions": [{"missing": str, "host": str}]}"""


def adopt_hosts(backend, missing, present, intent, overview_paths=()):
    """Ask which present part each missing part lives on. Agent-declared hierarchy.

    The identity agent's parent field covers the usual case, but a missing part whose
    declared parent is itself empty -- or root -- leaves the zoom pass with nowhere to
    look. The tail of the cow, the tusks of the ogre and the eyes of the fish all fell
    through exactly this hole, and the critic's colour override on them was a no-op on
    zero faces, which is the worst kind of fix: one that reports success.
    """
    prompt = ADOPT_PROMPT % ("\n".join("- %s" % m for m in missing),
                             "\n".join("- %s" % p for p in present),
                             intent or "not stated")
    from . import entities as entities_module
    key = "adoptions-%s" % entities_module.digest_of(
        {"missing": sorted(missing), "present": sorted(present)})[7:17]
    answer = backend._run(list(overview_paths), prompt, key)
    if not answer:
        return {}
    valid = set(present)
    return {entry["missing"]: entry["host"]
            for entry in answer.get("adoptions", [])
            if entry.get("host") in valid and entry.get("missing") in missing}


REVIEW_PROMPT = """You are reviewing the paint scheme for a 3D print as a miniature \
painter with final sign-off. You get renders of the finished piece and the table of \
what each part was painted.

The piece: %s

The scheme as printed:
%s

The printer has exactly these filaments: %s. Every part is exactly one filament.

Judge the FINISHED PIECE, not the intent. Say what a painter would change so the piece
reads better -- eyes that vanish, parts that merge into their background, a filament
wasted where it does no work. If it already reads well, say so and change nothing.

Reply with ONLY a JSON object, no prose, no code fences:
{"verdict": str, "changes": [{"part": str, "filament": str, "why": str}]}"""


def review_scheme(backend, render_paths, scheme, chosen, palette, intent):
    """Show the critic the finished renders; return filament overrides it insists on."""
    lines = "\n".join("- %-24s -> %-8s (wanted %s, role %s)"
                      % (entry["region"], chosen[entry["region"]].name,
                         entry.get("hex", "?"), entry.get("role", "?"))
                      for entry in scheme)
    filaments = ", ".join(paint.name for paint in palette)
    prompt = REVIEW_PROMPT % (intent or "not stated", lines, filaments)
    answer = backend._run(list(render_paths), prompt, "critic-review")
    if not answer:
        return {}, "review unavailable"
    by_name = {paint.name.lower(): paint for paint in palette}
    overrides = {}
    for change in answer.get("changes", []):
        part = change.get("part", "")
        paint = by_name.get((change.get("filament", "") or "").lower())
        if part and paint is not None:
            overrides[part] = (paint, change.get("why", ""))
    return overrides, answer.get("verdict", "")
