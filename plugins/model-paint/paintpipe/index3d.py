"""Find a feature's every instance by LOOKING, and let the geometry draw the edges.

This is the identify loop. It replaces every synthesised proposal in this
pipeline -- rings grown from a pixel stencil, camera-facing discs, floods
bounded by a crease angle -- and it replaces them for the reason written up as
failure circumstance 9: a synthesised region cannot follow a sculpted margin,
so the confirm gates refused it, correctly, forever. The judges were never the
problem. The proposers were.

Nothing here draws. The pipeline already owns a partition of the surface whose
edges the geometry itself drew -- the base regions of the scale-space index --
and every claim this module makes is a union of them, reached by climbing the
merge tree. A boundary this module returns is therefore a boundary that was
already there before anyone looked.

    a pixel   the agent pointed at    ->  rig.point_to_region
    a region  the point named         ->  a leaf of the merge tree
    a node    the instance really is  ->  climbed to, and confirmed by sight

THREE QUESTIONS, THREE MECHANISMS. THE BOUNDARY QUESTION HAS NO THRESHOLD.

Stated exactly, because the distinction is the whole point: *where* a feature
is and *how big* it is are settled entirely by evidence, and *whether it is
really there* is settled by a vote count and a share, which are thresholds and
are named as such below. Every previous attempt in this project put a number
on the boundary, and the number is what made the boundaries ragged. Putting
one on existence costs a missed instance, which is recoverable and reported;
putting one on extent costs a wrong edge on the print, which is not.

*Where are they?* Asked of many looks -- azimuth, elevation, roll and lighting
all move (see rig.py) -- because one look is an opinion and six that agree are
a measurement. Points land in the shared index, so two views pointing at one
instance produce the same node id with no matching step to get wrong.

*How big is each one?* This is the question every previous attempt answered
with a number, and the number is what made the boundaries ragged. It is
answered here two ways, both of them evidence. First, the agent's own account
of what is separate: two points in ONE image are, by its own listing, two
instances, so a node containing both has merged things the agent saw apart --
that node is too big, and the climb stops below it. Where that rule does not
bind (a lone instance in every view has nothing to be confused with), the
ladder of candidate nodes is RENDERED and the agent picks the rung that
outlines exactly one feature. A climb therefore ends because something was
seen, never because a constant was reached.

*Is it really there?* Consensus, scored honestly: a node's votes are counted
only against the views that could actually have seen it, read off the depth
buffer, so an instance hidden in five looks is judged on the looks where it
showed instead of being punished for the five. `min_votes` and `min_share` ARE
thresholds, and they are the conservative kind -- on the dragon's dorsal
spikes they kept 16 instances and dropped 48 for want of agreement. Every
dropped instance is kept in the survey record with its votes and its share, so
raising the gate is a decision made against numbers rather than a guess.
"""

import json
import os
from collections import defaultdict

import numpy as np

from . import rig as rig_module


def _silent(*_args):
    """A log that says nothing. `log=None` is a caller's right, and guarding
    every call site with `if log:` is how three of them got missed."""


FIND_PROMPT = """This is a %(pixels)dx%(pixels)d rendered view of a 3D model, \
lit %(lighting)s.

The piece: %(intent)s

Find every %(feature)s visible in THIS image. %(hint)s

For each one, give the pixel coordinate of a point ON it, as close to its
centre as you can. x is measured from the left edge, y from the top edge. The
coordinate must land on the feature itself, not near it.

List each instance SEPARATELY. Two points in your list mean two different
things on the model, so do not give two points on one feature, and do not
merge two features into one point.

Reply with ONLY a JSON object, no prose:
{"found": [{"n": 1, "x": <int>, "y": <int>}, ...]}
An empty list is a correct answer if this view shows none."""


LADDER_PROMPT = """These %(count)d images are the SAME view of the same 3D model. \
In each, one candidate region is tinted red over the grey shading.

The piece: %(intent)s

The candidates are nested: each numbered region contains the one before it.
They are candidate extents for a single %(feature)s. %(hint)s

Pick the number whose red region covers exactly ONE COMPLETE %(feature)s --
the whole of it and nothing else. Too small means part of one is still grey;
too big means it has spread onto neighbouring material or swallowed more than
one.

Reply with ONLY a JSON object, no prose:
{"pick": <number>, "why": "<one short sentence>"}
If NO candidate outlines exactly one complete %(feature)s, reply {"pick": 0,
"why": "..."} -- that is a correct and useful answer."""


