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


DIRECT_PROMPT = """This is a %dx%d rendered overview of a 3D model.

The piece: %s

Every %s we have already indexed is tinted blue. Others may still be plain
grey.

Point at up to %d places in THIS image where you can see grey, unindexed
%ss. Prefer places holding several of them, and places away from the ones
already tinted. For each place also say roughly how many pixels across a
single %s is at that spot in this image -- small for distant or tiny ones,
larger for near ones. A close camera will be sent to each place you name, at
the scale you report, so the scale matters as much as the position.

Reply with ONLY a JSON object, no prose:
{"look": [{"n": 1, "x": <int>, "y": <int>, "across": <int>}, ...]}
An empty list is a correct answer if every %s here is already blue."""


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
    information, where a yes/no would only have destroyed it. Unclear keeps
    the instance, since an unreadable render is evidence about the render
    (circumstance 2) -- and so does a single "no", because a drop is a verdict
    too: it is taken only when a second angle agrees.
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

    def ask(number, tilt, phase):
        faces = np.flatnonzero(unit == number)
        if not len(faces):
            return "unseen", ""
        weight = areas[faces]
        # Framed at several instance widths, so the agent sees the thing IN
        # its surroundings and can tell a cone on a rib from a cone on a
        # frond -- the distinction a tight crop destroys.
        reach = float(np.sqrt(weight.sum() / np.pi)) * 7.0
        camera = _look_at(mesh, faces, areas, centres, normals, pixels, reach,
                          tilt=tilt, phase=phase)
        if camera is None:
            return "unseen", ""
        bundle = render_module.render_bundle(mesh, camera, "zenithal", frame)
        visible = bundle["visible"]
        if not visible.any():
            return "unseen", ""
        lit = np.clip(bundle["rgb_lit"], 0, 1)
        shade = 0.32 + 0.60 * lit
        image = np.ones((pixels, pixels, 3))
        image[visible] = shade[visible, None]
        member = np.zeros(len(mesh.faces), dtype=bool)
        member[faces] = True
        hit = bundle["hit_id"]
        blue = visible & (hit >= 0) & member[np.maximum(hit, 0)]
        if blue.sum() < 60:
            return "unseen", ""
        image[blue] = np.stack([shade[blue] * 0.30, shade[blue] * 0.45,
                                np.minimum(shade[blue] * 1.25, 1.0)], axis=1)
        path = os_module.path.join(out_dir, "confirm-%d-t%d.png"
                                   % (number, int(round(tilt))))
        Image.fromarray((image * 255).astype(np.uint8)).save(path)
        prompt = NAME_PROMPT % (pixels, pixels, intent or "a model", feature,
                                hint or "", feature, feature)
        key = "name-%s" % entities_module.digest_of(
            open(path, "rb").read() + prompt.encode("utf-8"))[7:19]
        answer = backend._run([path], prompt, key) or {}
        return (str(answer.get("is", "unclear")).strip().lower(),
                str(answer.get("actually", "")).strip())

    def judge(number):
        """Keep on one yes; drop only on two angles agreeing it is not.

        A drop is a verdict like any other, and the two-angle law applies to
        it (circumstance 2). The first gate dropped on a single look and threw
        away barnacles that were plainly ridged and cratered from any other
        angle -- the render had lost them, and the verdict inherited the loss.
        """
        first, actually = ask(number, 0.0, 0.0)
        if first != "no":
            return number, first, ""
        second, again = ask(number, 30.0, 1.05)
        if second != "no":
            # The angles disagree, so the evidence does not support removing
            # it. Kept, and flagged, because a contested instance is a fact
            # worth reporting rather than a coin to flip.
            return number, "contested", actually
        return number, "no", again or actually

    with ThreadPoolExecutor(max_workers=workers) as pool:
        verdicts = list(pool.map(judge, numbers))

    kept, dropped, unclear, unseen, contested, named = [], [], 0, 0, 0, {}
    for number, verdict, actually in verdicts:
        if verdict == "no":
            dropped.append(number)
            label = actually.lower() or "unnamed"
            named[label] = named.get(label, 0) + 1
        else:
            kept.append(number)
            if verdict == "unseen":
                unseen += 1
            elif verdict == "contested":
                contested += 1
            elif verdict != "yes":
                unclear += 1
    # "unseen" is counted apart from "unclear" on purpose. Unclear is a
    # judgement the agent made about a picture it saw; unseen means no
    # picture reached it at all, and a gate that reports those as one number
    # hides its own coverage. A run where most instances were never shown is
    # not a 90%-pass rate, and the log must not be able to say it is.
    log("  confirm: %d kept, %d renamed away on two angles, %d contested "
        "(one angle said no, another did not), %d unclear, %d never shown "
        "(kept, but unexamined)"
        % (len(kept), len(dropped), contested, unclear, unseen))
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


