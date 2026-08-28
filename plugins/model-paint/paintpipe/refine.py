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
                    frame=None, views=4, pixels=760, workers=3, up=(0, 0, 1)):
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
    notes_all = {part["label"]: part.get("note", "") for part in vocabulary or []}

    report = {}
    notes = {part["label"]: part.get("note", "") for part in vocabulary or []}
    adjacency = mesh.face_adjacency

    # Each parent's recovery is vision-bound and independent of the others, so
    # the render/ask/confirm work fans out across a pool; only the final splice
    # into face_part happens serially, so two parents can never race a face.
    def _recover_parent(parent, children):
        host_faces = np.flatnonzero(face_part == index[parent])
        if len(host_faces) < 50:
            return None
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
            camera = render_module.Camera(-direction, up, centre, radius, pixels)
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
        confirmed, rejected = {}, {}
        for child, local_faces in moved.items():
            ok = _confirm_claim(backend, sub, local_faces, child, intent, centre,
                                radius, pixels, frame, up=up)
            if ok:
                confirmed[child] = [int(parent_faces[f]) for f in local_faces]
            else:
                rejected[child] = len(local_faces)
        return parent, confirmed, rejected

    from concurrent.futures import ThreadPoolExecutor
    if by_parent:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda item: _recover_parent(*item),
                                    by_parent.items()))
        for result in results:
            if result is None:
                continue
            parent, confirmed, rejected = result
            recovered = {}
            for child, global_faces in confirmed.items():
                for face in global_faces:
                    face_part[face] = index[child]
                recovered[child] = len(global_faces)
            for child, dropped in rejected.items():
                report.setdefault("_rejected", {})[child] = dropped
            report[parent] = recovered
    # LOCATE-THEN-ZOOM IS ROUTED BY FAILURE, NOT BY PEDIGREE. The first wiring sent
    # only "orphans" -- parts with no usable declared parent -- through it, and on
    # three CC0 models that set was empty: the tail, eyes, lips and tusks all HAD
    # declared parents with area (`body`, `lips and mouth`). They took the declared
    # path, which cannot work when the parent is most of the model or does not contain
    # the anatomy, and the locator never fired at all. Whatever a part's pedigree,
    # if it is still empty after the hierarchy pass, it gets pointed at.
    interim = np.bincount(face_part[face_part >= 0], minlength=len(labels))
    still = [label for label in empty if interim[index[label]] == 0]
    if still:
        located = locate_missing(backend, mesh, frame, still, intent, notes_all,
                                 up=up)
        if located:
            face_part, located_report = recover_located(
                mesh, face_part, labels, backend, intent, frame, located,
                notes_all, workers=workers, up=up)
            report["_located"] = located_report
        skipped = [label for label in still if label not in located]
        if skipped:
            report["_not_located"] = skipped
    # PAIR COMPLETION. The vocabulary says how many instances anatomy has;
    # a paired part with one found instance is a miss the coarse pass cannot
    # see. The locator is pointed at the OTHER instance specifically.
    expected = {part.get("label"): part.get("expected_count")
                for part in vocabulary or []}
    import scipy.sparse as _sparse
    for label, want in expected.items():
        if not want or want < 2 or label not in index:
            continue
        faces_here = np.flatnonzero(face_part == index[label])
        if len(faces_here) < 20:
            continue
        inside = np.zeros(len(mesh.faces), dtype=bool)
        inside[faces_here] = True
        both = inside[adjacency[:, 0]] & inside[adjacency[:, 1]]
        local = {int(f): i for i, f in enumerate(faces_here)}
        rows_l = [local[int(a)] for a, b in adjacency[both]]
        cols_l = [local[int(b)] for a, b in adjacency[both]]
        graph = _sparse.coo_matrix((np.ones(len(rows_l)), (rows_l, cols_l)),
                                   shape=(len(faces_here), len(faces_here)))
        n_comp, _comp = _sparse.csgraph.connected_components(graph,
                                                             directed=False)
        if n_comp >= want:
            continue
        missing_note = ("another %s -- %d of the %d instances you yourself "
                        "counted in the overviews are already labelled; box "
                        "only one you can actually SEE that is not labelled. "
                        "If your count was wrong and there are no more, skip "
                        "this part -- that is a correct answer" %
                        (label, n_comp, want))
        located = locate_missing(backend, mesh, frame, [label], intent,
                                 {label: missing_note}, up=up)
        if located:
            face_part, pair_report = recover_located(
                mesh, face_part, labels, backend, intent, frame, located,
                {label: missing_note}, workers=workers, up=up)
            report.setdefault("_pair_completion", {})[label] = pair_report

    # Loud failure beats a quiet wrong answer: name every part still empty.
    final_areas = np.bincount(face_part[face_part >= 0], minlength=len(labels))
    for label in labels:
        if final_areas[index[label]] == 0:
            report.setdefault("_failed", []).append(label)
    return face_part, report