MULTI_FIND_PROMPT = """This is a %(pixels)dx%(pixels)d rendered view of a 3D model, \
lit %(lighting)s.

The piece: %(intent)s

Find every instance of each of these features that is visible in THIS image:

%(features)s

For each instance, give its feature name exactly as written above and the pixel
coordinate of a point ON it, as close to its centre as you can. x is measured
from the left edge, y from the top edge. The coordinate must land on the
feature itself, not near it.

List each instance SEPARATELY. Two entries with the same name mean two
different things on the model, so do not give two points on one instance, and
do not merge two instances into one point.

Reply with ONLY a JSON object, no prose:
{"found": [{"label": "<feature name>", "x": <int>, "y": <int>}, ...]}
An empty list is a correct answer if this view shows none of them. Leaving a
feature out is a correct answer if this view does not show it."""


class Instance:
    """One confirmed thing: a merge-tree node, its regions, and its support."""

    def __init__(self, node, regions, votes, shown, pose_names, why=""):
        self.node = int(node)
        self.regions = np.asarray(regions, dtype=np.int64)
        self.votes = int(votes)
        self.shown = int(shown)
        self.pose_names = list(pose_names)
        self.why = why

    @property
    def share(self):
        return self.votes / max(self.shown, 1)

    def as_dict(self):
        return {"node": self.node, "regions": int(len(self.regions)),
                "votes": self.votes, "shown": self.shown,
                "share": round(self.share, 3), "why": self.why}


def ask_views(backend, views, feature, hint, intent, workers=4, retries=2,
              log=None):
    """Point at every instance, in every look.

    Returns (clicks, answered). A click is (view index, ordinal, x, y); the
    ordinal matters as much as the coordinate, being the agent's own statement
    that this instance is not that one -- the only instance-separation signal
    here that was not invented by a clustering rule.

    `answered` is the set of views that actually came back, and keeping it is a
    correctness fix rather than bookkeeping. A FAILED CALL AND AN EMPTY ANSWER
    ARE NOT THE SAME CLAIM. Conflating them -- which is what reading a None
    response as "found nothing" does -- lets a transport failure vote: the view
    still counts among those that could have seen the feature, so the share
    drops, and consensus discards an instance that every look which actually
    ran agreed on. Measured on the fixture: six of sixteen calls failed under
    eight workers, and the second eye was dropped at share 0.33 having been
    correctly found by both looks that answered.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    def look(job):
        index, view = job
        prompt = FIND_PROMPT % {"pixels": view.pixels,
                                "lighting": _lighting_words(view.lighting),
                                "intent": intent or "a 3D printed model",
                                "feature": feature, "hint": hint or ""}
        key = "find-%s" % rig_module.digest(os.path.basename(view.path or ""),
                                            prompt)
        answer = None
        for attempt in range(max(1, int(retries) + 1)):
            answer = backend._run([view.path], prompt, key)
            if answer is not None:
                break
            time.sleep(1.5 * (attempt + 1))
        if answer is None:
            return index, None
        out = []
        for entry in answer.get("found", []) or []:
            try:
                x, y = int(entry["x"]), int(entry["y"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append((index, len(out), x, y))
        return index, out

    jobs = list(enumerate(views))
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        results = list(pool.map(look, jobs))
    clicks, answered = [], set()
    for index, group in results:
        if group is None:
            continue
        answered.add(index)
        clicks.extend(group)
    if log:
        counted = [len(g) for _i, g in results if g is not None] or [0]
        lost = len(views) - len(answered)
        log("  %d of %d looks answered%s -> %d points "
            "(per look: min %d, median %d, max %d)"
            % (len(answered), len(views),
               ("; %d FAILED and are excluded from consensus" % lost)
               if lost else "", len(clicks),
               min(counted), int(np.median(counted)), max(counted)))
    return clicks, answered


def ask_views_many(backend, views, features, intent, workers=4, retries=2,
                   log=None):
    """Every missing feature asked of every look, in ONE call per look.

    Surveying features one at a time costs a full set of looks each, and the
    looks are the expensive part -- twelve calls per feature against twelve
    calls for all of them. It is also the better question: asked to find horns
    AND ears in one picture, the agent has to tell them apart, where two
    independent asks let it call the same bump both.

    Returns {feature: [clicks]} and the set of views that answered, so the
    failure accounting of ask_views holds here too -- one failed look is
    missing from every feature's evidence at once, and none of them may treat
    it as a look that saw nothing.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    listed = "\n".join("  - %s%s" % (name, (": " + note) if note else "")
                       for name, note in features)
    names = {name.strip().lower(): name for name, _note in features}

    def look(job):
        index, view = job
        prompt = MULTI_FIND_PROMPT % {
            "pixels": view.pixels, "lighting": _lighting_words(view.lighting),
            "intent": intent or "a 3D printed model", "features": listed}
        key = "multi-%s" % rig_module.digest(os.path.basename(view.path or ""),
                                             prompt)
        answer = None
        for attempt in range(max(1, int(retries) + 1)):
            answer = backend._run([view.path], prompt, key)
            if answer is not None:
                break
            time.sleep(1.5 * (attempt + 1))
        if answer is None:
            return index, None
        out = defaultdict(list)
        for entry in answer.get("found", []) or []:
            try:
                label = str(entry["label"]).strip().lower()
                x, y = int(entry["x"]), int(entry["y"])
            except (KeyError, TypeError, ValueError):
                continue
            # A name the vocabulary never offered is not a find. Inventing a
            # label here is how two stages end up believing in different parts.
            if label not in names:
                continue
            out[names[label]].append((index, len(out[names[label]]), x, y))
        return index, out

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        results = list(pool.map(look, list(enumerate(views))))
    clicks, answered = defaultdict(list), set()
    for index, group in results:
        if group is None:
            continue
        answered.add(index)
        for name, found in group.items():
            clicks[name].extend(found)
    if log:
        lost = len(views) - len(answered)
        log("  %d of %d looks answered%s; points per feature: %s"
            % (len(answered), len(views),
               ("; %d FAILED and are excluded from consensus" % lost)
               if lost else "",
               ", ".join("%s=%d" % (name, len(clicks.get(name, [])))
                         for name, _n in features) or "none"))
    return clicks, answered


