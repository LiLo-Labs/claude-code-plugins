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

The orbit alone always leaves a residue, and it is a residue of the LOOKING,
not of the judgement (circumstance 2). An orbit camera sits on the bounding
sphere and frames the whole model, so an instance on a steeply turned facet
is foreshortened in every one of them at once; orbiting harder cannot fix
what the orbit's own geometry costs. So the aimed rounds leave the sphere:
each camera sits on the outward normal of an unindexed look-alike and looks
straight in, at instance scale. They also SHOW what is already indexed --
confirmed instances tinted -- so the question is "what did we miss" rather
than "what is here".

Re-asking the ORBIT looks under that same tinted question was tried and cut.
Measured on the shell: 162 re-asks confirmed three instances the first pass
had missed, while 24 aimed looks confirmed three -- about seven times the
yield per look, at a seventh of the cost. Attention was never the binding
constraint; the geometry of the look was. A better question cannot recover
an answer the viewpoint does not contain.

The aimed rounds REPEAT, because each round changes both halves of its own
question. Confirming an instance takes it out of the candidate pool, so the
next round aims somewhere new; and it joins the signature that ranks the
pool, so a round that confirms small instances widens the band the next
round reaches with. The survey stops when a round stops finding -- a fact
about the model, not a number chosen in advance.

Every round is scored on its OWN evidence. Pooling them would put every
earlier view into the denominator of a node only a later round found,
punishing it for the blindness that round exists to correct.

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


GAP_PROMPT = """This is a %dx%d rendered view of a 3D model.

The piece: %s

We are indexing every %s. %s

The ones we have ALREADY indexed are tinted blue in this image. Your job is
only to find the ones we MISSED: %ss that are still plain grey. Ignore every
blue one -- they are done.

For each MISSED one, give the pixel coordinate of a point on it, as close to
its centre as you can. x is measured from the left edge, y from the top edge.
The coordinate must land on grey feature surface, not on blue.

Reply with ONLY a JSON object, no prose:
{"found": [{"n": 1, "x": <int>, "y": <int>}, ...]}
An empty list is a correct answer, and the right one if every %s here is
already blue."""


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


NAME_PROMPT = """This is a %dx%d rendered close view of part of a 3D model.

The piece: %s

ONE shape in this image is tinted blue. Look at the tinted shape itself --
not the grey things around it.

We believe it is a %s. %s

What is the tinted shape actually part of? Choose honestly. If it is not a
%s, say so and name what it really is; that is a useful answer, not a
failure. If the tint covers something you cannot make out at this size, say
unclear.

Reply with ONLY a JSON object, no prose:
{"is": "yes"}                       the tinted shape is a %s
{"is": "no", "actually": "<what it really is, a few words>"}
{"is": "unclear"}"""