def verify_instances(mesh, face_part, labels, backend, intent, frame,
                     up=(0, 0, 1), max_checks=40, pixels=760, workers=3,
                     log=print):
    """Zoom onto instances and ask if they are real -- selected RELATIVELY.

    The audit judges whole-model views, and at that distance a forehead plane
    can pass for an eye-white -- the cyclops ogre got two extra "eyes" above
    its brow that no close look would ever confirm. Each suspicious connected
    instance gets its own zoomed, in-context look; a refused instance reverts
    to the label that surrounds it.

    Nothing here is an absolute size. An instance is suspect because it is an
    OUTLIER AGAINST ITS OWN LABEL'S PEERS: hooves come four to a cow and all
    four are the same size, so a fifth "hoof" three times the median is the
    one to look at. Peer-consistent sets are sampled (largest and smallest
    stand for the set; if either fails, the rest are checked too). The one
    absolute number is `max_checks`, a spend budget, not a size claim.
    """
    import scipy.sparse as sparse
    from concurrent.futures import ThreadPoolExecutor

    areas = np.asarray(mesh.area_faces, dtype=float)
    adjacency = mesh.face_adjacency
    centres = mesh.triangles.mean(axis=1)
    extent = float(np.linalg.norm(np.ptp(mesh.vertices, axis=0)))
    suspects, representatives, peers_of = [], [], {}
    for label_id, label in enumerate(labels):
        faces = np.flatnonzero(face_part == label_id)
        if not len(faces):
            continue
        inside = np.zeros(len(mesh.faces), dtype=bool)
        inside[faces] = True
        both = inside[adjacency[:, 0]] & inside[adjacency[:, 1]]
        local = {int(f): i for i, f in enumerate(faces)}
        rows = [local[int(a)] for a, b in adjacency[both]]
        cols = [local[int(b)] for a, b in adjacency[both]]
        graph = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)),
                                  shape=(len(faces), len(faces)))
        count, component = sparse.csgraph.connected_components(graph,
                                                               directed=False)
        comp_area = np.bincount(component, weights=areas[faces],
                                minlength=count)
        median = float(np.median(comp_area[comp_area > 0]))
        label_total = float(comp_area.sum())
        members_of = {comp: faces[component == comp] for comp in range(count)}
        peer_ids, outlier_ids = [], []
        for comp in range(count):
            if comp_area[comp] <= 0:
                continue
            # The label's dominant body is the consensus stage's business,
            # and slivers are absorption's; instances in between are the
            # verifier's. Both bounds are relative to the label itself.
            if comp_area[comp] >= 0.8 * label_total:
                continue
            if comp_area[comp] < 0.02 * median:
                continue
            if 0.3 * median <= comp_area[comp] <= 3.0 * median:
                peer_ids.append(comp)
            else:
                outlier_ids.append(comp)
        for comp in outlier_ids:
            suspects.append((label_id, label, members_of[comp]))
        if len(peer_ids) <= 2:
            for comp in peer_ids:
                suspects.append((label_id, label, members_of[comp]))
        else:
            ordered = sorted(peer_ids, key=lambda c: -comp_area[c])
            for comp in (ordered[0], ordered[-1]):
                representatives.append((label_id, label, members_of[comp]))
            peers_of[label_id] = [members_of[comp] for comp in ordered[1:-1]]

    def check(label_id, label, members):
        # A refused instance must be RE-IDENTIFIED, not dumped on a
        # neighbour: binary refusal plus mechanical reassignment swapped the
        # ogre's horns and ears into each other and dropped a third of its
        # hide into "ears". The reviewer picks from the labels actually
        # present around the instance, or says none.
        inside = np.zeros(len(mesh.faces), dtype=bool)
        inside[members] = True
        edge = inside[adjacency[:, 0]] ^ inside[adjacency[:, 1]]
        outside = np.where(inside[adjacency[edge][:, 0]],
                           adjacency[edge][:, 1], adjacency[edge][:, 0])
        neighbours = face_part[outside]
        neighbours = neighbours[neighbours >= 0]
        options = [label] + [labels[i] for i in
                             np.bincount(neighbours,
                                         minlength=len(labels)).argsort()[::-1]
                             if np.bincount(neighbours,
                                            minlength=len(labels))[i] > 0
                             and labels[i] != label][:5]
        centre = centres[members].mean(axis=0)
        span = np.ptp(centres[members], axis=0)
        # The frame must show WHERE the instance sits, not just its surface:
        # judged from a tight close-up, an ear's inner cup passes for an eye
        # -- placement is half of what identity means.
        radius = max(float(np.linalg.norm(span)) * 1.6, 0.35 * extent)
        answer = _identify_region(backend, mesh, members, options, intent,
                                  centre, radius, pixels, frame, up=up)
        if answer is not None and answer != label:
            # A move needs agreement from a second angle: one view's
            # confident mistake is how horns became eyes.
            second = _identify_region(backend, mesh, members, options, intent,
                                      centre, radius, pixels, frame, up=up,
                                      spin=137.0)
            if second != answer:
                answer = None
        return label_id, label, members, answer

    report = {}
    jobs = (suspects + representatives)[:max_checks]
    if len(suspects) + len(representatives) > max_checks:
        log("  instance check: budget hit, %d of %d instances checked"
            % (max_checks, len(suspects) + len(representatives)))
    if jobs:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda j: check(*j), jobs))
        # A re-identified representative indicts its peer set: check the rest.
        escalate = []
        for label_id, label, _members, answer in results:
            if answer is not None and answer != label and label_id in peers_of:
                for members in peers_of.pop(label_id):
                    escalate.append((label_id, label, members))
        if escalate:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results += list(pool.map(lambda j: check(*j),
                                         escalate[:max_checks]))
        # Plausibility is judged against the labelling as it stood BEFORE any
        # correction: applying one implausible move must not inflate the
        # target enough to legitimise the next.
        snapshot = face_part.copy()
        for label_id, label, members, answer in results:
            if answer is None:
                continue
            if answer == label:
                continue
            target = labels.index(answer)
            # A re-identification that would dwarf everything the target
            # label already holds is a forced choice gone wrong, not a
            # finding -- leave the instance alone and say so.
            instance_area = float(areas[members].sum())
            target_area = float(areas[snapshot == target].sum())
            if target_area > 0 and instance_area > 5.0 * target_area:
                log("  instance check: %s x%d faces -> %s refused as "
                    "implausible (target holds far less); left unchanged"
                    % (label, len(members), answer))
                continue
            face_part[members] = target
            report.setdefault(label, []).append(
                {"faces": int(len(members)), "reassigned_to": answer})
            log("  instance check: %s x%d faces re-identified -> %s"
                % (label, len(members), answer))
    return face_part, report