def _lighting_words(name):
    return {"flat": "evenly, with no shadows",
            "studio": "with a soft key light from the upper right",
            "raking_l": "with a hard light grazing from the left, so relief "
                        "throws shadow",
            "raking_t": "with a hard light grazing from above, so relief "
                        "throws shadow",
            "raking_tr": "with a hard light grazing from the upper right, so "
                         "relief throws shadow"}.get(name, name)


def resolve(clicks, views, tree, base):
    """Points -> base regions, deduplicated per view.

    Two points from one view landing in one region is the agent contradicting
    itself -- it listed them as separate instances and they are the same place.
    The honest reading is one instance, so the duplicate is dropped rather than
    counted twice as agreement.
    """
    seen, resolved, missed = set(), [], 0
    for view_index, ordinal, x, y in clicks:
        pose = views[view_index].pose
        region = rig_module.point_to_region(pose, base, x, y)
        if region < 0:
            missed += 1
            continue
        key = (view_index, region)
        if key in seen:
            continue
        seen.add(key)
        resolved.append({"view": view_index, "pose": pose.name,
                         "ordinal": ordinal, "region": int(region),
                         "x": int(x), "y": int(y)})
    return resolved, missed


def climb(resolved, tree):
    """How big is each instance? Climb until the agent's own separation says stop.

    Every point is walked up the merge tree. A node that holds two points from
    ONE view has merged two things that view listed separately, so the climb
    stops strictly below it. Nothing here is compared against a size, an area
    share or a characteristic radius: the stopping rule is another look's
    testimony, which is the only thing on hand that knows where one instance
    ends and the next begins.

    Returns {point index: node} and the ladder each point could still have
    climbed, which is what the confirm pass is offered when this rule never
    binds -- a lone instance has nothing to be confused with, so nothing stops
    it, and without the ladder it would climb to the root and swallow the model.
    """
    chains = {}
    for point in resolved:
        region = point["region"]
        if region not in chains:
            chains[region] = rig_module.ancestors(tree, region)

    holders = defaultdict(list)
    for index, point in enumerate(resolved):
        for node in chains[point["region"]]:
            holders[node].append(index)

    stopped, ladders = {}, {}
    for index, point in enumerate(resolved):
        chain = chains[point["region"]]
        best, rungs = chain[0], [chain[0]]
        for node in chain[1:]:
            views_here = [resolved[j]["view"] for j in holders[node]]
            if len(views_here) != len(set(views_here)):
                break            # this node merges two instances one view kept apart
            best = node
            rungs.append(node)
        stopped[index] = int(best)
        ladders[index] = rungs
    return stopped, ladders, chains


