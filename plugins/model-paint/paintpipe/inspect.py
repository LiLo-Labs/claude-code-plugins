"""The final inspector: open eyes, bounded hands, and a loop.

Every other reviewer in this pipeline answers a scripted question. This one
is asked the open one -- what would a demanding customer flag on the finished
piece? -- and is given levers to act on what it sees, the same levers a person
driving the CLI has:

    repaint          a part moves to another filament
    darken_recesses  a part's deep cavities (by ITS OWN occlusion
                     distribution) take a darker filament -- nostril holes,
                     mouth throats, zonal shading where the reviewer judges
                     the piece needs it
    absorb_fragments a part keeps its K real instances and its slivers
                     dissolve into what surrounds them
    needs_capability what it saw but cannot fix with these levers, logged
                     verbatim -- the development backlog, written by the
                     pipeline about itself

It looks, acts, re-renders, and looks again until it has nothing left to
flag or the round budget ends. Findings it cannot act on are still findings:
they go in the report, not in the bin.
"""

import json
import os

import numpy as np

INSPECT_PROMPT = """You are the final quality inspector for a 3D-printed, \
multi-filament painted piece. The images show the FINISHED result: a full \
turnaround, a hero view, and close-ups of individual parts. Judge it the way \
a demanding customer would -- at arm's length and up close.

The piece: %s

Parts and their filaments:
%s

Loaded filaments: %s

Standards that matter: cavities and holes read dark (a nostril or open mouth \
painted the surface colour looks like a sticker); one material reads as one \
substance; no stray slivers of one part's colour stranded on another part; \
features legible at arm's length; restraint -- no filament needs a job. \
Beyond these, flag ANYTHING you would flag as a buyer.

For each finding, act with one of:
- {"action": "repaint", "part": str, "filament": str, "why": str}
- {"action": "darken_recesses", "part": str, "filament": str, \
"depth": "deep" or "shallow", "why": str} -- deep hits only true cavities, \
shallow also shades strong concavities; only compact cavity floors are \
painted, and the action refuses parts whose "recesses" are scattered creases
- {"action": "absorb_fragments", "part": str, "keep": int, "why": str} -- \
keep the part's `keep` largest pieces, dissolve the rest into surroundings
- {"action": "clear_recesses", "part": str, "why": str} -- undo this part's \
recess darkening; use it when an earlier darkening reads as splotches
- {"action": "relocate", "part": str, "note": str, "why": str} -- the part's \
paint is NOT on the part's real geometry (its colour sits somewhere else, or \
the named feature renders bare). `note` describes where the feature really \
is, precisely, for a locating camera
- {"action": "needs_capability", "note": str} -- something real that none of \
these levers can fix; describe it precisely

An empty list means the piece passes. Do not restate what is already right.

Reply with ONLY a JSON object, no prose, no code fences:
{"verdict": str, "findings": [ ... ]}"""


def _compact_pools(mesh, recess):
    """Keep only cavity-sized components of a recess selection.

    Components are measured against the largest pool: anything under a tenth
    of it is a speck. If even the survivors are nothing but specks relative
    to the selection, the "cavity" was scattered creases -- return nothing.
    """
    import scipy.sparse as sparse
    if len(recess) == 0:
        return recess
    inside = np.zeros(len(mesh.faces), dtype=bool)
    inside[recess] = True
    adjacency = mesh.face_adjacency
    both = inside[adjacency[:, 0]] & inside[adjacency[:, 1]]
    local = {int(f): i for i, f in enumerate(recess)}
    rows = [local[int(a)] for a, b in adjacency[both]]
    cols = [local[int(b)] for a, b in adjacency[both]]
    graph = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)),
                              shape=(len(recess), len(recess)))
    n_comp, comp = sparse.csgraph.connected_components(graph, directed=False)
    areas = np.asarray(mesh.area_faces)[recess]
    sizes = np.bincount(comp, weights=areas, minlength=n_comp)
    largest = float(sizes.max())
    keep = np.flatnonzero(sizes >= 0.1 * largest)
    kept = recess[np.isin(comp, keep)]
    # More surviving pools than plausible cavities means a scatter.
    if len(keep) > 8:
        return recess[:0]
    return kept


