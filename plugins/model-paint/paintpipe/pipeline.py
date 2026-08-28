"""The whole run, in the order the agents actually decide things.

    segment  -- 3D feature atoms: a cut of the persistence merge tree, whose
                boundaries are concave junctions and relief edges found in 3D
                (segment3d). Geometry only ever PROPOSES pieces here; it never
                names one.
    name     -- the vision agent reads shaded + numbered-id renders from many
                directions and says which atoms belong to which part; votes are
                fused statistically across views (patches.fuse_votes).
    descend  -- atoms whose votes straddle parts are split along their own
                sub-tree and re-asked. The tree makes "colour the sub-part" a
                descent, not a re-segmentation.
    refine   -- parts the vocabulary promised but nobody found get the recovery
                ladder: declared-parent zoom, locate-then-zoom, prune gate,
                design cut confirmed in context (refine.refine_subparts).
    paint    -- the painter colours the named parts unconstrained ("colour it
                beautifully"); only then is the scheme limited to the loaded
                filaments, and a critic reviews the finished renders and may
                override assignments (§10 before §11, always).
    export   -- painted 3MF whose geometry is verified identical to the input.

Where a constant appears it is a legibility or budget bound (how many ids fit
readably in one render, how many views to buy), never a boundary: every part
boundary comes from the merge tree, and every name from an agent looking at
renders. That is the division of labour the whole project converged on --
selection beats judgement, and geometry beats tiling.
"""

import json
import os
import time

import numpy as np


def default_log(message):
    print(message, flush=True)