def fuse_nested(groups, tree):
    """Groups whose nodes nest are one instance described at two granularities.

    Two looks at one spike land on different base regions of it, and if their
    climbs stop at different rungs the survey ends up holding the same spike
    twice -- as a node and as something inside that node -- with the evidence
    for it split between them. Neither half then clears consensus, and the
    spike is lost for having been seen too WELL.

    Fusing keeps the outermost node, because that is the rung the ladder
    judged to be one whole feature; the inner ones are parts of it. Nodes that
    do not nest are left alone: two spikes side by side share no ancestor
    below the body, and nothing here merges them.
    """
    if not groups:
        return dict(groups)
    nodes = sorted(groups, key=lambda n: -len(rig_module.node_regions(tree, n)))
    holder = {}
    for node in nodes:
        chain = set(rig_module.ancestors(tree, int(node)))
        target = node
        for other in nodes:
            if other == node:
                continue
            # `other` is outside `node` when it sits on node's ancestor chain.
            if int(other) in chain:
                target = holder.get(other, other)
                break
        holder[node] = target

    fused = defaultdict(set)
    for node, members in groups.items():
        fused[holder.get(node, node)].update(members)
    return dict(fused)


def nearest_by_area(rungs, areas, typical):
    """The rung whose area is closest to `typical`, compared as a RATIO.

    Log-ratio rather than difference, because these sizes differ by factors:
    a spike is a spike whether it is 4mm2 or 40, and a rung twice the target
    is exactly as wrong as one half of it. Absolute difference would make
    every large rung look equally bad and pick the smallest.
    """
    return int(min(rungs, key=lambda r: abs(np.log(
        max(float(areas[int(r)]), 1e-9) / max(float(typical), 1e-9)))))


def _framed_pose(mesh, tree, wide, regions, pixels=420, context=2.5):
    """A close pose on one candidate, looking from where it is already visible.

    The direction is borrowed from the wide pose that sees the candidate best,
    so the close look cannot land on the far side of the model -- the framing
    changes, the vantage does not.
    """
    from . import render as render_module

    faces = np.flatnonzero(rig_module.face_mask(tree, regions))
    centres = mesh.triangles[faces].mean(axis=1)
    centre = centres.mean(axis=0)
    spread = float(np.linalg.norm(np.ptp(centres, axis=0))) / 2.0
    whole = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0
    radius = float(np.clip(spread * context, whole * 0.02, whole * 1.06))
    camera = render_module.Camera(wide.camera.forward, wide.camera.up, centre,
                                  radius, pixels)
    return rig_module.Pose("%s-zoom" % wide.name, camera,
                           render_module.geometry_bundle(mesh, camera,
                                                         cavity_taps=0))


