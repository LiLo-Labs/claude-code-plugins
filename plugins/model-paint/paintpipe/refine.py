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
    missing = [label for label in labels
               if areas[index[label]] == 0 and hierarchy.get(label)
               and hierarchy[label] in index and areas[index[hierarchy[label]]] > 0]
    by_parent = {}
    for label in missing:
        by_parent.setdefault(hierarchy[label], []).append(label)

    report = {}
    notes = {part["label"]: part.get("note", "") for part in vocabulary or []}
    for parent, children in by_parent.items():
        parent_faces = np.flatnonzero(face_part == index[parent])
        if len(parent_faces) < 50:
            continue
        sub = trimesh.Trimesh(vertices=mesh.vertices,
                              faces=mesh.faces[parent_faces], process=False)
        centre = sub.triangles.mean(axis=1).mean(axis=0)
        radius = float(np.linalg.norm(
            np.ptp(sub.triangles.reshape(-1, 3), axis=0)) / 2.0) * 1.25
        footprint = 2 * radius / pixels
        target = patch_module.TILE_FACTOR * patch_module.GLYPH_PX * footprint
        local_patch, count = patch_module.build_patches(sub, target)

        # Ask from several sides of the parent.
        vocab_here = ([{"label": parent, "note": "everything not otherwise named"}]
                      + [{"label": c, "note": notes.get(c, "")} for c in children])
        rounds = []
        for k, direction in enumerate(render_module.fibonacci_directions(views)):
            camera = render_module.Camera(-direction, [0, 0, 1], centre, radius, pixels)
            bundle = render_module.render_bundle(sub, camera, "zenithal", frame)
            shaded = vision_module.render_png(bundle)
            lit = np.clip(bundle["rgb_lit"], 0, 1)
            id_png, listed = patch_module.render_id_view(sub, local_patch, count,
                                                         camera, lit)
            key = "refine-%s-%d" % (parent.replace(" ", "_"), k)
            votes = patch_module.ask_assignments(backend, shaded, id_png, listed,
                                                 vocab_here, intent, key)
            rounds.append((votes, 1.0))
        names = [parent] + children
        assigned, _votes = patch_module.fuse_votes(rounds, count, names)
        # Splice: only faces claimed for a CHILD move; everything else stays parent.
        recovered = {}
        for local_face in range(len(parent_faces)):
            claim = assigned[local_patch[local_face]]
            if claim > 0:
                child = names[int(claim)]
                face_part[parent_faces[local_face]] = index[child]
                recovered[child] = recovered.get(child, 0) + 1
        report[parent] = recovered
    return face_part, report


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
