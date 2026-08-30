"""Ask what the parts ARE, then find them. Not: divide the mesh, then ask what fell out.

This inverts the order every previous attempt used, and the inversion is the
whole fix. Dividing first and asking afterwards means the agent can only name
the pieces the division happened to produce -- so when an area-greedy split of
a dragon's head produced skull, brow lump, snout, knob and bump, the two horns
at the top-rear were never offered, and no amount of naming, voting, mirroring
or consensus could reach them. They were not in the list.

Asked plainly of a clean render instead, the same model answers in one call:
two horns, top-rear left and right, and the cones behind the skull are neck
spikes not horns. The seeing was never the problem. The division was.

So:

    1. IDENTIFY   clean renders, no colours, no numbers, no division:
                  "what parts does this piece have, and how many of each?"
    2. LOCATE     for each named part, point at it in the views that show it
    3. SIZE       show candidate extents around each point and let the agent
                  pick the one that is that whole part and nothing else
    4. CORRECT    paint what was found, show it, ask what is wrong or missing,
                  and go round again

NOTHING HERE IS SPECIFIC TO A MODEL. There is no symmetry assumption -- that
was a crutch that worked on a mirror-symmetric head and did nothing for a
posed limb or a scattered texture. There is no size constant: every camera is
framed on the thing being asked about, so a 4mm eye and a 190mm body are both
judged at the same apparent size, and the only physical quantity that enters
anywhere is the nozzle width, because that is a real fact about the printer
rather than a fact about this model.
"""

import json
import os

import numpy as np

from . import rig as rig_module


IDENTIFY = """This picture shows %(count)d views of the same 3D model, plainly shaded, laid
out side by side and labelled "view 0", "view 1" and so on.

The piece: %(intent)s

List the distinct PARTS this model has -- the things a painter would want to
give their own colour. For each, say how many of it there are and where it
sits, in plain words.

Judge only from what you can see. Do not list a part because the subject
usually has one; do not merge two different things into one entry; and if
several things are really one repeating family (a row of spikes, a field of
barnacles), give that ONE entry with the count.

Reply with ONLY a JSON object, no prose:
{"parts": [{"name": "<short name>", "count": <int or 0 if many>,
            "where": "<where it sits, plainly>"}, ...]}"""


POINT = """This is view %(index)d of a 3D model, plainly shaded.

The piece: %(intent)s

Find: %(name)s -- %(where)s

Give the pixel coordinate of a point ON each one you can see in THIS view. x
from the left edge, y from the top. If this view does not show it, reply with
an empty list -- that is a correct answer and better than a guess.

Reply with ONLY a JSON object, no prose:
{"found": [{"x": <int>, "y": <int>}, ...]}"""


CRITIQUE = """The LEFT images are a 3D model plainly shaded. The RIGHT images are
the same views with the current colouring applied.

The piece: %(intent)s

The parts that have been coloured so far:
%(legend)s

Look at what is coloured against what is actually there, and report only what
is WRONG:

  "missing"  -- something that should have been coloured as one of the parts
                above but is left plain
  "wrong"    -- something coloured as a part that is not that part
  "partial"  -- a part coloured on only some of itself

For anything missing or partial, give a pixel coordinate on it and say which
view, so it can be found. Say nothing about colour choice; only about whether
the right SURFACE is claimed.

Reply with ONLY a JSON object, no prose:
{"problems": [{"kind": "missing|wrong|partial", "part": "<name>",
               "view": <int>, "x": <int>, "y": <int>, "why": "<short>"}, ...]}
An empty list means the colouring matches what you can see."""


def survey_views(mesh, up, out_dir, pixels=760, count=4, log=None):
    """Plain shaded views of the whole piece. No colour, no numbers, no division.

    This is the picture a person is actually looking at when they say "it has
    two horns", and until now nothing in the pipeline ever showed it and asked
    that question.
    """
    os.makedirs(out_dir, exist_ok=True)
    from . import preview

    directions = preview.orbit(count, 28.0, up=up)
    poses = rig_module.poses_from(mesh, directions, up, pixels=pixels)
    paths, images = [], []
    for index, pose in enumerate(poses):
        image = rig_module.light(pose, "studio")
        path = os.path.join(out_dir, "look-%d.png" % index)
        rig_module.write_png(image, pose.visible, path)
        paths.append(path)
        canvas = np.full(image.shape, 0.97)
        canvas[pose.visible] = image[pose.visible]
        images.append(canvas)

    # ONE file, not N. Handing the agent four separate paths makes it open four
    # files, and measured here that turned a question answering in a couple of
    # minutes into one that had not returned in fifteen. The views are the same
    # views; they just arrive as a single picture.
    sheet = os.path.join(out_dir, "views.png")
    rig_module.sheet(images, ["view %d" % i for i in range(len(images))],
                     sheet, columns=min(len(images), 4))
    if log:
        log("  %d plain views for identification, as one sheet" % len(paths))
    return sheet, paths, poses


def identify(backend, mesh, up, intent, out_dir, count=4, pixels=760,
             log=print):
    """What parts does this piece have? One ask, on pictures of the thing itself."""
    sheet, paths, poses = survey_views(mesh, up, out_dir, pixels=pixels,
                                       count=count, log=log)
    prompt = IDENTIFY % {"count": len(paths),
                         "intent": intent or "a 3D printed model"}
    with open(sheet, "rb") as handle:
        digest = rig_module.digest(handle.read(), intent)
    answer = backend._run([sheet], prompt, "identify-%s" % digest)
    parts = []
    for entry in (answer or {}).get("parts", []) or []:
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        try:
            howmany = int(entry.get("count", 0))
        except (TypeError, ValueError):
            howmany = 0
        parts.append({"name": name, "count": howmany,
                      "where": str(entry.get("where", "")).strip()})
    if log:
        for part in parts:
            log("    %-34s x%-4s %s" % (part["name"],
                                        part["count"] or "many",
                                        part["where"][:60]))
    return parts, paths, poses