def confirm_ladder(backend, mesh, tree, poses, rungs, feature, hint, intent,
                   out_dir, tag, pixels=420, max_rungs=5, log=None):
    """Render the candidate extents and let the agent pick the right one.

    This is what stands where a threshold used to. The rungs are nested nodes
    of the merge tree, so every option already has a real boundary; the only
    open question is which of them is one whole feature, and that is a question
    about appearance, so it is asked of something that can look.

    Returns the chosen node, or None when the agent says none of them is one
    complete feature -- a refusal that is kept as a refusal instead of being
    rounded to the nearest candidate.
    """
    if not rungs:
        return None, "no candidates"
    # Spread the ladder when it is long: adjacent rungs of a deep chain differ
    # by a sliver, and five near-identical pictures is not a choice.
    chosen_rungs = list(rungs)
    if len(chosen_rungs) > max_rungs:
        picks = np.linspace(0, len(chosen_rungs) - 1, max_rungs)
        chosen_rungs = [chosen_rungs[int(round(p))] for p in picks]
        seen, unique = set(), []
        for node in chosen_rungs:
            if node not in seen:
                seen.add(node)
                unique.append(node)
        chosen_rungs = unique

    region_sets = [rig_module.node_regions(tree, node) for node in chosen_rungs]
    wide, count = rig_module.best_pose(poses, tree, region_sets[-1])
    if wide is None or count < 8:
        return None, "invisible from every pose"

    # FRAME ON THE CANDIDATE, DO NOT JUDGE IT FROM THE WIDE VIEW. On the dragon
    # a whole-model tile puts a dorsal spike at a few pixels across, and a gate
    # asked whether that has spread onto its neighbour cannot see the answer --
    # it is being asked to read a boundary it was never shown. The zoom is a
    # real camera move (rays recast at the same resolution), and it keeps
    # roughly 2.5x the candidate's own extent in frame so "spread onto
    # neighbouring material" stays a visible question rather than a guess.
    pose = _framed_pose(mesh, tree, wide, region_sets[-1], pixels=pixels)
    shaded = rig_module.light(pose, "studio")
    images = []
    for regions in region_sets:
        mask = rig_module.face_mask(tree, regions)
        images.append(rig_module.highlight_image(pose, shaded, mask))
    path = os.path.join(out_dir, "ladder-%s.png" % tag)
    rig_module.sheet(images, [str(i + 1) for i in range(len(images))], path,
                     columns=min(3, len(images)))

    prompt = LADDER_PROMPT % {"count": len(images),
                              "intent": intent or "a 3D printed model",
                              "feature": feature, "hint": hint or ""}
    key = "ladder-%s" % rig_module.digest(os.path.basename(path), prompt)
    answer = backend._run([path], prompt, key) or {}
    try:
        pick = int(answer.get("pick", 0))
    except (TypeError, ValueError):
        pick = 0
    why = str(answer.get("why", ""))[:200]
    if pick < 1 or pick > len(chosen_rungs):
        return None, why or "refused"
    return int(chosen_rungs[pick - 1]), why


def score(nodes, poses, views, tree, base, answered=None, min_pixels=6):
    """Votes against the looks that could actually have seen each node.

    Visibility comes off the depth buffer, so it is exact rather than inferred
    from a normal, and `shown` counts views (every lighting of a pose shares
    that pose's occlusion, so numerator and denominator scale together and the
    share stays a fraction of comparable looks).

    `answered` restricts the denominator to views that actually returned an
    answer. A view whose call failed saw nothing and said nothing, and it is
    not evidence of absence -- counting it as a look that "could have seen"
    the node makes every share too harsh in exact proportion to how unreliable
    the transport was that day.
    """
    seen_regions = {}
    for pose in poses:
        regions, counts = rig_module.visible_regions(pose, base,
                                                     min_pixels=min_pixels)
        seen_regions[pose.name] = set(int(r) for r in regions)
    per_pose_views = defaultdict(int)
    for index, view in enumerate(views):
        if answered is not None and index not in answered:
            continue
        per_pose_views[view.pose.name] += 1

    out = {}
    for node in nodes:
        regions = set(int(r) for r in rig_module.node_regions(tree, node))
        shown = 0
        for pose in poses:
            if regions & seen_regions[pose.name]:
                shown += per_pose_views[pose.name]
        out[int(node)] = shown
    return out


def survey(backend, mesh, tree, views, poses, feature, hint, intent, out_dir,
           min_votes=2, min_share=0.30, workers=4, confirm=True, log=print):
    """The whole identify loop for ONE feature: look, resolve, climb, confirm, agree.

    Returns (unit, instances, report). `unit` is a per-face instance id, -1
    where nothing was found; its boundaries are merge-tree node boundaries and
    therefore the geometry's own.
    """
    os.makedirs(out_dir, exist_ok=True)
    clicks, answered = ask_views(backend, views, feature, hint, intent,
                                 workers=workers, log=log)
    return settle(backend, mesh, tree, views, poses, clicks, answered, feature,
                  hint, intent, out_dir, min_votes=min_votes,
                  min_share=min_share, confirm=confirm, workers=workers,
                  log=log)