def recover_scattered_families(mesh, face_part, labels, backend, intent, frame,
                               features, up=(0, 0, 1), pixels=800,
                               max_checks=20, workers=3, log=print):
    """Find the rest of a scattered texture family by what it MEASURES like.

    A label like 'barnacle patches' is not one blob but a family of dozens of
    small encrustations, and per-atom majority voting hands most of them to
    the label they grow ON -- each cluster alone is too small to win its atom.
    The members that DID win define a geometric signature (characteristic
    radius and relief sign from the scale index); faces of host labels that
    match it form candidate patches, sized against the family's own pieces,
    and each candidate is confirmed from two angles by a reviewer choosing
    between the family and its host before a single face moves. Everything is
    relative to the family itself: no absolute size appears anywhere.
    """
    from concurrent.futures import ThreadPoolExecutor
    import scipy.sparse as sparse

    if features is None:
        log("  scatter sweep: no geometric signature available; skipped")
        return face_part, {}
    areas = np.asarray(mesh.area_faces, dtype=float)
    adjacency = mesh.face_adjacency
    centres = mesh.triangles.mean(axis=1)
    extent = float(np.linalg.norm(np.ptp(mesh.vertices, axis=0)))
    painted_area = float(areas[face_part >= 0].sum())

    def components_of(members):
        inside = np.zeros(len(mesh.faces), dtype=bool)
        inside[members] = True
        both = inside[adjacency[:, 0]] & inside[adjacency[:, 1]]
        local = {int(f): i for i, f in enumerate(members)}
        rows = [local[int(a)] for a, b in adjacency[both]]
        cols = [local[int(b)] for a, b in adjacency[both]]
        graph = sparse.coo_matrix((np.ones(len(rows)), (rows, cols)),
                                  shape=(len(members), len(members)))
        n_comp, comp = sparse.csgraph.connected_components(graph,
                                                           directed=False)
        return n_comp, comp

    families = []
    for label_id, label in enumerate(labels):
        members = np.flatnonzero(face_part == label_id)
        if len(members) < 30:
            continue
        family_area = float(areas[members].sum())
        if family_area > 0.10 * painted_area:
            continue
        n_comp, comp = components_of(members)
        if n_comp < 5:
            continue
        comp_area = np.bincount(comp, weights=areas[members],
                                minlength=n_comp)
        median_piece = float(np.median(comp_area))
        if median_piece > 0.02 * painted_area:
            continue
        families.append((label_id, label, members, median_piece))
    if not families:
        return face_part, {}

    family_ids = {label_id for label_id, *_rest in families}
    report = {}
    for label_id, label, members, median_piece in families:
        feats = features[members]
        c_lo, c_hi = np.percentile(feats[:, 0], [12.0, 88.0])
        s_lo, s_hi = np.percentile(feats[:, 1], [12.0, 88.0])
        c_pad, s_pad = 0.2 * (c_hi - c_lo), 0.2 * (s_hi - s_lo)
        candidate = ((face_part >= 0)
                     & ~np.isin(face_part, list(family_ids))
                     & (features[:, 0] >= c_lo - c_pad)
                     & (features[:, 0] <= c_hi + c_pad)
                     & (features[:, 1] >= s_lo - s_pad)
                     & (features[:, 1] <= s_hi + s_pad))
        pool_faces = np.flatnonzero(candidate)
        if len(pool_faces) < 8:
            continue
        n_comp, comp = components_of(pool_faces)
        comp_area = np.bincount(comp, weights=areas[pool_faces],
                                minlength=n_comp)
        patches = [pool_faces[comp == c] for c in range(n_comp)
                   if 0.35 * median_piece <= comp_area[c] <= 3.0 * median_piece]
        patches.sort(key=lambda p: -float(areas[p].sum()))
        if len(patches) > max_checks:
            log("  scatter sweep %-22s: budget hit, %d of %d look-alike "
                "patches checked" % (label, max_checks, len(patches)))
            patches = patches[:max_checks]
        if not patches:
            continue

        def confirm(patch):
            host_votes = np.bincount(face_part[patch], minlength=len(labels))
            host = labels[int(host_votes.argmax())]
            options = [label, host] if host != label else [label]
            centre = centres[patch].mean(axis=0)
            span = float(np.linalg.norm(np.ptp(centres[patch], axis=0)))
            radius = max(span * 1.6, 0.35 * extent)
            first = _identify_region(backend, mesh, patch, options, intent,
                                     centre, radius, pixels, frame, up=up)
            if first != label:
                return patch, None
            second = _identify_region(backend, mesh, patch, options, intent,
                                      centre, radius, pixels, frame, up=up,
                                      spin=137.0)
            return patch, (label if second == label else None)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(confirm, patches))
        recovered = 0
        for patch, answer in results:
            if answer is None:
                continue
            face_part[patch] = label_id
            recovered += 1
            report.setdefault(label, []).append({"faces": int(len(patch))})
        log("  scatter sweep %-22s: %d/%d look-alike patches confirmed "
            "and recovered" % (label, recovered, len(patches)))
    return face_part, report