def final_review(backend, mesh, frame, up, face_part, labels, chosen, palette,
                 occlusion, intent, out_dir, render_final, log,
                 rounds=3, workers=3, features=None):
    """Look, act, re-render, look again. Returns (face_overrides, report).

    `chosen` is mutated in place (part -> Paint). `face_overrides` maps face
    index -> filament slot for face-level decisions (recess darkening) that
    part-level assignment cannot express. `render_final(face_overrides)`
    re-renders the final images from the current state and returns their paths.
    """
    from . import entities
    from . import preview
    from PIL import Image

    by_name = {paint.name: paint for paint in palette}
    slot = {paint.name: i + 1 for i, paint in enumerate(palette)}
    face_overrides = {}
    report = {"rounds": [], "needs_capability": []}
    centres = mesh.triangles.mean(axis=1)

    def part_zooms():
        paths = []
        for label_id, label in enumerate(labels):
            faces = np.flatnonzero(face_part == label_id)
            if len(faces) < 8:
                continue
            centre = centres[faces].mean(axis=0)
            span = float(np.linalg.norm(np.ptp(centres[faces], axis=0)))
            extent = float(np.linalg.norm(np.ptp(mesh.vertices, axis=0)))
            zoom = max(1.2, min(4.0, extent / max(span * 2.2, 1e-6)))
            direction = preview.orbit(1, 12.0, start_deg=40.0
                                      + 67.0 * label_id, up=up)[0]
            table = np.array(
                [(chosen[l].lab if l in chosen else palette[-1].lab)
                 for l in labels])
            lab = np.tile(np.asarray(palette[-1].lab, dtype=float),
                          (len(face_part), 1))
            painted = face_part >= 0
            lab[painted] = table[face_part[painted]]
            for face, filament in face_overrides.items():
                lab[face] = palette[filament - 1].lab
            rgb = preview.lab_to_srgb(lab)
            image = preview.render_asset(mesh, rgb, direction, size=480,
                                         occlusion=occlusion, up=up,
                                         centre=centre, zoom=zoom)
            path = os.path.join(backend.directory,
                                "inspect-part-%d.png" % label_id)
            Image.fromarray(image).save(path)
            paths.append(path)
        return paths

    history = []
    for round_id in range(rounds):
        final_paths = render_final(face_overrides)
        paths = list(final_paths) + part_zooms()
        lines = "\n".join("- %-26s -> %s" % (label,
                                             chosen[label].name
                                             if label in chosen
                                             else palette[-1].name)
                          for label in labels)
        prompt = INSPECT_PROMPT % (intent or "not stated", lines,
                                   ", ".join(p.name for p in palette))
        if history:
            prompt += ("\n\nActions already taken in earlier rounds (the "
                       "current images include their effect; do not repeat "
                       "one, and reverse one only if the images show it made "
                       "things worse):\n"
                       + "\n".join("- %s" % h for h in history))
        blob = prompt.encode("utf-8")
        for path in paths:
            with open(path, "rb") as handle:
                blob += handle.read()
        answer = backend._run(paths, prompt, "inspect-%s"
                              % entities.digest_of(blob)[7:19])
        findings = (answer or {}).get("findings", [])
        verdict = (answer or {}).get("verdict", "")
        acted = 0
        for finding in findings:
            action = finding.get("action", "")
            part = finding.get("part", "")
            why = str(finding.get("why", finding.get("note", "")))[:90]
            if action == "needs_capability":
                report["needs_capability"].append(finding.get("note", ""))
                log("  inspector needs-capability: %s"
                    % str(finding.get("note", ""))[:110])
                continue
            if part not in labels:
                continue
            label_id = labels.index(part)
            faces = np.flatnonzero(face_part == label_id)
            if action == "repaint":
                paint = by_name.get(finding.get("filament", ""))
                if paint is not None:
                    chosen[part] = paint
                    log("  inspector repaint %-22s -> %-7s %s"
                        % (part, paint.name, why))
                    acted += 1
            elif action == "darken_recesses" and len(faces):
                paint = by_name.get(finding.get("filament", ""))
                if paint is None:
                    continue
                depth = finding.get("depth", "deep")
                quantile = 0.18 if depth == "deep" else 0.40
                # The quantile keeps the cut relative to the part, but a
                # cavity is also enclosed in absolute terms -- occlusion is
                # sky visibility, scale-free -- so a mostly-convex part whose
                # "deepest" faces still see half the sky yields nothing.
                ceiling = 0.35 if depth == "deep" else 0.55
                cut = min(float(np.quantile(occlusion[faces], quantile)),
                          ceiling)
                recess = faces[occlusion[faces] <= cut]
                # A real cavity is a few compact pools. On a mostly-convex
                # part the quantile selects scattered creases instead, and
                # painting those black splotches the whole part (the cow's
                # brow paid for this). Keep only components that hold their
                # own against the largest pool; refuse a scatter outright.
                recess = _compact_pools(mesh, recess)
                if len(recess) == 0:
                    log("  inspector darken %-22s refused: recesses are "
                        "scattered creases, not cavities" % part)
                    continue
                for face in recess:
                    face_overrides[int(face)] = slot[paint.name]
                log("  inspector darken %-22s %5d faces -> %-7s %s"
                    % (part, len(recess), paint.name, why))
                acted += 1
            elif action == "relocate":
                from . import refine as refine_module
                relocate = getattr(refine_module, "relocate_part", None)
                if relocate is None:
                    # A long-running process can hold an older refine module
                    # than the inspect module it lazily imported; a finding
                    # is still a finding, so it goes to the backlog instead
                    # of crashing a finished run at the last stage.
                    report["needs_capability"].append(
                        "relocate %s: %s" % (part, finding.get("note", "")))
                    continue
                note = str(finding.get("note", "")) or why
                moved = relocate(
                    backend, mesh, frame, face_part, labels, part, note,
                    intent, up=up, log=log, features=features)
                if moved:
                    acted += 1
            elif action == "clear_recesses" and len(faces):
                inside = set(int(f) for f in faces)
                cleared = [f for f in face_overrides if f in inside]
                for face in cleared:
                    del face_overrides[face]
                log("  inspector clear  %-22s %5d override faces removed %s"
                    % (part, len(cleared), why))
                if cleared:
                    acted += 1
            elif action == "absorb_fragments" and len(faces):
                import scipy.sparse as sparse
                keep = max(1, int(finding.get("keep", 1)))
                inside = np.zeros(len(mesh.faces), dtype=bool)
                inside[faces] = True
                adjacency = mesh.face_adjacency
                both = inside[adjacency[:, 0]] & inside[adjacency[:, 1]]
                local = {int(f): i for i, f in enumerate(faces)}
                rows = [local[int(a)] for a, b in adjacency[both]]
                cols = [local[int(b)] for a, b in adjacency[both]]
                graph = sparse.coo_matrix(
                    (np.ones(len(rows)), (rows, cols)),
                    shape=(len(faces), len(faces)))
                n_comp, comp = sparse.csgraph.connected_components(
                    graph, directed=False)
                areas = np.asarray(mesh.area_faces)[faces]
                sizes = np.bincount(comp, weights=areas, minlength=n_comp)
                keepers = set(np.argsort(-sizes)[:keep])
                dissolved = 0
                for c in range(n_comp):
                    if c in keepers:
                        continue
                    members = faces[comp == c]
                    member_mask = np.zeros(len(mesh.faces), dtype=bool)
                    member_mask[members] = True
                    edge = (member_mask[adjacency[:, 0]]
                            ^ member_mask[adjacency[:, 1]])
                    outside = np.where(member_mask[adjacency[edge][:, 0]],
                                       adjacency[edge][:, 1],
                                       adjacency[edge][:, 0])
                    near = face_part[outside]
                    near = near[(near >= 0) & (near != label_id)]
                    if len(near):
                        face_part[members] = int(np.bincount(near).argmax())
                        dissolved += len(members)
                log("  inspector absorb %-22s kept %d, dissolved %d faces %s"
                    % (part, keep, dissolved, why))
                acted += 1
        for finding in findings:
            if finding.get("action") in ("repaint", "darken_recesses",
                                         "absorb_fragments",
                                         "clear_recesses", "relocate"):
                history.append("%s %s (%s)"
                               % (finding.get("action"),
                                  finding.get("part", ""),
                                  str(finding.get("why", ""))[:60]))
        report["rounds"].append({"verdict": verdict,
                                 "findings": len(findings),
                                 "acted": acted})
        log("inspector round %d: %s (%d findings, %d acted)"
            % (round_id, verdict[:90], len(findings), acted))
        if not acted:
            break
    return face_overrides, report