def paint(input_path, out_dir, intent="", size_mm=None, palette=(),
          model="claude-opus-5", nozzle_mm=0.4, viewing_mm=500.0, pixels=900,
          cap=250, workers=3, no_vision=False, log=default_log):
    """One mesh and a brief in; a painted, geometry-identical 3MF out.

    Returns a manifest dict (also written to out_dir/scheme.json). With
    `no_vision` the run stops after segmentation with an atom atlas -- naming
    is an act of looking, and there is no honest deterministic stand-in for it.
    """
    import trimesh
    from . import entities, field as field_module, frame as frame_module
    from . import policy as policy_module, preview, segment3d, vision

    started = time.time()
    os.makedirs(out_dir, exist_ok=True)
    policy = policy_module.DEFAULT

    # -- frame: units, scale, validation. Repairs never move a vertex. --------
    source = trimesh.load(input_path, process=False, force="mesh")
    store = entities.Store(os.path.join(out_dir, "entities"))
    run = store.mint("run", params={"input": os.path.basename(input_path),
                                    "method": "3d-atoms"})
    frame = frame_module.build_frame(source, target_size_mm=size_mm)
    working = frame.working_mesh(source, store=store, inputs=[run])
    for check in frame.checks:
        if not check.passed:
            log("  validate %-18s %-9s %s"
                % (check.name, "repaired" if check.repaired else "FAILED",
                   check.detail))
    log("frame %s mm (%s)" % (frame.extent_mm.round(1).tolist(),
                              frame.size_source))

    field = field_module.LabelField(working, frame, policy, store=store,
                                    inputs=[run])
    mesh = field.substrate

    # -- segment in 3D --------------------------------------------------------
    face_atom, tree = segment3d.atoms(mesh, cap=cap, log=log)
    atom_count = len(tree["node_of_atom"])

    if no_vision:
        atlas_path = _atom_atlas(mesh, face_atom, atom_count, frame, out_dir,
                                 preview, preview.up_axis(frame))
        log("no vision: segmentation only -- %d atoms, atlas at %s"
            % (atom_count, atlas_path))
        store.write()
        return {"atoms": atom_count, "atlas": atlas_path, "painted": False}

    backend = vision.HeadlessBackend(os.path.join(out_dir, "vision"),
                                     model=model)

    # Which way is up is a fact about the depicted thing, not about the file's
    # axis convention -- so it is looked at, not assumed.
    up = _choose_up(mesh, frame, backend, intent=intent, log=log)

    # -- name the pieces ------------------------------------------------------
    # `intent` comes back enriched: the identity dossier studied before
    # naming rides inside it for every later stage as well.
    face_part, labels, vocabulary, naming, overviews, intent = _name_atoms(
        mesh, frame, face_atom, tree, atom_count, backend, intent, up,
        pixels=pixels, workers=workers, log=log)

    # -- second pass: recover what the vocabulary promised but nobody found ---
    from . import refine as refine_module
    face_part, recovered = refine_module.refine_subparts(
        mesh, face_part, labels, vocabulary, backend, intent, frame=frame,
        workers=workers, up=up)
    log("recovery: %s" % (json.dumps(recovered) if recovered
                          else "nothing missing"))

    # Every instance of every small part gets its own zoomed look; a refused
    # instance reverts to the label around it. The audit judges from model
    # distance, and at that distance a forehead can pass for an eye.
    face_part, refused = refine_module.verify_instances(
        mesh, face_part, labels, backend, intent, frame, up=up,
        workers=workers, log=log)
    if refused:
        recovered = dict(recovered or {})
        recovered["_instances_refused"] = refused

    # Boundaries that follow creases stay; boundaries scribbled across smooth
    # skin straighten. Two contrasting filaments meeting on a staircase edge
    # is what jagged paint looks like on the print.
    from . import consensus as consensus_module
    before = int((face_part[mesh.face_adjacency[:, 0]]
                  != face_part[mesh.face_adjacency[:, 1]]).sum())
    face_part = consensus_module.smooth_boundaries(mesh, face_part)
    after = int((face_part[mesh.face_adjacency[:, 0]]
                 != face_part[mesh.face_adjacency[:, 1]]).sum())
    log("boundary relax: %d -> %d boundary edges" % (before, after))

    # A thin blade -- a fin, an ear, a frill -- is one thing: both sides and
    # the rim wear one label.
    face_part = consensus_module.unify_blades(mesh, face_part, log=log)

    settled, claimed, rows = _settle(field, mesh, face_part, labels, log=log)
    _part_atlas(mesh, settled, claimed, labels, frame, out_dir, preview, up)

    # -- paint: unconstrained first, then the printer's reality ---------------
    manifest = _paint_and_export(
        input_path, out_dir, mesh, frame, face_part, labels, vocabulary,
        palette, backend, intent, nozzle_mm, viewing_mm, up=up,
        overviews=overviews, log=log)
    manifest["up_axis"] = [round(float(v), 6) for v in up]

    manifest.update({"atoms": atom_count, "naming": naming,
                     "recovered": recovered, "isolation": rows,
                     "vocabulary": vocabulary,
                     "seconds": round(time.time() - started, 1),
                     "vision_calls": backend.calls,
                     "vision_cost_usd": round(backend.cost_usd, 3)})
    np.savez_compressed(os.path.join(out_dir, "parts.npz"),
                        face_part=face_part, settled=settled, claimed=claimed,
                        labels=np.array(labels, dtype=object))
    store.write()
    with open(os.path.join(out_dir, "scheme.json"), "w") as handle:
        json.dump(entities._plain(manifest), handle, indent=2, default=str)
    log("\ndone in %.0fs, vision $%.2f -- %s"
        % (manifest["seconds"], backend.cost_usd, out_dir))
    return manifest