def _identify_region(backend, mesh, members, options, intent, anchor, radius,
                     pixels, frame, up=(0, 0, 1), spin=0.0):
    """Show the region red in its best view; the reviewer picks its part.

    Returns the chosen label, or None when no view shows the region or the
    reviewer cannot tell -- in either case the caller changes nothing.
    """
    import io
    from PIL import Image
    from . import entities as entities_module
    from . import render as render_module

    mask = np.zeros(len(mesh.faces), dtype=bool)
    mask[members] = True
    normals = mesh.face_normals[mask].mean(axis=0)
    norm = np.linalg.norm(normals)
    base = -normals / norm if norm > 1e-9 else np.array([0.0, -1.0, -0.3])
    axis = np.asarray(up, dtype=float)
    axis = axis / max(np.linalg.norm(axis), 1e-12)

    def spun(angle_deg):
        angle = np.radians(angle_deg)
        parallel = axis * float(base @ axis)
        ortho = base - parallel
        side = np.cross(axis, ortho)
        return parallel + ortho * np.cos(angle) + side * np.sin(angle)

    best = None
    for direction in (spun(spin), spun(spin + 50), spun(spin - 50),
                      spun(spin + 120), spun(spin - 120)):
        direction = direction / max(np.linalg.norm(direction), 1e-12)
        camera = render_module.Camera(direction, up, anchor, radius, pixels)
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        visible = bundle["visible"]
        hit = bundle["hit_id"]
        red = visible & mask[np.clip(hit, 0, len(mask) - 1)]
        coverage = int(red.sum())
        if best is None or coverage > best[0]:
            best = (coverage, bundle, red)
        if coverage > (pixels * pixels) // 50:
            break
    coverage, bundle, red = best
    if coverage < 150:
        return None
    lit = np.clip(bundle["rgb_lit"], 0, 1)
    visible = bundle["visible"]
    image = np.ones((pixels, pixels, 3))
    grey = 0.35 + 0.55 * lit
    image[visible] = grey[visible, None]
    image[red] = np.stack([0.40 + 0.55 * lit[red], 0.12 * lit[red],
                           0.08 * lit[red]], axis=1)
    buffer = io.BytesIO()
    Image.fromarray((image * 255).astype(np.uint8)).save(buffer, format="PNG")
    listed = "\n".join("%d. %s" % (i, option)
                       for i, option in enumerate(options))
    prompt = ("The RED region is one connected piece of this model's surface.\n"
              "The piece: %s\n\nWhich of these parts is the red region?\n%s\n"
              "%d. none of these / cannot tell\n\n"
              'Reply with ONLY a JSON object, no prose: {"choice": <number>}'
              % (intent or "a model", listed, len(options)))
    key = "ident-%s" % entities_module.digest_of(
        buffer.getvalue() + prompt.encode("utf-8"))[7:19]
    path = os.path.join(backend.directory, "%s.png" % key)
    if not os.path.exists(path):
        with open(path, "wb") as handle:
            handle.write(buffer.getvalue())
    answer = backend._run([path], prompt, key)
    try:
        choice = int((answer or {}).get("choice", -1))
    except (TypeError, ValueError):
        return None
    if 0 <= choice < len(options):
        return options[choice]
    return None


def _confirm_claim(backend, sub, local_faces, child, intent, centre, radius, pixels,
                   frame, up=(0, 0, 1)):
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
    camera = render_module.Camera(direction, up, centre, radius, pixels)
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


LOCATE_PROMPT = """You are locating small missing parts on a 3D model so a zoom camera can be aimed at them. You get several numbered views of the whole model, in the order listed (view 0 first).

Missing parts:
%s

The piece: %s

For each part you can SEE in some view, give the view number and a tight pixel bounding
box [x0, y0, x1, y1] around EACH clear instance of it ([0,0] is top-left, images are
%dpx square) -- a paired or repeated part (two eyes, two horns, several studs) gets one
entry PER instance, and both sides of a pair should be boxed even if that takes two
different views. Anchor each box on the exact anatomy: an eye sits on the FACE below
the brow, never on a horn or an ear. If the feature is subtle or would only be PAINTED
on this shape rather than sculpted (lips or eyes on a smooth toy, for instance), box
the place where it belongs -- that is a real answer, and it is how a painter decides
where such features go. Skip only parts whose place you genuinely cannot tell.

Reply with ONLY a JSON object, no prose, no code fences:
{"locations": [{"part": str, "view": int, "box": [int, int, int, int]}]}"""