def confirm(backend, mesh, frame, up, feature, hint, intent, out_dir, unit,
            pixels=900, workers=8, log=print):
    """Ask of each indexed instance what it actually is, without leading it.

    The aimed rounds are a leading question by construction: they put one
    candidate in the centre of frame and ask what is still unmarked there,
    which invites a yes. That is the right trade for finding things and the
    wrong one for keeping them, so recall and precision are separated -- the
    rounds propose, and this gate disposes.

    It is a gate that exits through SELECTION (circumstance 6): the agent may
    answer that the tinted shape is something else and say what, which is
    information, where a yes/no would only have destroyed it. An instance is
    dropped only when it is named as something else; unclear keeps it, since
    an unreadable render is evidence about the render (circumstance 2).
    """
    import os as os_module
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image
    from . import entities as entities_module
    from . import render as render_module

    os_module.makedirs(out_dir, exist_ok=True)
    areas = np.asarray(mesh.area_faces, dtype=float)
    centres = np.asarray(mesh.triangles_center, dtype=float)
    normals = np.asarray(mesh.face_normals, dtype=float)
    numbers = np.unique(unit[unit >= 0])

    def ask(number):
        faces = np.flatnonzero(unit == number)
        if not len(faces):
            return number, "unseen", ""
        weight = areas[faces]
        outward = (normals[faces] * weight[:, None]).sum(axis=0)
        norm = np.linalg.norm(outward)
        if norm < 1e-9:
            return number, "unseen", ""
        inward = -outward / norm   # see _aim_cameras: forward looks INTO the surface
        target = (centres[faces] * weight[:, None]).sum(axis=0) / weight.sum()
        # Framed at several instance widths, so the agent sees the thing IN
        # its surroundings and can tell a cone on a rib from a cone on a
        # frond -- the distinction a tight crop destroys.
        reach = float(np.sqrt(weight.sum() / np.pi)) * 7.0
        side = np.cross(inward, [0.0, 0.0, 1.0])
        if np.linalg.norm(side) < 1e-6:
            side = np.cross(inward, [0.0, 1.0, 0.0])
        spun = np.cross(side / np.linalg.norm(side), inward)
        camera = render_module.Camera(inward, spun, target, reach, pixels)
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        visible = bundle["visible"]
        if not visible.any():
            return number, "unseen", ""
        lit = np.clip(bundle["rgb_lit"], 0, 1)
        shade = 0.32 + 0.60 * lit
        image = np.ones((pixels, pixels, 3))
        image[visible] = shade[visible, None]
        member = np.zeros(len(mesh.faces), dtype=bool)
        member[faces] = True
        hit = bundle["hit_id"]
        blue = visible & (hit >= 0) & member[np.maximum(hit, 0)]
        if blue.sum() < 60:
            return number, "unseen", ""
        image[blue] = np.stack([shade[blue] * 0.30, shade[blue] * 0.45,
                                np.minimum(shade[blue] * 1.25, 1.0)], axis=1)
        path = os_module.path.join(out_dir, "confirm-%d.png" % number)
        Image.fromarray((image * 255).astype(np.uint8)).save(path)
        prompt = NAME_PROMPT % (pixels, pixels, intent or "a model", feature,
                                hint or "", feature, feature)
        key = "name-%s" % entities_module.digest_of(
            open(path, "rb").read() + prompt.encode("utf-8"))[7:19]
        answer = backend._run([path], prompt, key) or {}
        verdict = str(answer.get("is", "unclear")).strip().lower()
        return number, verdict, str(answer.get("actually", "")).strip()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        verdicts = list(pool.map(ask, numbers))

    kept, dropped, unclear, unseen, named = [], [], 0, 0, {}
    for number, verdict, actually in verdicts:
        if verdict == "no":
            dropped.append(number)
            label = actually.lower() or "unnamed"
            named[label] = named.get(label, 0) + 1
        else:
            kept.append(number)
            if verdict == "unseen":
                unseen += 1
            elif verdict != "yes":
                unclear += 1
    # "unseen" is counted apart from "unclear" on purpose. Unclear is a
    # judgement the agent made about a picture it saw; unseen means no
    # picture reached it at all, and a gate that reports those as one number
    # hides its own coverage. A run where most instances were never shown is
    # not a 90%-pass rate, and the log must not be able to say it is.
    log("  confirm: %d kept, %d renamed away, %d unclear, %d never shown "
        "(kept, but unexamined)"
        % (len(kept), len(dropped), unclear, unseen))
    for label, count in sorted(named.items(), key=lambda kv: -kv[1])[:8]:
        log("    not a %s, actually: %s x%d" % (feature.split(" -- ")[0],
                                                label, count))
    out = np.full(len(unit), -1, dtype=np.int64)
    for fresh, number in enumerate(kept):
        out[unit == number] = fresh
    return out, len(kept), dropped


def _consensus(votes, shown, min_votes, min_share):
    """Judge a node on the views that could actually have seen it.

    A node the cameras only ever reached once cannot clear two votes however
    obvious it is, so the bar is the smaller of the asked-for bar and the
    number of looks that contained it: seen twice, agreed twice; seen once,
    agreed once. The share gate is what keeps that honest -- a node offered
    to ten views and pointed at in one still fails.
    """
    share = votes / np.maximum(shown, 1)
    bar = np.minimum(min_votes, np.maximum(shown, 1))
    return np.flatnonzero((votes > 0) & (votes >= bar) & (share >= min_share)), share


def _groups(face_node):
    """Face indices grouped by node, once. Scanning the whole face array per
    node is quadratic on a 600k-face mesh; one argsort is not."""
    live = np.flatnonzero(face_node >= 0)
    order = live[np.argsort(face_node[live], kind="stable")]
    keys = face_node[order]
    edges = np.flatnonzero(np.diff(keys)) + 1
    return dict(zip(keys[np.concatenate([[0], edges])],
                    np.split(order, edges)))