def survey_many(backend, mesh, tree, views, poses, features, intent, out_dir,
                min_votes=2, min_share=0.30, workers=4, confirm=True,
                log=print):
    """Several features, one set of looks. Returns {feature: (unit, instances, report)}.

    The looks are what cost money and time, so they are shared; everything
    after them is per-feature and independent.
    """
    log = log or _silent
    os.makedirs(out_dir, exist_ok=True)
    clicks, answered = ask_views_many(backend, views, features, intent,
                                      workers=workers, log=log)
    out = {}
    for name, note in features:
        if log:
            log("  %s:" % name)
        out[name] = settle(backend, mesh, tree, views, poses,
                           clicks.get(name, []), answered, name, note, intent,
                           out_dir, min_votes=min_votes, min_share=min_share,
                           confirm=confirm, workers=workers, log=log)
    return out


def settle(backend, mesh, tree, views, poses, clicks, answered, feature, hint,
           intent, out_dir, min_votes=2, min_share=0.30, confirm=True,
           workers=4, confirm_cap=24, log=print):
    """Points -> instances: resolve, climb, confirm by sight, then agree.

    Split out from `survey` so that one shared set of looks can settle many
    features (see `survey_many`) without asking for the pictures again.
    """
    # Owns its directory rather than trusting a caller to have made it: the
    # ladder sheets are written from inside the confirm pool, where a missing
    # directory surfaces as a thread exception halfway through a survey that
    # has already been paid for.
    log = log or _silent
    os.makedirs(out_dir, exist_ok=True)
    base = rig_module.region_of_face(tree)
    resolved, missed = resolve(clicks, views, tree, base)
    if log:
        log("  %d points land on the surface (%d missed it), in %d regions"
            % (len(resolved), missed,
               len(set(p["region"] for p in resolved))))
    if not resolved:
        return (np.full(len(mesh.faces), -1, dtype=np.int64), [],
                {"feature": feature, "points": 0, "instances": 0,
                 "answered": len(answered), "looks": len(views),
                 "reason": "nothing pointed at"})

    stopped, ladders, _chains = climb(resolved, tree)

    # Points that stopped at the same node are the same instance -- fused with
    # no matching step, which is the entire reason the index is global.
    grouped = defaultdict(list)
    for index, node in stopped.items():
        grouped[node].append(index)

    # Where the separation rule never bound, the climb is open-ended and the
    # ladder decides. "Never bound" is exactly: the point could have kept
    # climbing, i.e. its ladder still has rungs above where it stopped.
    settled, notes = {}, {}
    if confirm:
        # THE CLIMB GIVES AN UPPER BOUND, NEVER A LOWER ONE. It stops below the
        # first node that merges two instances one view kept apart, so the
        # instance is somewhere in [the clicked region, the climbed node] -- and
        # where no view contradicted it, the climbed node can be most of the
        # model. The ladder's job is to choose within that interval, so a group
        # whose climb never left its own region has nothing to choose and needs
        # no picture; every other group does.
        #
        # They are bought in parallel: independent questions about different
        # parts of the model, and asking sixty of them one after another was
        # most of the wall clock of a survey.
        climbed, ordered = [], sorted(grouped.items(),
                                      key=lambda kv: -len(kv[1]))
        for node, members in ordered:
            if len(ladders[members[0]]) <= 1:
                settled[node] = node
            else:
                climbed.append((node, members))
        capped = []
        if len(climbed) > confirm_cap:
            log("  %d climbs to settle; confirming the %d best supported by "
                "sight and sizing the rest from what they confirm"
                % (len(climbed), confirm_cap))
            capped = climbed[confirm_cap:]
            climbed = climbed[:confirm_cap]

        def _confirm(job):
            node, members = job
            return node, confirm_ladder(
                backend, mesh, tree, poses, ladders[members[0]], feature, hint,
                intent, out_dir,
                tag="%s-%d" % (rig_module.digest(feature)[:6], node), log=log)

        if climbed:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
                for node, (picked, why) in pool.map(_confirm, climbed):
                    if picked is None:
                        notes[node] = why
                        continue
                    settled[node] = picked
                    notes[picked] = why

        if capped:
            # Instances of one repeating feature are the same kind of thing, so
            # the size the agent CONFIRMED on this model is the best evidence
            # available about the size of the ones it was not shown. Each
            # remaining group takes the rung of its own ladder closest in area
            # to that median -- its own boundary, at a size that was measured
            # rather than assumed. Falling back to the climbed node instead
            # would take the upper bound every time, which is exactly the
            # over-merge the ladder exists to prevent.
            areas = np.asarray(tree["area"], dtype=float)
            picked_areas = [float(areas[int(v)]) for v in settled.values()
                            if int(v) < len(areas)]
            if picked_areas:
                typical = float(np.median(picked_areas))
                for node, members in capped:
                    settled[node] = nearest_by_area(ladders[members[0]],
                                                    areas, typical)
                log("  sized %d unconfirmed group(s) at the confirmed median "
                    "of %.1f mm2" % (len(capped), typical))
            else:
                for node, _members in capped:
                    settled[node] = node
    else:
        settled = {node: node for node in grouped}

    # Re-group: two climbs confirmed onto one node are one instance.
    merged = defaultdict(set)
    for node, picked in settled.items():
        for index in grouped[node]:
            merged[picked].add(index)

    # AND A NODE INSIDE ANOTHER NODE IS THE SAME INSTANCE, SEEN LESS WELL.
    # Without this, buying more looks makes recall WORSE, which is the
    # opposite of what more evidence should do. Measured on the dragon: 12
    # looks gave 66 climbs and 16 spikes, and 24 looks gave 110 climbs and
    # only 12, because every extra look adds points that land on new regions
    # of a spike the survey already had. More points per view also make the
    # separation rule bite lower -- two points in one image stop a climb, and
    # there are more such pairs -- so groups come out smaller, more numerous,
    # and individually too thinly supported to clear consensus.
    #
    # The fix is not a looser gate. It is that these groups were never
    # different things: a node and its own ancestor are one feature described
    # at two granularities, so they are fused, keeping the outermost, which is
    # the one the ladder judged to be a whole feature.
    fused = fuse_nested(merged, tree)
    if log and len(fused) != len(merged):
        log("  %d groups fused into %d: nested nodes are one instance seen "
            "at two granularities" % (len(merged), len(fused)))
    merged = fused

    shown = score(list(merged), poses, views, tree, base, answered=answered)
    instances = []
    for node, members in merged.items():
        voting_views = set(resolved[i]["view"] for i in members)
        instance = Instance(node, rig_module.node_regions(tree, node),
                            votes=len(voting_views), shown=shown.get(node, 0),
                            pose_names=sorted(set(resolved[i]["pose"]
                                                  for i in members)),
                            why=notes.get(node, ""))
        instances.append(instance)

    kept = [i for i in instances
            if i.votes >= min_votes and i.share >= min_share]
    keep_ids = {id(i) for i in kept}
    # A node seen in exactly one look, pointed at in that one look, is not
    # evidence -- but neither is it a lie. It is recorded and dropped, so a
    # feature that only ever showed once is visible in the report rather than
    # silently absent.
    dropped = [i for i in instances if id(i) not in keep_ids]

    unit = np.full(len(mesh.faces), -1, dtype=np.int64)
    for number, instance in enumerate(sorted(kept, key=lambda i: -len(i.regions))):
        unit[rig_module.face_mask(tree, instance.regions)] = number

    report = {"feature": feature, "points": len(resolved), "missed": missed,
              "looks": len(views), "answered": len(answered),
              "failed_looks": len(views) - len(answered),
              "climbed": len(grouped), "confirmed": len(merged),
              "instances": len(kept), "dropped": len(dropped),
              "faces": int((unit >= 0).sum()),
              "kept_detail": [i.as_dict() for i in
                              sorted(kept, key=lambda i: -len(i.regions))],
              "dropped_detail": [i.as_dict() for i in dropped]}
    if log:
        log("  %d points -> %d climbed -> %d confirmed -> %d instances "
            "(%d dropped for want of agreement), %d faces"
            % (len(resolved), len(grouped), len(merged), len(kept),
               len(dropped), int((unit >= 0).sum())))
    with open(os.path.join(out_dir, "survey-%s.json"
                           % rig_module.digest(feature)[:8]), "w") as handle:
        json.dump(report, handle, indent=2)
    return unit, sorted(kept, key=lambda i: -len(i.regions)), report