def locate_missing(backend, mesh, frame, missing, intent, notes, pixels=800, views=5,
                   up=(0, 0, 1)):
    """Ask WHERE each missing part is; backproject the box to a 3D ball.

    This replaces host adoption for parts the hierarchy cannot place. Adoption failed
    structurally on big hosts: "the tail is on the body" is true and useless, because
    zooming onto a host that is most of the model is not zooming -- the patches come out
    as coarse as the pass that already missed the part. A pixel box in a named view
    backprojects through the pick buffer to a point and a radius, and THAT is a place a
    camera can actually be aimed at, whatever labels currently cover it.
    """
    from . import entities as entities_module
    from . import render as render_module
    from . import vision as vision_module

    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2 * 1.05
    directions = render_module.fibonacci_directions(views)
    bundles, paths = [], []
    for k, direction in enumerate(directions):
        camera = render_module.Camera(-direction, up, centre, radius, pixels)
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        bundles.append(bundle)
        path = os.path.join(backend.directory, "locate-view-%d.png" % k)
        with open(path, "wb") as handle:
            handle.write(vision_module.render_png(bundle))
        paths.append(path)
    prompt = LOCATE_PROMPT % ("\n".join("- %s: %s" % (m, notes.get(m, ""))
                                        for m in missing),
                              intent or "not stated", pixels)
    key = "locate-%s" % entities_module.digest_of(
        {"missing": sorted(missing), "prompt": prompt})[7:17]
    answer = backend._run(paths, prompt, key)
    if not answer:
        return {}
    found = {}
    for entry in answer.get("locations", []):
        part = entry.get("part")
        view = entry.get("view")
        box = entry.get("box") or []
        if part not in missing or not isinstance(view, int) \
                or not (0 <= view < len(bundles)) or len(box) != 4:
            continue
        x0, y0, x1, y1 = [int(np.clip(v, 0, pixels - 1)) for v in box]
        if x1 <= x0 or y1 <= y0:
            continue
        bundle = bundles[view]
        window = bundle["point"][y0:y1, x0:x1]
        seen = bundle["visible"][y0:y1, x0:x1]
        if not seen.any():
            continue
        points = window[seen]
        anchor = np.median(points, axis=0)
        extent = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
        # The box's own faces, kept as a stencil. When the geometry refuses to yield
        # the part -- because on this mesh the feature was only ever painted, not
        # sculpted -- the located pixels themselves are the design cut: a label-only
        # boundary drawn where the agent says the feature belongs, mesh untouched.
        stencil = np.unique(bundle["hit_id"][y0:y1, x0:x1][seen])
        # A paired or repeated part legitimately produces SEVERAL boxes -- two
        # eyes, many studs -- and each is its own recovery target; the old
        # single-slot dict silently kept only the last instance. But the SAME
        # instance boxed in two views is one target, not two: the ogre's one
        # neck stump, boxed twice, was drawn twice and flooded the head. Two
        # boxes whose anchors sit within each other's extent are one instance.
        instances = found.setdefault(part, [])
        duplicate = any(np.linalg.norm(anchor - known["anchor"])
                        < 0.6 * (extent + known["extent_mm"])
                        for known in instances)
        if not duplicate and len(instances) < 4:
            instances.append({"anchor": anchor, "extent_mm": max(extent, 1e-3),
                              "direction": bundles[view]["camera"].forward,
                              "stencil_faces": stencil[stencil >= 0]})
    return found