def _signature(groups, characteristic, features, areas, nodes):
    """What the confirmed instances measure like, per node.

    Three axes the scale-space index already carries -- characteristic radius,
    relief sign, response strength -- summarised per node by the area-weighted
    median face, plus the node's area. This is only ever used to AIM a camera;
    nothing is labelled by it.
    """
    out = {}
    for node in nodes:
        faces = groups.get(int(node))
        if faces is None or not len(faces):
            continue
        weight = areas[faces]
        order = np.argsort(characteristic[faces])
        cumulative = np.cumsum(weight[order])
        where = int(np.searchsorted(cumulative, cumulative[-1] / 2.0))
        middle = faces[order[min(where, len(order) - 1)]]
        out[int(node)] = np.concatenate([features[middle],
                                         [float(weight.sum())]])
    return out


def _aim_cameras(mesh, face_node, groups, confirmed, characteristic, features,
                 areas, pixels, family, limit=24):
    """Cameras pointed straight down at unindexed look-alikes.

    Every orbit camera is a compromise: it frames the whole model, so an
    instance on a steeply turned facet is foreshortened in all of them at
    once, and no amount of orbiting fixes it because the orbit never leaves
    the model's bounding sphere. These cameras leave it: each one sits on the
    outward normal of a candidate node and looks in, so the candidate is
    presented face-on and at instance scale.

    The candidates are chosen by geometric signature -- unindexed nodes that
    measure like the confirmed instances on all three scale-space axes and on
    area. That is aiming, not labelling: what is at the end of the aim still
    has to be pointed at by an agent and still has to pass consensus.
    """
    from . import render as render_module

    if not len(confirmed):
        return []
    known = _signature(groups, characteristic, features, areas, confirmed)
    if not known:
        return []
    reference = np.stack(list(known.values()))
    low = np.percentile(reference, 5.0, axis=0)
    high = np.percentile(reference, 95.0, axis=0)

    candidates = np.setdiff1d(np.fromiter(groups.keys(), dtype=np.int64),
                              np.asarray(confirmed, dtype=np.int64))
    if not len(candidates):
        return []
    # Cheap prefilter on area, so the per-node signature is computed for a
    # plausible few hundred rather than every node on the surface.
    node_area = np.array([areas[groups[int(n)]].sum() for n in candidates])
    plausible = candidates[(node_area >= low[3]) & (node_area <= high[3])]
    if not len(plausible):
        return []
    signature = _signature(groups, characteristic, features, areas, plausible)
    spread = np.maximum(high[:3] - low[:3], 1e-6)
    middle = (high[:3] + low[:3]) / 2.0
    scored = []
    for node, vector in signature.items():
        distance = np.abs(vector[:3] - middle) / spread
        if np.all(distance <= 1.0):
            scored.append((float(distance.max()), node))
    if not scored:
        return []
    scored.sort()

    normals = np.asarray(mesh.face_normals, dtype=float)
    centres = np.asarray(mesh.triangles_center, dtype=float)
    reach = max(4.0 * family, 1e-6)
    out = []
    for _score, node in scored[:limit]:
        faces = groups[int(node)]
        weight = areas[faces]
        outward = (normals[faces] * weight[:, None]).sum(axis=0)
        norm = np.linalg.norm(outward)
        if norm < 1e-9:
            continue
        # Camera.rays() puts the ray origin at centre - forward * 4r, so
        # `forward` is the direction the camera LOOKS, pointing from outside
        # into the surface. The outward normal is where the camera stands;
        # what it looks along is the negative. Passing the normal itself put
        # the camera inside the model for 58% of candidates on the shell,
        # which rendered the far side and wasted the look entirely.
        inward = -outward
        target = (centres[faces] * weight[:, None]).sum(axis=0) / weight.sum()
        side = np.cross(inward, [0.0, 0.0, 1.0])
        if np.linalg.norm(side) < 1e-6:
            side = np.cross(inward, [0.0, 1.0, 0.0])
        spun = np.cross(side / np.linalg.norm(side), inward)
        out.append((render_module.Camera(inward, spun, target, reach, pixels),
                    "aim%d" % int(node)))
    return out