def repaint(input_path, out_dir, palette, overrides, size_mm=None,
            log=default_log):
    """Re-map finished parts to filaments without re-running any vision.

    `overrides` is {part label: filament name}. Loads parts.npz and scheme.json
    from a previous run in `out_dir`, applies the changes, re-renders the final
    views and re-exports the verified 3MF. This is what "make the eyes black"
    costs after a run: seconds, not a re-segmentation.
    """
    import trimesh
    from PIL import Image
    from . import entities, field as field_module, frame as frame_module
    from . import policy as policy_module, preview

    saved = np.load(os.path.join(out_dir, "parts.npz"), allow_pickle=True)
    face_part = saved["face_part"]
    labels = [str(label) for label in saved["labels"]]
    with open(os.path.join(out_dir, "scheme.json")) as handle:
        manifest = json.load(handle)
    filaments = dict(manifest.get("filaments", {}))
    by_name = {paint_choice.name: paint_choice for paint_choice in palette}
    for part, name in overrides.items():
        if part not in labels:
            raise SystemExit("no part named %r; parts are %s" % (part, labels))
        if name not in by_name:
            raise SystemExit("no filament named %r; loaded: %s"
                             % (name, sorted(by_name)))
        log("repaint %-24s -> %s" % (part, name))
        filaments[part] = name
    # Stored assignments must resolve against the palette just as strictly as
    # explicit overrides do: silently dropping one would repaint a part the
    # user never asked about with the body filament.
    stale = sorted({name for name in filaments.values() if name not in by_name})
    if stale:
        raise SystemExit(
            "the saved run uses filament(s) %s but --colors loaded %s; pass "
            "the same filament names as the original run (or include the old "
            "names) so unchanged parts keep their colour" % (stale,
                                                             sorted(by_name)))
    chosen = {part: by_name[name] for part, name in filaments.items()}

    source = trimesh.load(input_path, process=False, force="mesh")
    frame = frame_module.build_frame(source, target_size_mm=size_mm)
    working = frame.working_mesh(source, store=entities.Store(
        os.path.join(out_dir, "entities")))
    field = field_module.LabelField(working, frame, policy_module.DEFAULT)
    mesh = field.substrate
    up = np.asarray(manifest.get("up_axis") or preview.up_axis(frame),
                    dtype=float)
    occlusion = preview.ambient_occlusion(mesh, samples=40)
    table = np.array([chosen[label].lab if label in chosen
                      else palette[-1].lab for label in labels])
    lab = np.tile(np.asarray(palette[-1].lab, dtype=float),
                  (len(face_part), 1))
    painted_faces = face_part >= 0
    lab[painted_faces] = table[face_part[painted_faces]]
    rgb = preview.lab_to_srgb(lab)
    preview.contact_sheet(mesh, rgb, preview.orbit(8, 18.0, up=up), size=470,
                          occlusion=occlusion, columns=4, up=up).save(
        os.path.join(out_dir, "final-turnaround.png"))
    Image.fromarray(preview.render_asset(
        mesh, rgb, preview.orbit(1, 24.0, start_deg=200.0, up=up)[0],
        size=950, occlusion=occlusion, up=up, zoom=1.25)).save(
        os.path.join(out_dir, "final-hero.png"))

    export = _export_3mf(input_path, out_dir, face_part, labels, chosen,
                         palette, log=log)
    manifest["filaments"] = filaments
    manifest["export"] = export
    with open(os.path.join(out_dir, "scheme.json"), "w") as handle:
        json.dump(manifest, handle, indent=2, default=str)
    return manifest


UP_PROMPT = """Renders of the SAME 3D model, each numbered in its top-left \
corner, each assuming a different up direction. In exactly one of them the \
model sits the way it would actually stand or display: base at the bottom, \
not tipped on its side or upside down.

What the piece is: %s

Use the anatomy of what is depicted -- a head's chin is below its brow, an \
animal stands on its feet, horns and ears point up.

Reply with ONLY a JSON object, no prose, no code fences:
{"upright": <the number>, "why": "<one line>"}"""


def _choose_up(mesh, frame, backend, intent="", log=default_log):
    """Ask the agent which orientation is upright, instead of trusting the
    file's axis convention (STLs converted from Y-up sources lie about it)."""
    from PIL import Image, ImageDraw
    from . import entities, preview

    prior = np.asarray(preview.up_axis(frame), dtype=float)
    candidates = [prior]
    for axis in ([0.0, 0.0, 1.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0],
                 [0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]):
        vector = np.asarray(axis)
        if all(np.linalg.norm(vector - known) > 1e-6 for known in candidates):
            candidates.append(vector)

    neutral = np.tile(np.array([64.0, 1.0, 2.0]), (len(mesh.vertices), 1))
    rgb = preview.face_colours(mesh, neutral)
    paths, blobs = [], []
    for index, candidate in enumerate(candidates):
        # Two azimuths per candidate: one view of a symmetric model can look
        # plausible under an inverted up, and this one decision poisons every
        # downstream judgement if it lands wrong.
        tiles = [preview.render_asset(mesh, rgb, direction, size=380,
                                      up=candidate)
                 for direction in (preview.orbit(1, 18.0, start_deg=200.0,
                                                 up=candidate)[0],
                                   preview.orbit(1, 18.0, start_deg=90.0,
                                                 up=candidate)[0])]
        image = Image.fromarray(np.concatenate(tiles, axis=1))
        ImageDraw.Draw(image).text((8, 6), str(index), fill=(0, 0, 0))
        path = os.path.join(backend.directory, "up-%d.png" % index)
        image.save(path)
        paths.append(path)
        with open(path, "rb") as handle:
            blobs.append(handle.read())
    prompt = UP_PROMPT % (intent or "not stated")
    key = "up-%s" % entities.digest_of(b"".join(blobs)
                                       + intent.encode("utf-8"))[7:19]
    answer = backend._run(paths, prompt, key) or {}
    try:
        pick = int(answer.get("upright", 0))
    except (TypeError, ValueError):
        pick = 0
    if not 0 <= pick < len(candidates):
        pick = 0
    chosen = candidates[pick]
    log("up axis: %s%s -- %s"
        % (np.round(chosen, 3).tolist(),
           "" if pick == 0 else " (file convention said %s)"
           % np.round(prior, 3).tolist(),
           str(answer.get("why", "no answer; kept the file convention"))[:70]))
    return chosen