def recover_located(mesh, face_part, labels, backend, intent, frame, located, notes,
                    pixels=760, views=3, workers=3, up=(0, 0, 1)):
    """Zoom a camera at each located ball and ask the patch question there.

    The ball is spatial -- faces near the anchor, whatever label they carry -- so
    anatomy mislabelled to any neighbour is in frame. Only claims for the missing part
    move faces, and each claim still passes the visual confirm gate.
    """
    from . import patches as patch_module
    from . import render as render_module
    from . import vision as vision_module
    from . import entities as entities_module
    import trimesh

    index = {label: i for i, label in enumerate(labels)}
    centres = mesh.triangles.mean(axis=1)
    report = {}

    # Vision-bound and independent per part, exactly like the parent pass:
    # fan out the zoomed asks, splice serially.
    def _recover_part(part, spec):
        anchor, extent = spec["anchor"], spec["extent_mm"]
        ball = np.flatnonzero(np.linalg.norm(centres - anchor, axis=1)
                              < max(extent * 1.6, 2.0))
        if len(ball) < 30:
            return part, [], 0
        sub = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces[ball],
                              process=False)
        zoom_r = max(extent * 1.4, 1e-2)
        footprint = 2 * zoom_r / pixels
        target = patch_module.TILE_FACTOR * patch_module.GLYPH_PX * footprint
        local_patch, count = patch_module.build_patches(sub, target)
        local_labels = sorted({labels[int(face_part[f])] for f in ball
                               if face_part[f] >= 0})
        vocab_here = ([{"label": l, "note": notes.get(l, "")} for l in local_labels]
                      + [{"label": part, "note": notes.get(part, "")}])
        base = np.asarray(spec["direction"], dtype=float)
        helper = np.array([0.0, 0.0, 1.0]) if abs(base[2]) < 0.9 \
            else np.array([1.0, 0.0, 0.0])
        side = np.cross(base, helper)
        side /= max(np.linalg.norm(side), 1e-9)
        rounds = []
        for k, tilt in enumerate((0.0, 0.5, -0.5)[:views]):
            direction = base + side * tilt
            direction /= np.linalg.norm(direction)
            camera = render_module.Camera(direction, up, anchor, zoom_r, pixels)
            bundle = render_module.render_bundle(sub, camera, "zenithal", frame)
            shaded = vision_module.render_png(bundle)
            lit = np.clip(bundle["rgb_lit"], 0, 1)
            id_png, listed = patch_module.render_id_view(sub, local_patch, count,
                                                         camera, lit)
            state = entities_module.digest_of({"ball": ball, "part": part})[7:17]
            votes = patch_module.ask_assignments(backend, shaded, id_png, listed,
                                                 vocab_here, intent,
                                                 "locrec-%s-%s-%d"
                                                 % (part.replace(" ", "_"), state, k))
            rounds.append((votes, 1.0))
        names = local_labels + [part]
        target_id = len(names) - 1
        assigned, _votes = patch_module.fuse_votes(rounds, count, names)
        claimed_patches = sorted({int(local_patch[f]) for f in range(len(ball))
                                  if assigned[local_patch[f]] == target_id})
        if not claimed_patches:
            return part, [], 0
        # PRUNE, DON'T VETO. The binary confirm gate stalemated with claim greed: asked
        # to find a part, the finder finds it everywhere -- half a fish's face claimed
        # as "lips" -- and the gate could only throw the whole claim away, so every
        # recovery ended at zero. Verified by looking at the rejected renders: the gate
        # was right each time, and binary right gets nothing kept. The reviewer now
        # sees the CLAIMED patches numbered and says which are truly the part; the
        # intersection survives. Selection beats judgement at the exit exactly as it
        # did at the entry.
        kept_patches = _prune_claim(backend, sub, local_patch, count, claimed_patches,
                                    part, intent, anchor, zoom_r, pixels, frame,
                                    up=up)
        kept = [int(ball[f]) for f in range(len(ball))
                if int(local_patch[f]) in kept_patches]
        return part, kept, len(claimed_patches)

    from concurrent.futures import ThreadPoolExecutor
    jobs = [(part, spec) for part, specs in located.items() for spec in specs]
    if jobs:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda item: _recover_part(*item), jobs))
        for part, kept, claimed_count in results:
            if kept:
                for face in kept:
                    face_part[face] = index[part]
                report[part] = report.get(part, 0) if report.get(part, 0) > 0 \
                    else 0
                report[part] += len(kept)
            elif report.get(part, 0) <= 0:
                report[part] = min(report.get(part, 0),
                                   -claimed_count if claimed_count else 0)
    # DESIGN CUT, the last resort and an honest one. A part that was LOCATED -- the
    # agent boxed where it belongs -- but that every geometric gate refused is a
    # feature that exists in the design and not in the mesh: lips on a smooth toy
    # fish, markings on a stylized cow. The spec calls for exactly this: a label-only
    # boundary drawn where it does not exist geometrically, without touching the mesh.
    # A single drawing put to a yes/no gate stalemated exactly like the binary
    # confirm did: the gate kept being RIGHT about a mediocre drawing and the
    # feature stayed unpainted forever. So the reviewer now picks from several
    # candidate drawings -- stencil solidified at different radii, discs of
    # camera-facing surface at the located anchor -- or rejects them all.
    # Selection beats judgement at the last gate too.
    for part, specs in located.items():
        if report.get(part, 0) > 0:
            continue
        drawn = 0
        for slot, spec in enumerate(specs):
            stencil = spec.get("stencil_faces")
            if stencil is None or len(stencil) < 10:
                continue
            faces, tag = _pick_design_cut(backend, mesh, frame, part, spec,
                                          intent, pixels, up=up)
            if faces is not None:
                for face in faces:
                    face_part[int(face)] = index[part]
                drawn += int(len(faces))
                report.setdefault("_drawn", []).append(
                    "%s#%d(%s)" % (part, slot, tag))
        if drawn:
            report[part] = drawn
        else:
            report.setdefault("_drawn_rejected", []).append(part)
    return face_part, report


def _design_candidates(mesh, spec):
    """Several plausible drawings of a located, geometry-less feature."""
    adjacency = mesh.face_adjacency
    stencil = np.asarray(spec["stencil_faces"], dtype=int)
    out = []
    for rings, tag in ((1, "tight"), (3, "solid"), (5, "wide")):
        chosen = np.zeros(len(mesh.faces), dtype=bool)
        chosen[stencil] = True
        for _ring in range(rings):
            touch = chosen[adjacency[:, 0]] | chosen[adjacency[:, 1]]
            chosen[np.unique(adjacency[touch].ravel())] = True
        out.append((np.flatnonzero(chosen), tag))
    centres = mesh.triangles.mean(axis=1)
    direction = np.asarray(spec["direction"], dtype=float)
    facing = (mesh.face_normals @ direction) < -0.1
    for scale, tag in ((0.45, "disc-small"), (0.8, "disc-large")):
        disc = (np.linalg.norm(centres - spec["anchor"], axis=1)
                < spec["extent_mm"] * scale) & facing
        if disc.sum() >= 10:
            out.append((np.flatnonzero(disc), tag))
    # Drop near-duplicates: two candidates within 20% of the same size are one
    # choice, not two.
    kept = []
    for faces, tag in out:
        if all(abs(len(faces) - len(other)) > 0.2 * max(len(faces), len(other))
               for other, _tag in kept):
            kept.append((faces, tag))
    return kept[:5]