def survey(backend, mesh, frame, up, feature, hint, intent, out_dir, tree,
           characteristic, views=6, pixels=900, zoom_tiles=3, workers=8,
           min_votes=2, min_share=0.34, aims=64, max_rounds=8, min_new=2,
           log=print):
    """Look from many different cameras; let tree nodes collect the votes.

    One orbiting pass asks what is there. Then aimed rounds repeat until they
    stop finding: each puts a camera on the outward normal of an unindexed
    look-alike, shows what is already indexed, and asks what is still
    unmarked. Every round is scored on its own evidence, and a node confirmed
    by any round is confirmed.
    """
    import os as os_module
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image
    from . import entities as entities_module
    from . import render as render_module

    os_module.makedirs(out_dir, exist_ok=True)
    wide, centre, radius = cameras(mesh, up, pixels, views, zoom_tiles)
    areas = np.asarray(mesh.area_faces, dtype=float)
    features = np.asarray(tree["features"], dtype=float)

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

    def look(job, marked=None):
        camera, tag = job
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        visible = bundle["visible"]
        if not visible.any():
            return None
        lit = np.clip(bundle["rgb_lit"], 0, 1)
        shade = 0.32 + 0.60 * lit
        image = np.ones((pixels, pixels, 3))
        image[visible] = shade[visible, None]
        if marked is not None:
            hit = bundle["hit_id"]
            blue = visible & (hit >= 0) & marked[np.maximum(hit, 0)]
            if blue.any():
                image[blue] = np.stack([shade[blue] * 0.30,
                                        shade[blue] * 0.45,
                                        np.minimum(shade[blue] * 1.25, 1.0)],
                                       axis=1)
            prompt = GAP_PROMPT % (pixels, pixels, intent or "a model",
                                   feature, hint or "", feature, feature)
            tag = "gap-%s" % tag
        else:
            prompt = FIND_PROMPT % (pixels, pixels, intent or "a model",
                                    feature, hint or "")
        path = os_module.path.join(out_dir, "look-%s.png" % tag)
        Image.fromarray((image * 255).astype(np.uint8)).save(path)
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

    def tally(batch, ignore=None):
        votes = np.zeros(total, dtype=np.int64)
        shown = np.zeros(total, dtype=np.int64)
        for hits, visible_faces in batch:
            pointed = np.unique(face_node[np.array(hits, dtype=np.int64)]) \
                if hits else np.array([], dtype=np.int64)
            votes[pointed] += 1
            here = np.unique(face_node[visible_faces[visible_faces >= 0]])
            if ignore is not None:
                here = here[~ignore[here]]
            shown[here] += 1
        return votes, shown

    votes, shown = tally(results)
    winners, _share = _consensus(votes, shown, min_votes, min_share)
    log("  pass 1: %d nodes pointed at; %d pass consensus"
        % (int((votes > 0).sum()), len(winners)))

    # The aimed rounds. Each one takes the unindexed nodes that most look
    # like the instances confirmed SO FAR, puts a camera on each one's
    # outward normal, and asks what is still unmarked. The loop is the point:
    # every round changes both halves of its own question. Confirming an
    # instance removes it from the candidate pool, so the next round aims
    # somewhere new; and it joins the signature the pool is ranked against,
    # so a round that confirms small cones widens the band the next round
    # will reach with. The survey stops when a round stops finding, which is
    # a fact about the model rather than a number chosen in advance.
    groups = _groups(face_node)
    settled = np.zeros(total, dtype=bool)
    settled[winners] = True
    for number in range(1, max_rounds + 1):
        if not len(winners):
            break
        aimed = _aim_cameras(mesh, face_node, groups, winners, characteristic,
                             features, areas, pixels, family, limit=aims)
        if not aimed:
            log("  round %d: no unindexed candidate looks like the family; "
                "the pool is exhausted" % number)
            break
        marked = np.isin(face_node, winners)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            more = [r for r in pool.map(lambda job: look(job, marked), aimed)
                    if r is not None]
        # Each round is a self-contained survey and is scored on its OWN
        # evidence. Pooling rounds would put every earlier view into the
        # denominator of a node only this round found -- punishing it for the
        # blindness this round exists to correct, which is circumstance 2 one
        # level up. A node confirmed by any round is confirmed.
        found, _share = _consensus(*tally(more, ignore=settled), min_votes,
                                   min_share)
        fresh = np.setdiff1d(found, np.flatnonzero(settled))
        winners = np.union1d(winners, found)
        settled[winners] = True
        log("  round %d: %d aimed looks -> %d pass, %d new (%d indexed)"
            % (number, len(more), len(found), len(fresh), len(winners)))
        if len(fresh) < min_new:
            log("  round %d found %d, below the %d that would justify another;"
                " stopping" % (number, len(fresh), min_new))
            break
    log("  %d instances indexed (>=%d votes or unanimous where rarely seen, "
        ">=%.0f%% of the views that could see them)"
        % (len(winners), min_votes, 100 * min_share))

    unit = np.full(len(mesh.faces), -1, dtype=np.int64)
    for number, node in enumerate(winners):
        unit[face_node == node] = number
    return unit, len(winners), family