def _name_atoms(mesh, frame, face_atom, tree, atom_count, backend, intent, up,
                pixels=900, workers=3, log=default_log):
    """Vocabulary, per-view votes, statistical fusion, contested descent."""
    from concurrent.futures import ThreadPoolExecutor
    from . import patches, preview, render as render_module, segment3d, vision

    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.05

    # The vocabulary is anatomy, and anatomy is read from upright, eye-level
    # views -- five arbitrary directions let the ogre's chin folds pass for a
    # face because no overview ever showed the real one straight on.
    overview_directions = (preview.orbit(4, 4.0, up=up)
                           + preview.orbit(2, 45.0, start_deg=45.0, up=up))
    overviews = [vision.render_png(render_module.render_bundle(
        mesh, render_module.Camera(np.asarray(d, float), up, centre, radius,
                                   640),
        "zenithal", frame)) for d in overview_directions]
    # WHAT IS THIS THING -- studied once, deeply, before any part is named.
    # The dossier's identity and its cautions about look-alike traps travel
    # inside every downstream ask, so the labeller that meets the ogre's
    # chin folds has already been told they are not a face.
    dossier = backend.describe(overviews, intent)
    if dossier.get("identity"):
        log("identity: %s" % dossier["identity"])
    if dossier.get("cautions"):
        log("cautions: %s" % dossier["cautions"])
    briefing = intent or ""
    if dossier.get("identity"):
        briefing += "\n\nWhat this piece is (studied): %s" % dossier["identity"]
    for landmark in dossier.get("landmarks", []) or []:
        briefing += "\n- %s: %s" % (landmark.get("what", ""),
                                    landmark.get("where", ""))
    if dossier.get("cautions"):
        briefing += "\nCautions: %s" % dossier["cautions"]
    intent = briefing.strip() or intent

    vocabulary = backend.vocabulary(overviews, intent)
    labels = [part["label"] for part in vocabulary]
    # Ask keys carry the full question state -- view geometry AND the
    # vocabulary being assigned. Replaying an old run's answers against a new
    # part list silently drops the votes for every renamed part.
    from . import entities
    view_state = entities.digest_of({"up": np.round(np.asarray(up), 4).tolist(),
                                     "pixels": int(pixels),
                                     "camera": "up-hinted-batch3",
                                     "labels": labels})[7:13]
    if not labels:
        # The backend returns [] on any failed call. Stop before spending a
        # dozen naming views on a run that can only end in an empty argmax.
        raise SystemExit(
            "the vision backend returned no part vocabulary -- the headless "
            "call failed (see %s for the failure record); nothing to name"
            % backend.directory)
    log("parts %s" % labels)

    def _render_view(camera, atom_map, count, only=None):
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        shaded = vision.render_png(bundle)
        lit = np.clip(bundle["rgb_lit"], 0, 1)
        id_png, listed = patches.render_id_view(mesh, atom_map, count, camera,
                                                lit, only=only)
        return shaded, id_png, listed

    def batched_votes(camera_list, atom_map, count, tag, only=None):
        # A call is the unit of latency; three views share one. The judgement
        # per view is unchanged -- ids stay scoped to their own id render.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rendered = list(pool.map(
                lambda c: _render_view(c, atom_map, count, only=only),
                camera_list))
        chunks = [rendered[i:i + 3] for i in range(0, len(rendered), 3)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            answers = list(pool.map(
                lambda pair: patches.ask_assignments_batch(
                    backend, pair[1], vocabulary, intent,
                    "%s-b%02d" % (tag, pair[0])),
                enumerate(chunks)))
        rounds_out = []
        for chunk_votes in answers:
            for votes in chunk_votes:
                log("  %s: %d parts, %d votes"
                    % (tag, len(votes),
                       sum(len(v) for v in votes.values())))
                rounds_out.append((votes, 1.0))
        return rounds_out

    # Three elevation rings so undersides and crowns are looked at, not
    # inferred. The counts are a view budget, not a boundary.
    directions = (preview.orbit(6, 18.0, up=up) + preview.orbit(3, 55.0, up=up)
                  + preview.orbit(3, -20.0, up=up))
    cameras = [render_module.Camera(np.asarray(d, float), up, centre,
                                    radius, pixels) for d in directions]
    rounds = batched_votes(cameras, face_atom, atom_count,
                           "name-%s" % view_state)
    assigned, votes = patches.fuse_votes(rounds, atom_count, labels)
    log("voted: %d/%d atoms" % (int((assigned >= 0).sum()), atom_count))

    # Contested descent: an atom whose votes straddle parts is split along its
    # own sub-tree and the sub-atoms are re-asked with their ids highlighted.
    top = votes.max(axis=1)
    second = (np.partition(votes, -2, axis=1)[:, -2]
              if votes.shape[1] >= 2 else 0 * top)
    contested = np.flatnonzero((top > 0) & ((top - second) < 0.6 * top))
    log("contested atoms: %d" % len(contested))
    parent_of = {}
    atom_map, count = face_atom, atom_count
    votes2 = None
    if len(contested):
        new_map = face_atom.copy()
        next_id = atom_count
        new_ids = []
        for atom in contested:
            subs = segment3d.descend(tree, int(atom), max_children=12)
            if len(subs) < 2:
                continue
            for _sub, faces in subs.items():
                keep = faces[face_atom[faces] == atom]
                if len(keep) < 20:
                    continue
                new_map[keep] = next_id
                parent_of[next_id] = int(atom)
                new_ids.append(next_id)
                next_id += 1
        if new_ids:
            log("descended into %d sub-atoms" % len(new_ids))
            cameras2 = [render_module.Camera(np.asarray(d, float), up,
                                             centre, radius, pixels)
                        for d in preview.orbit(6, 30.0, start_deg=15.0,
                                               up=up)]
            rounds2 = batched_votes(cameras2, new_map, next_id,
                                    "sub-%s" % view_state,
                                    only=set(new_ids))
            _assigned2, votes2 = patches.fuse_votes(rounds2, next_id, labels)
            count, atom_map = next_id, new_map

    # Labels move a whole atom at a time from here on: every boundary in the
    # result is an atom boundary, and atom boundaries are the 3D tree's own.
    # (The old face-by-face flood raced label fronts across part boundaries
    # and drew jagged bleed through features; consensus.py is its replacement.)
    from . import consensus
    votes_all = np.zeros((count, len(labels)))
    votes_all[:votes.shape[0]] = votes
    if votes2 is not None:
        votes_all += votes2
    weights = consensus.boundary_weights(mesh, atom_map, count)
    voted = votes_all.sum(axis=1) > 0
    assigned = np.where(voted, np.argmax(votes_all, axis=1),
                        -1).astype(np.int32)
    assigned = consensus.fill(assigned, weights, len(labels))
    assigned = consensus.smooth(assigned, votes_all, weights)

    # The agent inspects the coloured assignment and corrects it -- missed
    # instances, one-sided pairs, features split between colours -- until it
    # has nothing left to fix.
    assigned, votes_all, audit_history = consensus.audit(
        mesh, frame, backend, atom_map, count, assigned, votes_all, labels,
        vocabulary, intent, up, weights, pixels=pixels, workers=workers,
        log=log)

    # Corrections are immune to smoothing on purpose, so a stray one leaves a
    # confident satellite; absorb fragments that are slivers next to their own
    # label's real component.
    valid = atom_map >= 0
    atom_area = np.bincount(atom_map[valid],
                            weights=np.asarray(mesh.area_faces)[valid],
                            minlength=count)
    assigned = consensus.absorb_islands(assigned, weights, atom_area,
                                        len(labels), log=log)

    # An atom nothing could reach or correct keeps its contested parent's top
    # vote; anything still unlabelled stays honestly unpainted.
    still = np.flatnonzero(assigned < 0)
    if len(still) and parent_of:
        parent_top = np.argmax(votes, axis=1)
        for atom in still:
            parent = parent_of.get(int(atom))
            if parent is not None and votes[parent].max() > 0:
                assigned[atom] = parent_top[parent]
    face_part = np.where(assigned[atom_map] >= 0, assigned[atom_map],
                         -1).astype(np.int32)

    naming = {"views": len(cameras), "contested": int(len(contested)),
              "voted_atoms": int((assigned >= 0).sum()), "atoms": int(count),
              "audit_corrections": audit_history}
    return face_part, labels, vocabulary, naming, overviews, intent


def _settle(field, mesh, face_part, labels, log=default_log):
    """Faces to vertices by vote, then the isolation report -- the objective
    misclassification metric: a cleanly found part is one or a few pieces."""
    from . import atlas
    votes = np.zeros((len(mesh.vertices), len(labels)))
    for column in range(3):
        vertex = mesh.faces[:, column]
        ok = face_part >= 0
        np.add.at(votes, (vertex[ok], face_part[ok]), 1.0)
    claimed = votes.sum(axis=1) > 0
    settled = np.where(claimed, np.argmax(votes, axis=1), 0).astype(np.int32)
    rows = atlas.isolation_report(field, settled, claimed, labels)
    log("\n%-26s %7s %7s %8s" % ("PART", "AREA%", "PIECES", "LARGEST%"))
    for row in sorted(rows, key=lambda r: -r["area_pct"]):
        log("%-26s %7.2f %7d %8.1f" % (row["part"], row["area_pct"],
                                       row["pieces"],
                                       row["largest_piece_pct"]))
    return settled, claimed, rows


def _atom_atlas(mesh, face_atom, count, frame, out_dir, preview, up):
    from . import atlas
    table = np.array([atlas.DISTINCT[i % len(atlas.DISTINCT)]
                      for i in range(max(count, 1))])
    face_rgb = np.tile(np.asarray(atlas.NEUTRAL), (len(face_atom), 1))
    labelled = face_atom >= 0
    face_rgb[labelled] = table[face_atom[labelled]]
    occlusion = preview.ambient_occlusion(mesh, samples=30)
    path = os.path.join(out_dir, "atoms.png")
    preview.contact_sheet(mesh, face_rgb, preview.orbit(4, 18.0, up=up),
                          size=470, occlusion=occlusion, columns=4, up=up).save(path)
    return path


def _part_atlas(mesh, settled, claimed, labels, frame, out_dir, preview, up):
    from . import atlas
    colours, _ = atlas.colour_by_part(settled, claimed, labels)
    occlusion = preview.ambient_occlusion(mesh, samples=30)
    preview.contact_sheet(mesh, colours[mesh.faces].mean(axis=1),
                          preview.orbit(4, 18.0, up=up), size=470,
                          occlusion=occlusion, columns=4, up=up).save(
        os.path.join(out_dir, "atlas.png"))


def _paint_and_export(input_path, out_dir, mesh, frame, face_part, labels,
                      vocabulary, palette, backend, intent, nozzle_mm,
                      viewing_mm, up=None, overviews=(), log=default_log):
    """§10 then §11: beautiful first, then limited; critic last; then the 3MF."""
    from types import SimpleNamespace
    from PIL import Image
    from . import agents, limiter, policy as policy_module, preview
    from . import refine as refine_module

    policy = policy_module.DEFAULT
    if up is None:
        up = preview.up_axis(frame)
    occlusion = preview.ambient_occlusion(mesh, samples=40)

    # Colours commit per FACE from the atom-crisp face_part -- never through a
    # per-vertex argmax, which softened and shifted every part boundary by a
    # vertex ring. What the renders show is exactly what the export paints.
    def face_lab(table, default_lab):
        out = np.tile(np.asarray(default_lab, dtype=float),
                      (len(face_part), 1))
        painted = face_part >= 0
        out[painted] = np.asarray(table, dtype=float)[face_part[painted]]
        return out

    def write(lab_per_face, stem):
        rgb = preview.lab_to_srgb(lab_per_face)
        preview.contact_sheet(mesh, rgb, preview.orbit(8, 18.0, up=up),
                              size=470, occlusion=occlusion, columns=4, up=up).save(
            os.path.join(out_dir, "%s-turnaround.png" % stem))
        Image.fromarray(preview.render_asset(
            mesh, rgb, preview.orbit(1, 24.0, start_deg=200.0, up=up)[0],
            size=950, occlusion=occlusion, up=up, zoom=1.25)).save(
            os.path.join(out_dir, "%s-hero.png" % stem))

    painter = agents.VisionPainter(backend)
    holder = SimpleNamespace(labels=labels)
    scheme = painter.colour(holder, labels, 3.0, intent, vocabulary=vocabulary,
                            overviews=list(overviews))
    log("\ncontinuous colour")
    for entry in scheme:
        log("  %-24s %-8s %-10s" % (entry["region"], entry.get("hex", ""),
                                    entry["role"]))
    order = {entry["region"]: i for i, entry in enumerate(scheme)}
    wanted = np.array([scheme[order[label]]["lab"] for label in labels])
    # The unlimited stage shades WITHIN parts the way a painter would: recesses
    # sink toward each part's shade colour, upward crests catch its highlight.
    # Flat unlimited colour was a contradiction -- infinite palette spent at
    # part granularity.
    shade = np.array([scheme[order[label]].get("shade_lab",
                                               scheme[order[label]]["lab"])
                      for label in labels])
    highlight = np.array([scheme[order[label]].get("highlight_lab",
                                                   scheme[order[label]]["lab"])
                          for label in labels])
    from . import consensus as consensus_module

    def bake_continuous():
        order_now = {entry["region"]: i for i, entry in enumerate(scheme)}
        base_table = np.array([scheme[order_now[label]]["lab"]
                               for label in labels])
        shade_table = np.array([scheme[order_now[label]].get(
            "shade_lab", scheme[order_now[label]]["lab"]) for label in labels])
        light_table = np.array([scheme[order_now[label]].get(
            "highlight_lab", scheme[order_now[label]]["lab"])
            for label in labels])
        baked = face_lab(base_table, [64.0, 1.0, 2.0])
        painted_faces = face_part >= 0
        if painted_faces.any():
            sink = np.clip(1.0 - occlusion[painted_faces], 0.0, 1.0)[:, None]
            lift = np.clip(mesh.face_normals[painted_faces]
                           @ (np.asarray(up, dtype=float)
                              / max(np.linalg.norm(up), 1e-12)),
                           0.0, 1.0)[:, None]
            parts_here = face_part[painted_faces]
            base_here = baked[painted_faces]
            baked[painted_faces] = (
                base_here
                + (shade_table[parts_here] - base_here) * 0.65 * sink
                + (light_table[parts_here] - base_here) * 0.45 * lift)
        return consensus_module.feather_lab(mesh, baked, face_part)

    write(bake_continuous(), "continuous")
    log("wrote continuous-turnaround.png, continuous-hero.png")

    # THE DESIGN MUST STAND ON ITS OWN before any filament exists: a critic
    # reviews the continuous renders as a painted asset and adjusts colours;
    # only a design worth having gets limited.
    design_changes, design_verdict = refine_module.review_continuous(
        backend, [os.path.join(out_dir, "continuous-hero.png"),
                  os.path.join(out_dir, "continuous-turnaround.png")],
        scheme, intent)
    if design_verdict:
        log("design critic: %s" % design_verdict)
    if design_changes:
        log("design critic adjusted %d part(s); re-baking continuous"
            % design_changes)
        write(bake_continuous(), "continuous")

    if not palette:
        log("no filaments given: design only, not a plan")
        return {"regions": scheme, "painted": False}

    areas = np.asarray(mesh.area_faces, dtype=float)
    share = {label: float(areas[face_part == i].sum())
             for i, label in enumerate(labels)}
    for entry in scheme:
        entry["area_mm2"] = round(max(share.get(entry["region"], 0.0), 1.0), 2)
    adjacency = mesh.face_adjacency
    a, b = face_part[adjacency[:, 0]], face_part[adjacency[:, 1]]
    both = (a >= 0) & (b >= 0) & (a != b)
    pairs = np.unique(np.stack([np.minimum(a[both], b[both]),
                                np.maximum(a[both], b[both])], axis=1), axis=0)
    touching = [(labels[int(x)], labels[int(y)]) for x, y in pairs]
    chosen, clashes = limiter.assign_paints(scheme, list(palette), touching,
                                            policy, viewing_mm, areas=share)
    log("\nlimited to %d filament(s)" % len(palette))
    for entry in scheme:
        paint_choice = chosen[entry["region"]]
        log("  %-24s %-8s -> %-8s dE %5.1f"
            % (entry["region"], entry.get("hex", ""), paint_choice.name,
               limiter.delta_e(entry["lab"], paint_choice.lab)))
    if clashes:
        log("  boundaries the palette cannot separate: %s" % clashes)

    def limited_lab():
        table = [chosen[label].lab if label in chosen else palette[-1].lab
                 for label in labels]
        return face_lab(table, palette[-1].lab)

    write(limited_lab(), "limited")
    zero_faced = {row_label for i, row_label in enumerate(labels)
                  if share.get(row_label, 0.0) <= 0.0}
    overrides, verdict = refine_module.review_scheme(
        backend, [os.path.join(out_dir, "limited-hero.png"),
                  os.path.join(out_dir, "limited-turnaround.png")],
        scheme, chosen, list(palette), intent)
    if verdict:
        log("\ncritic: %s" % verdict)
    for part, (paint_choice, why) in overrides.items():
        marker = " [NO FACES -- override is a no-op]" if part in zero_faced \
            else ""
        log("  override %-24s -> %-7s %s%s" % (part, paint_choice.name,
                                               why[:60], marker))
        chosen[part] = paint_choice

    # MATERIAL TRUTH, enforced. A bald crown is the same skin as the cheeks;
    # a recess in skin is still skin. Non-accent parts sharing a material
    # adopt the material's area-majority filament, whatever aesthetic
    # arguments upstream tried -- restraint is the look, and shadow does the
    # separating. Accent-role parts (an iris, teeth) keep their own colour.
    material_of = {part.get("label"): (part.get("material") or "").strip()
                   for part in vocabulary or []}
    role_of = {entry["region"]: entry.get("role", "") for entry in scheme}
    groups = {}
    for label in labels:
        material = material_of.get(label, "")
        if material and role_of.get(label) != "accent":
            groups.setdefault(material, []).append(label)
    for material, members in groups.items():
        if len(members) < 2:
            continue
        weight = {}
        for label in members:
            if label in chosen:
                name = chosen[label].name
                weight[name] = weight.get(name, 0.0) + share.get(label, 0.0)
        if not weight:
            continue
        majority = max(weight, key=weight.get)
        paint_majority = next(p for p in palette if p.name == majority)
        for label in members:
            if label in chosen and chosen[label].name != majority:
                log("  material %-10s %-24s %s -> %s"
                    % (material, label, chosen[label].name, majority))
                chosen[label] = paint_majority
    write(limited_lab(), "final")
    log("wrote final-turnaround.png, final-hero.png")

    export = _export_3mf(input_path, out_dir, face_part, labels, chosen,
                         palette, log=log)
    return {"regions": [{k: v for k, v in entry.items() if k != "actor"}
                        for entry in scheme],
            "filaments": {entry["region"]: chosen[entry["region"]].name
                          for entry in scheme},
            "unseparated": clashes, "critic": verdict,
            "overrides": {part: paint_choice.name
                          for part, (paint_choice, _w) in overrides.items()},
            "export": export, "painted": True}


def _export_3mf(input_path, out_dir, face_part, labels, chosen, palette,
                log=default_log):
    """Write the painted 3MF and verify the geometry never moved."""
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts = os.path.join(here, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        from paintlib import build as builder, orca, threemf
    except ImportError:
        log("3MF writer unavailable; skipping export")
        return {"written": False}

    base = os.path.join(out_dir, "base.3mf")
    painted = os.path.join(out_dir, "painted.3mf")
    builder.from_stl(input_path, base,
                     name=os.path.splitext(os.path.basename(input_path))[0])

    slot = {paint_choice.name: i + 1 for i, paint_choice in enumerate(palette)}
    default = slot[palette[-1].name]
    assignments = {}
    for face, part in enumerate(face_part):
        if part < 0:
            continue
        label = labels[int(part)]
        filament = slot[chosen[label].name] if label in chosen else default
        if filament != default:
            assignments[face] = filament

    archive = threemf.ThreeMF(base)
    archive.paint_object(archive.mesh_objects()[0], assignments)
    orca.set_filaments(
        archive,
        [{"index": i + 1, "name": paint_choice.name,
          "hex": _to_hex(paint_choice.lab)}
         for i, paint_choice in enumerate(palette)],
        default_filament=default)
    archive.save(painted)

    ok, why = threemf.geometry_matches(base, painted)
    log("\n3MF %s -- %s" % ("IDENTICAL" if ok else "DIFFERS", why))
    return {"written": True, "path": painted, "geometry_identical": bool(ok),
            "detail": why}


def _to_hex(lab):
    from colour import Lab_to_XYZ, XYZ_to_sRGB
    rgb = np.clip(XYZ_to_sRGB(Lab_to_XYZ(np.asarray(lab, dtype=float))), 0, 1)
    return "#%02X%02X%02X" % tuple(int(round(v * 255)) for v in rgb)