def _pick_design_cut(backend, mesh, frame, part, spec, intent, pixels,
                     up=(0, 0, 1)):
    """Render every candidate red-in-context from the locating view; one pick."""
    import io
    from PIL import Image, ImageDraw
    from . import entities as entities_module
    from . import render as render_module

    candidates = _design_candidates(mesh, spec)
    if not candidates:
        return None, ""
    direction = np.asarray(spec["direction"], dtype=float)
    radius = max(spec["extent_mm"] * 2.5, 5.0)
    camera = render_module.Camera(direction, up, spec["anchor"], radius,
                                  pixels)
    bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
    lit = np.clip(bundle["rgb_lit"], 0, 1)
    visible = bundle["visible"]
    hit = bundle["hit_id"]
    grey = 0.35 + 0.55 * lit
    blobs, paths = [], []
    for i, (faces, _tag) in enumerate(candidates):
        mask = np.zeros(len(mesh.faces), dtype=bool)
        mask[faces] = True
        image = np.ones((pixels, pixels, 3))
        image[visible] = grey[visible, None]
        red = visible & mask[np.clip(hit, 0, len(mask) - 1)]
        image[red] = np.stack([0.40 + 0.55 * lit[red], 0.12 * lit[red],
                               0.08 * lit[red]], axis=1)
        picture = Image.fromarray((image * 255).astype(np.uint8))
        ImageDraw.Draw(picture).text((10, 8), str(i), fill=(0, 0, 0))
        buffer = io.BytesIO()
        picture.save(buffer, format="PNG")
        blobs.append(buffer.getvalue())
    key = "pickcut-%s-%s" % (part.replace(" ", "_"),
                             entities_module.digest_of(b"".join(blobs))[7:17])
    for i, blob in enumerate(blobs):
        path = os.path.join(backend.directory, "%s-%d.png" % (key, i))
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(blob)
        paths.append(path)
    prompt = ("Each image shows the SAME view of the piece with a DIFFERENT red "
              "drawing of where the %s would be painted (the feature may be "
              "purely painted-on; judge placement, coverage and shape). Images "
              "are numbered top-left, in the order given.\n"
              "The piece: %s\n\n"
              "Which drawing best matches where the %s belongs? Prefer the one "
              "a painter would mask. If none is acceptable -- wrong place, or "
              "absurd shape -- reject them all.\n\n"
              'Reply with ONLY a JSON object, no prose: {"choice": <number>} '
              'or {"choice": -1}'
              % (part, intent or "a model", part))
    answer = backend._run(paths, prompt, key)
    try:
        choice = int((answer or {}).get("choice", -1))
    except (TypeError, ValueError):
        choice = -1
    if 0 <= choice < len(candidates):
        faces, tag = candidates[choice]
        return faces, tag
    return None, ""


def _confirm_in_context(backend, mesh, faces, part, intent, anchor, radius, pixels,
                        frame, up=(0, 0, 1)):
    """Whole model in frame, claimed faces red, one question.

    Returns True (confirmed), False (refused), or None: no candidate view
    showed the claim, so nothing was actually judged. The ogre's tusks were
    "refused" from a view that showed zero red pixels -- an honest reviewer
    saying it could not see tusks, mistaken by the caller for a verdict.
    Several directions are tried and the one showing the claim best asks the
    question; unseen is reported as unseen.
    """
    import io
    from PIL import Image
    from . import entities as entities_module
    from . import render as render_module

    mask = np.zeros(len(mesh.faces), dtype=bool)
    mask[faces] = True
    normals = mesh.face_normals[mask].mean(axis=0)
    norm = np.linalg.norm(normals)
    base = -normals / norm if norm > 1e-9 else np.array([0.0, -1.0, -0.3])
    axis = np.asarray(up, dtype=float)
    axis = axis / max(np.linalg.norm(axis), 1e-12)

    def spun(angle_deg):
        angle = np.radians(angle_deg)
        parallel = axis * float(base @ axis)
        ortho = base - parallel
        side = np.cross(axis, ortho)
        return parallel + ortho * np.cos(angle) + side * np.sin(angle)

    best = None
    for direction in (spun(spin), spun(spin + 50), spun(spin - 50),
                      spun(spin + 120), spun(spin - 120)):
        direction = direction / max(np.linalg.norm(direction), 1e-12)
        camera = render_module.Camera(direction, up, anchor, radius, pixels)
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        visible = bundle["visible"]
        hit = bundle["hit_id"]
        red = visible & mask[np.clip(hit, 0, len(mask) - 1)]
        coverage = int(red.sum())
        if best is None or coverage > best[0]:
            best = (coverage, bundle, red)
        if coverage > (pixels * pixels) // 50:
            break
    coverage, bundle, red = best
    if coverage < 150:
        return None
    lit = np.clip(bundle["rgb_lit"], 0, 1)
    visible = bundle["visible"]
    image = np.ones((pixels, pixels, 3))
    grey = 0.35 + 0.55 * lit
    image[visible] = grey[visible, None]
    image[red] = np.stack([0.40 + 0.55 * lit[red], 0.12 * lit[red],
                           0.08 * lit[red]], axis=1)
    buffer = io.BytesIO()
    Image.fromarray((image * 255).astype(np.uint8)).save(buffer, format="PNG")
    key = "ctx-%s-%s" % (part.replace(" ", "_"),
                         entities_module.digest_of(buffer.getvalue())[7:17])
    path = os.path.join(backend.directory, "%s.png" % key)
    with open(path, "wb") as handle:
        handle.write(buffer.getvalue())
    prompt = ("The RED region marks where the %s will be painted on this piece "
              "(the feature may be subtle or purely painted-on; judge PLACEMENT).\n"
              "The piece: %s\n\n"
              "Is the red region in the right place and roughly the right size for "
              "the %s?\n\n"
              'Reply with ONLY a JSON object, no prose: {"correct": true} or '
              '{"correct": false}' % (part, intent or "a model", part))
    answer = backend._run([path], prompt, key)
    if not answer:
        return None
    return bool(answer.get("correct"))