def point_at(backend, poses, paths, part, intent, workers=3, log=None):
    """Where is this NAMED part? Asked of each view, with the name in hand.

    Pointing at a thing you have been told to look for is a far easier task
    than finding every instance of an unnamed feature, which is what the old
    survey asked. The name and its stated position come from step 1, so this
    call is a lookup rather than a discovery.
    """
    from concurrent.futures import ThreadPoolExecutor

    def look(job):
        index, path = job
        prompt = POINT % {"index": index, "intent": intent or "a 3D model",
                          "name": part["name"], "where": part["where"]}
        with open(path, "rb") as handle:
            digest = rig_module.digest(handle.read(), part["name"])
        answer = backend._run([path], prompt, "point-%s" % digest)
        if answer is None:
            return index, None
        out = []
        for entry in answer.get("found", []) or []:
            try:
                out.append((int(entry["x"]), int(entry["y"])))
            except (KeyError, TypeError, ValueError):
                continue
        return index, out

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        results = list(pool.map(look, list(enumerate(paths))))
    hits, answered = [], 0
    for index, found in results:
        if found is None:
            continue
        answered += 1
        for x, y in found:
            hits.append((index, x, y))
    if log:
        log("    %s: %d point(s) from %d/%d views"
            % (part["name"], len(hits), answered, len(paths)))
    return hits


def field_from(tree, claims, face_count):
    """Per-face labels from {name: regions}. Later claims refine earlier ones."""
    out = np.full(face_count, -1, dtype=np.int64)
    labels = []
    for name, regions in claims.items():
        if not len(regions):
            continue
        out[rig_module.face_mask(tree, regions)] = len(labels)
        labels.append(name)
    return out, labels


def report(parts, claims, tree, path):
    """What was asked for, what was found, and what was not. Written every run."""
    rows = []
    for part in parts:
        regions = claims.get(part["name"])
        rows.append({"name": part["name"], "asked": part["count"] or "many",
                     "where": part["where"],
                     "regions": int(len(regions)) if regions is not None else 0,
                     "found": bool(regions is not None and len(regions))})
    with open(path, "w") as handle:
        json.dump({"parts": rows}, handle, indent=2)
    return rows


def locate(backend, mesh, tree, poses, paths, part, intent, out_dir,
           workers=3, confirm=True, log=print):
    """Find one NAMED part on the surface. Points -> regions -> confirmed extent.

    The sizing is the ladder from index3d: candidate extents around each point,
    rendered framed on the candidate, and the agent picks the one that is that
    whole part and nothing else. Nothing is voted on and nothing is gated -- a
    point that was made is a point that counts, because the name came from
    looking at the piece rather than from a guess about a feature.
    """
    from . import index3d

    base = rig_module.region_of_face(tree)
    hits = point_at(backend, poses, paths, part, intent, workers=workers,
                    log=log)
    if not hits:
        return np.array([], dtype=np.int64), 0

    seen, regions = set(), []
    for index, x, y in hits:
        region = rig_module.point_to_region(poses[index], base, x, y)
        if region < 0 or region in seen:
            continue
        seen.add(region)
        regions.append(region)
    if not regions:
        return np.array([], dtype=np.int64), 0

    claimed = set()
    for region in regions:
        # THE WHOLE CHAIN, leaf to root. Truncating to the first six ancestors
        # caps the largest extent the agent is allowed to choose, so a big part
        # can never be picked: on the shell that gave "shell body" -- most of
        # the model -- four regions out of 9626, because six rungs up from a
        # 65-face leaf is still tiny. confirm_ladder spreads a long chain into
        # a handful of well-separated rungs itself, so handing it everything
        # costs nothing and lets one mechanism size a barnacle and a shell.
        ladder = rig_module.ancestors(tree, int(region))
        if len(ladder) <= 1 or not confirm:
            claimed.update(int(r) for r in
                           rig_module.node_regions(tree, ladder[0]))
            continue
        node, _why = index3d.confirm_ladder(
            backend, mesh, tree, poses, ladder, part["name"],
            part["where"], intent, out_dir,
            tag="%s-%d" % (rig_module.digest(part["name"])[:6], region),
            log=None)
        chosen = node if node is not None else ladder[0]
        claimed.update(int(r) for r in rig_module.node_regions(tree, chosen))
    out = np.asarray(sorted(claimed), dtype=np.int64)
    if log:
        log("    %-32s %d point(s) -> %d region(s)"
            % (part["name"], len(regions), len(out)))
    return out, len(regions)


def run(backend, mesh, tree, up, intent, out_dir, views=4, workers=3,
        max_parts=8, log=print):
    """identify -> locate every named part -> a label field. The whole method."""
    os.makedirs(out_dir, exist_ok=True)
    parts, paths, poses = identify(backend, mesh, up, intent, out_dir,
                                   count=views, log=log)
    claims = {}
    for part in parts[:max_parts]:
        regions, points = locate(backend, mesh, tree, poses, paths, part,
                                 intent, out_dir, workers=workers, log=log)
        if len(regions):
            claims[part["name"]] = regions
    field, labels = field_from(tree, claims, len(mesh.faces))
    report(parts, claims, tree, os.path.join(out_dir, "found.json"))
    if log:
        painted = int((field >= 0).sum())
        log("  %d/%d parts located; %d faces claimed (%.1f%% of surface)"
            % (len(claims), len(parts), painted,
               100.0 * painted / len(mesh.faces)))
    return field, labels, parts, claims, poses, paths