def _tilted(direction, angle_deg, phase):
    """A view direction rotated off `direction` by an angle, in a chosen plane.

    A candidate that survives one round is looked at again in the next, and
    looking again from the identical angle is not a second look. Rolling the
    view off the normal changes the foreshortening, the silhouette and what
    the neighbours occlude -- which is the whole reason moving the camera
    means anything (circumstance 2).
    """
    direction = np.asarray(direction, float)
    if abs(angle_deg) < 1e-6:
        return direction
    reference = np.array([0.0, 0.0, 1.0])
    if abs(float(direction @ reference)) > 0.98:
        reference = np.array([0.0, 1.0, 0.0])
    side = np.cross(direction, reference)
    side /= max(np.linalg.norm(side), 1e-12)
    other = np.cross(direction, side)
    axis = side * np.cos(phase) + other * np.sin(phase)
    angle = np.radians(angle_deg)
    spun = direction * np.cos(angle) + np.cross(axis, direction) * np.sin(angle)
    return spun / max(np.linalg.norm(spun), 1e-12)


def _look_at(mesh, faces, areas, centres, normals, pixels, reach,
             tilt=0.0, phase=0.0):
    """One camera standing off a patch of surface, looking in."""
    from . import render as render_module
    weight = areas[faces]
    outward = (normals[faces] * weight[:, None]).sum(axis=0)
    norm = np.linalg.norm(outward)
    if norm < 1e-9:
        return None
    # Camera.rays() puts the ray origin at centre - forward * 4r, so `forward`
    # is the direction the camera LOOKS: from outside, into the surface. The
    # outward normal is where the camera stands; the negative is where it
    # points. Passing the normal itself put the camera inside the model.
    inward = _tilted(-outward / norm, tilt, phase)
    target = (centres[faces] * weight[:, None]).sum(axis=0) / weight.sum()
    side = np.cross(inward, [0.0, 0.0, 1.0])
    if np.linalg.norm(side) < 1e-6:
        side = np.cross(inward, [0.0, 1.0, 0.0])
    spun = np.cross(side / np.linalg.norm(side), inward)
    return render_module.Camera(inward, spun, target, reach, pixels)


def _aim_cameras(mesh, face_node, groups, confirmed, characteristic, features,
                 areas, pixels, family, limit=24, tilt=0.0, phase=0.0,
                 zooms=(1.0,)):
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
    out = []
    for _score, node in scored[:limit]:
        faces = groups[int(node)]
        for zoom in zooms:
            reach = max(4.0 * family * zoom, 1e-6)
            camera = _look_at(mesh, faces, areas, centres, normals, pixels,
                              reach, tilt=tilt, phase=phase)
            if camera is not None:
                out.append((camera, "aim%d-t%dz%d"
                            % (int(node), int(round(tilt)),
                               int(round(zoom * 10)))))
    return out