def _prune_claim(backend, sub, local_patch, count, claimed_patches, part, intent,
                 anchor, zoom_r, pixels, frame, up=(0, 0, 1)):
    """Show the claim as numbered patches; keep only the ids the reviewer confirms."""
    from . import entities as entities_module
    from . import patches as patch_module
    from . import render as render_module
    import io
    from PIL import Image, ImageDraw

    mask_faces = np.isin(local_patch, list(claimed_patches))
    normals = sub.face_normals[mask_faces].mean(axis=0)
    norm = np.linalg.norm(normals)
    direction = -normals / norm if norm > 1e-9 else np.array([0.0, -1.0, -0.3])
    camera = render_module.Camera(direction, up, anchor, zoom_r, pixels)
    bundle = render_module.render_bundle(sub, camera, "zenithal", frame)
    lit = np.clip(bundle["rgb_lit"], 0, 1)
    id_png, listed = patch_module.render_id_view(sub, local_patch, count, camera, lit)
    offer = [pid for pid in listed if pid in set(claimed_patches)]
    if not offer:
        return set()
    key = "prune-%s-%s" % (part.replace(" ", "_"),
                           entities_module.digest_of(sorted(claimed_patches))[7:17])
    path = os.path.join(backend.directory, "%s.png" % key)
    with open(path, "wb") as handle:
        handle.write(id_png)
    prompt = ("A recovery pass claims these numbered patches are: %s\n"
              "The piece: %s\n\n"
              "Candidate patch ids: %s\n\n"
              "Which of those ids are TRULY part of the %s -- on the right anatomy, in "
              "the right place? Be strict: keeping a wrong patch paints the wrong "
              "surface. An empty list is a fine answer.\n\n"
              'Reply with ONLY a JSON object, no prose: {"keep": [int, ...]}'
              % (part, intent or "a model", offer, part))
    answer = backend._run([path], prompt, key)
    if not answer:
        return set()
    return {int(i) for i in answer.get("keep", []) if int(i) in set(offer)}


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
{"verdict": str, "changes": [{"part": str, "filament": str, "why": str}]}
Judge with a painter's restraint: parts of the same material should normally share one filament (skin stays skin everywhere, including bald crowns and recesses -- shadow does the separating), and NO filament needs a job. Never spread colours to use them up; override toward fewer colours when the piece reads as patchwork.
"""


def review_scheme(backend, render_paths, scheme, chosen, palette, intent):
    """Show the critic the finished renders; return filament overrides it insists on."""
    lines = "\n".join("- %-24s -> %-8s (wanted %s, role %s)"
                      % (entry["region"], chosen[entry["region"]].name,
                         entry.get("hex", "?"), entry.get("role", "?"))
                      for entry in scheme)
    filaments = ", ".join(paint.name for paint in palette)
    prompt = REVIEW_PROMPT % (intent or "not stated", lines, filaments)
    # Keyed by the renders actually reviewed: a constant key replayed the
    # first critique ever cached against renders it never saw.
    from . import entities as entities_module
    blob = prompt.encode("utf-8")
    for path in render_paths:
        with open(path, "rb") as handle:
            blob += handle.read()
    answer = backend._run(list(render_paths), prompt,
                          "critic-%s" % entities_module.digest_of(blob)[7:19])
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


CONTINUOUS_REVIEW = """You are reviewing the UNCONSTRAINED colour design of a \
3D piece -- no printer, no palette limits, pure painted-asset quality. The \
images show it shaded with each part's base, shade and highlight colours \
blended over the surface.

The piece: %s

Current design (per part: base / shade / highlight):
%s

Judge it as a finished painted collectible: soft natural transitions, material \
truth (one material reads as one substance), believable colour temperature in \
recesses and crests, features legible. Where it fails, change the part's \
colours -- kin adjustments beat replacements. Change only what needs changing.

Reply with ONLY a JSON object, no prose, no code fences:
{"verdict": str, "changes": [{"part": str, "hex": "#RRGGBB", \
"shade_hex": "#RRGGBB", "highlight_hex": "#RRGGBB", "why": str}]}"""


def review_continuous(backend, render_paths, scheme, intent):
    """The design is judged AS A DESIGN, before any filament exists."""
    from . import entities as entities_module
    from .agents import _hex_to_lab
    lines = "\n".join("- %-24s %s / %s / %s" % (
        entry["region"], entry.get("hex", "?"),
        entry.get("shade_hex", entry.get("hex", "?")),
        entry.get("highlight_hex", entry.get("hex", "?")))
        for entry in scheme)
    prompt = CONTINUOUS_REVIEW % (intent or "not stated", lines)
    blob = prompt.encode("utf-8")
    for path in render_paths:
        with open(path, "rb") as handle:
            blob += handle.read()
    answer = backend._run(list(render_paths), prompt,
                          "designcrit-%s" % entities_module.digest_of(blob)[7:19])
    if not answer:
        return 0, "design review unavailable"
    by_region = {entry["region"]: entry for entry in scheme}
    changed = 0
    for change in answer.get("changes", []):
        entry = by_region.get(change.get("part", ""))
        if entry is None:
            continue
        for key, lab_key in (("hex", "lab"), ("shade_hex", "shade_lab"),
                             ("highlight_hex", "highlight_lab")):
            value = change.get(key)
            if value:
                entry[key] = value
                entry[lab_key] = _hex_to_lab(value)
        changed += 1
    return changed, answer.get("verdict", "")