def _directed(backend, mesh, frame, wide, marked, feature, intent, out_dir,
              pixels, areas, centres, normals, tilt, phase, workers, up,
              occlusion, places=8, log=print):
    """Cameras a global agent asked for, at the scale it asked for.

    The geometric aims can only propose what already resembles what is
    confirmed, so they walk outward from the index and cannot cross a gap.
    An agent looking at the WHOLE piece can: it sees where the tinted
    instances are not, and says go there. It reports the apparent size of an
    instance at each place it names, which sets the camera's framing -- so
    the zoom level is chosen by something that can see the model rather than
    by a constant, which is the only way one number can suit a colony in the
    foreground and one on the far rim.
    """
    import os as os_module
    from concurrent.futures import ThreadPoolExecutor
    from PIL import Image
    from . import entities as entities_module
    from . import preview as preview_module

    colour = np.tile(np.array([[0.80, 0.80, 0.78]]), (len(mesh.faces), 1))
    colour[marked] = [0.13, 0.30, 0.90]

    def survey_one(job):
        index, (camera, direction, _spun) = job
        # The PRESENTATION renderer, not the raw lit buffer. At whole-model
        # scale the lit buffer is a flat silhouette in which a 3mm cone on a
        # 110mm piece has no readable relief, and an agent asked to point at
        # cones it cannot see will point anyway -- which is what naming the
        # same hundred places every round, whatever had already been found,
        # turned out to be. Key/fill/sky over ambient occlusion resolves the
        # individual cones at the same scale and the same framing.
        image = preview_module.render_asset(mesh, colour, direction, size=pixels,
                                            occlusion=occlusion, up=up)
        path = os_module.path.join(out_dir, "overview-%d.png" % index)
        Image.fromarray(image).save(path)
        origins, rays = camera.rays()
        hit = mesh.ray.intersects_first(ray_origins=origins,
                                        ray_directions=rays).reshape(pixels,
                                                                     pixels)
        prompt = DIRECT_PROMPT % (pixels, pixels, intent or "a model", feature,
                                  places, feature, feature, feature)
        key = "direct-%s" % entities_module.digest_of(
            open(path, "rb").read() + prompt.encode("utf-8"))[7:19]
        answer = backend._run([path], prompt, key) or {}
        asked = []
        for entry in answer.get("look", []) or []:
            try:
                x, y = int(entry["x"]), int(entry["y"])
                across = float(entry.get("across", 0) or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= x < pixels and 0 <= y < pixels):
                continue
            face = int(hit[y, x])
            if face < 0:
                continue
            # The agent reports the instance's size in PIXELS of this image;
            # the camera knows how many millimetres a pixel of it is worth.
            across_mm = max(across, 4.0) * camera.footprint_mm
            asked.append((face, across_mm))
        return asked

    with ThreadPoolExecutor(max_workers=workers) as pool:
        asked = [a for batch in pool.map(survey_one, list(enumerate(wide)))
                 for a in batch]
    out = []
    for face, across_mm in asked:
        # Framed at about five instance widths, so what the agent pointed at
        # arrives with its neighbours around it rather than filling the frame.
        camera = _look_at(mesh, np.array([face]), areas, centres, normals,
                          pixels, max(across_mm * 2.5, 1e-6),
                          tilt=tilt, phase=phase)
        if camera is not None:
            out.append((camera, "dir%d-t%d" % (face, int(round(tilt)))))
    log("    directed: %d places named by the overview agent" % len(out))
    return out


def survey(backend, mesh, frame, up, feature, hint, intent, out_dir, tree,
           characteristic, views=6, pixels=900, zoom_tiles=3, workers=8,
           min_votes=2, min_share=0.34, aims=64, max_rounds=8, min_new=2,
           zooms=(1.0,), direct=True, log=print):
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
    occlusion = None
    if direct:
        from . import preview as preview_module
        occlusion = preview_module.ambient_occlusion(mesh, samples=24)
    settled = np.zeros(total, dtype=bool)
    settled[winners] = True
    areas_all = areas
    centres = np.asarray(mesh.triangles_center, dtype=float)
    normals = np.asarray(mesh.face_normals, dtype=float)
    # Every round looks from a different angle and at two framings. A
    # candidate that survived a round is revisited, and revisiting it from
    # the identical camera is not a second look.
    # Small tilts only. A big tilt off the normal gives back exactly the
    # foreshortening the aimed camera exists to remove: measured on the shell,
    # a run whose rounds ran at 26-42 degrees found 5, 5, 5, 3, 2, 2, 3 while
    # the face-on run found 22, 10, 7, 1. The angle should vary enough that a
    # revisit is a new look, and no further.
    angles = ((0.0, 0.0), (12.0, 0.0), (12.0, 2.09), (12.0, 4.19),
              (18.0, 1.05), (18.0, 3.14), (8.0, 5.24), (18.0, 0.52))
    for number in range(1, max_rounds + 1):
        if not len(winners):
            break
        tilt, phase = angles[(number - 1) % len(angles)]
        marked = np.isin(face_node, winners)
        # Two proposers, because they fail differently. The geometric aims
        # can only offer what already resembles the confirmed set, so they
        # walk outward from the index and cannot cross a gap; the overview
        # agent sees the whole piece and says where the index ISN'T.
        aimed = _aim_cameras(mesh, face_node, groups, winners, characteristic,
                             features, areas, pixels, family, limit=aims,
                             tilt=tilt, phase=phase, zooms=zooms)
        if direct:
            aimed += _directed(backend, mesh, frame, wide, marked, feature,
                               intent, out_dir, pixels, areas_all, centres,
                               normals, tilt, phase, workers, up, occlusion,
                               log=log)
        if not aimed:
            log("  round %d: nothing left to aim at; the pool is exhausted"
                % number)
            break
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
        log("  round %d (tilt %.0f deg): %d looks -> %d pass, %d new "
            "(%d indexed)" % (number, tilt, len(more), len(found), len(fresh),
                              len(winners)))
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
