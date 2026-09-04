"""Take the MOTION out of a generated animation and leave the pixels behind.

Every generative route tried on this branch ships the model's pixels and so
inherits the model's drift: measured on the corpus knight, a clip that asks for
real movement comes back with 89 to 442 of a ~500-pixel silhouette changed. The
character is a lookalike. Conforming fixes the palette and cannot fix that,
because the shape is wrong, not the colour.

Mixamo does not have this problem, and the reason is structural rather than
technical: it never ships the motion-capture actor's body. It ships YOUR
character, moved by a skeleton fitted to the capture. The motion and the
character are separable, and only the motion is worth generating.

So: generate an animation once, then SOLVE for the rig pose that best explains
each frame, and throw the generated pixels away. What ships is this project's own
cutout renderer driving the user's own art -- byte-exact rest pose, palette a
provable subset, identity untouched by construction rather than by measurement.
The model contributes a table of angles.

Two consequences worth the work on their own:

* **A fitted clip is reusable.** The knight's walk, once solved, is a
  `motion.Animation` like any hand-authored one, and drives every other rig in
  the corpus. That is a motion LIBRARY built by generation rather than a
  generation step in every user's build, which is also most of the cost gone.
* **It cannot fail unsafely.** A bad fit is a bad animation of the right
  character. Every other generative route fails by handing back the wrong
  character, which is worse and much harder to notice.

The solve is coordinate descent over pose channels, scored by silhouette
agreement, walking the rig parents-first so a child is fitted against a parent
that has already stopped moving.
"""

import numpy as np

from . import image as img
from . import motion as motion_module
from . import render as render_module
from . import skeleton

# Channels searched per part, and the span searched over. Angles dominate --
# a limb rotates about its joint -- and the translations pick up what a rigid
# rotation cannot reach.
# (channel, half-width, samples) per refinement pass. Coarse first over the whole
# plausible range, then narrow around whatever that found -- a full fine sweep of
# every channel is four times the renders for the same answer, and the fit is
# thousands of renders either way.
# What a part is ALLOWED to do, by role. Without this the solve contorts whatever
# part buys the most silhouette overlap, which is the biggest one -- fitting an
# exaggerated walk on the corpus knight, it rotated the HEAD forty degrees and
# smeared it across the chest, because a head is a large blob and moving a large
# blob covers more target than moving a leg. The result fits at 0.78 and is not a
# walk. A neck does not do that, and the rig should not either.
LIMITS = {
    # A head is a face. At 32px it is a dozen pixels of visor slit or eye, and
    # ANY rotation nearest-neighbour can draw smears them: three and a half
    # degrees turned the corpus knight's "|||" visor into "\\\". Swept against
    # an exaggerated walk, dropping the head from 14 degrees to 4 costs 0.01 of
    # silhouette agreement -- 0.66 worst-frame against 0.65 -- and keeps the face
    # legible, which is the thing a player is actually looking at.
    "head": 4.0, "torso": 8.0, "body": 8.0,
    "arm_near": 85.0, "arm_far": 85.0,
    "leg_near": 50.0, "leg_far": 50.0,
    "tail": 45.0, "wing_near": 60.0, "wing_far": 60.0,
    "accessory": 40.0, "prop": 90.0,
}
DEFAULT_LIMIT = 40.0

# And how far it may SLIDE, in pixels of the authored 32px character. Left
# unconstrained the solve translates whatever helps: fitting an exaggerated walk
# on the corpus knight it lifted the ROOT seven pixels -- a quarter of the
# character's height -- while translating the head five pixels down to cancel it.
# Two channels fighting each other to explain the video's own camera drift.
#
# A head does not slide on its neck; that is what the neck's rotation is for. A
# hand may, because an arm reaching is mostly translation at this scale.
SHIFTS = {
    "head": 0.6, "torso": 1.2, "body": 1.2,
    "arm_near": 3.5, "arm_far": 3.5,
    "leg_near": 2.5, "leg_far": 2.5,
    "prop": 4.0,
}
DEFAULT_SHIFT = 2.5

# A clip captured in place should not walk out of frame. The root carries the
# character's bob, which is one or two pixels, not seven.
ROOT_SHIFT = 2.5

# How much a pose is charged for departing from rest, as a fraction of the
# agreement it buys. Among poses that fit equally well, prefer the one that moved
# least -- otherwise the solve spends its freedom wherever it happens to help
# first, and a still limb picks up motion it never had.
TIDINESS = 0.06

SWEEPS = (("angle", 38.0), ("dy", 3.0), ("dx", 3.0))
ROOT_SWEEPS = (("dy", 4.0), ("dx", 4.0))
PASSES = ((9, 1.0), (7, 0.28))


def _span(centre, half, count, limit=None):
    values = np.linspace(centre - half, centre + half, int(count))
    if limit is not None:
        values = np.clip(values, -abs(limit), abs(limit))
    return values


def limit_for(part):
    """How far this part's role permits it to turn."""
    return LIMITS.get(part.role, DEFAULT_LIMIT)


def shift_for(part, height=32.0, authored=32.0):
    """How far this part's role permits it to slide, scaled to the character.

    In pixels of the 32px character the numbers were measured on, so a 64px
    sprite gets twice the allowance and a 16px one half -- a pixel means a
    different amount of body on each.
    """
    return SHIFTS.get(part.role, DEFAULT_SHIFT) * (height / float(authored))


def effort(rig, pose):
    """How far a pose departs from rest, as a share of what each part is allowed.

    Charged against the fit so that among poses which explain the target equally
    well, the tidiest wins. Scaled per part by its own limit, so a leg swinging
    40 degrees of its permitted 50 is not judged more extravagant than a head
    turning 12 of its permitted 14.
    """
    total, count = 0.0, 0
    for part in rig.parts:
        own = pose.parts.get(part.name)
        if own is None:
            continue
        allowed = limit_for(part)
        slide = shift_for(part, rig.size[1])
        total += abs(own.angle) / allowed if allowed else 0.0
        total += (abs(own.dx) + abs(own.dy)) / max(1e-6, slide)
        count += 1
    return (total / count) if count else 0.0


def agreement(ours, target):
    """Intersection over union of two silhouettes. 1.0 is a perfect fit.

    Silhouette rather than colour, because the generated frame's colours have
    already drifted and its SHAPE is the only part carrying the motion. This is
    also what makes the fit transferable: a shape agreement says where the limbs
    went, and says nothing about who the character was.
    """
    overlap = int((ours & target).sum())
    union = int((ours | target).sum())
    # Two empty silhouettes agree perfectly. Returning 0 there says a frame that
    # rendered nothing disagrees with a target that is nothing, which makes the
    # solve chase a difference that does not exist.
    return (overlap / float(union)) if union else 1.0


def _mask_of(cutout, pose, margin, shape):
    frame = render_module.render_pose(cutout, pose, margin=margin)
    out = np.zeros(shape, dtype=bool)
    mask = img.alpha_mask(frame)
    rows = min(shape[0], mask.shape[0])
    columns = min(shape[1], mask.shape[1])
    out[:rows, :columns] = mask[:rows, :columns]
    return out


def fit_pose(cutout, target, margin, start=None, passes=PASSES,
             tidiness=TIDINESS):
    """The rig pose that best explains one target silhouette.

    Coordinate descent, parents before children. A child is searched against a
    parent that has already settled, which is the same order `world_transforms`
    composes in and the reason a shoulder does not have to be re-solved every
    time the hand moves.
    """
    rig = cutout.rig
    pose = start if start is not None else skeleton.Pose()
    shape = target.shape
    # Skinning costs 11.5ms a render against 4.5ms rigid, and the fit spends
    # thousands of renders searching. It is a rendering refinement, not a pose,
    # so it is off during the search and back on when the answer is drawn.
    was = render_module.SKIN
    render_module.SKIN = False
    try:
        def scored():
            return (agreement(_mask_of(cutout, pose, margin, shape), target)
                    - tidiness * effort(rig, pose))

        best = scored()
        for count, width in passes:
            root_cap = ROOT_SHIFT * (rig.size[1] / 32.0)
            for channel, half in ROOT_SWEEPS:
                keep = getattr(pose, channel)
                for value in _span(keep, half * width, count, root_cap):
                    setattr(pose, channel, float(value))
                    score = scored()
                    if score > best:
                        best, keep = score, float(value)
                setattr(pose, channel, keep)

            for part in rig.descend():
                if part.pivot is None:
                    continue
                current = pose.get(part.name)
                own = skeleton.PartPose(current.angle, current.dx, current.dy,
                                        current.sx, current.sy)
                pose.set(part.name, own)
                allowed = limit_for(part)
                slide = shift_for(part, rig.size[1])
                for channel, half in SWEEPS:
                    keep = getattr(own, channel)
                    cap = allowed if channel == "angle" else slide
                    for value in _span(keep, half * width, count, cap):
                        setattr(own, channel, float(value))
                        score = scored()
                        if score > best:
                            best, keep = score, float(value)
                    setattr(own, channel, keep)
    finally:
        render_module.SKIN = was
    # The reported score is the AGREEMENT, not the penalised one. Tidiness steers
    # the search; it is not part of the answer, and a caller reading the fit as a
    # rig diagnostic needs the raw silhouette number.
    return pose, agreement(_mask_of(cutout, pose, margin, shape), target)


def fit_clip(cutout, targets, margin=None, passes=PASSES, warm=True,
             tidiness=TIDINESS):
    """[(pose, agreement)] for a sequence of target silhouettes.

    Each frame starts from the previous frame's answer (`warm`), because a walk
    cycle moves a little at a time and the search then begins near the answer
    rather than at rest. On the corpus knight this roughly halves the work and
    materially improves the fit on the frames furthest from rest.
    """
    import copy
    if margin is None:
        margin = render_module.suggest_margin(cutout.rig)
    out, previous = [], None
    for target in targets:
        start = copy.deepcopy(previous) if (warm and previous is not None) else None
        pose, score = fit_pose(cutout, target, margin, start=start,
                               passes=passes, tidiness=tidiness)
        out.append((pose, score))
        previous = pose
    return out


def to_animation(fitted, name, rig=None, fps=10, loop=True, note=""):
    """Fitted poses as a reusable `motion.Animation`.

    This is the artefact worth keeping. A solved walk is a table of angles like
    any hand-authored clip in the library, drives every other rig in the corpus,
    and never has to be generated again -- which is what makes this a motion
    LIBRARY rather than a generation step in every user's build.

    Tracks are keyed by ROLE rather than by part name, so a clip solved on one
    character applies to another whose parts are named differently. A channel
    that never leaves rest across the whole clip is dropped, so the animation
    reads as what it is rather than as a wall of zeroes.
    """
    frames = len(fitted)
    if not frames:
        raise ValueError("no fitted poses")
    times = [index / float(frames) for index in range(frames)]

    root = []
    for moment, (pose, _score) in zip(times, fitted):
        root.append({"t": round(moment, 4), "dx": round(pose.dx, 3),
                     "dy": round(pose.dy, 3)})

    # Keyed by ROLE when a rig is given, so a clip solved on one character drives
    # another whose parts are named differently -- which is the whole reason to
    # keep a solved clip at all. Without a rig the part's own name is the best
    # available key and the clip only drives the character it came from.
    role_of = {}
    if rig is not None:
        for part in rig.parts:
            role_of[part.name] = part.role

    by_role = {}
    for index, (pose, _score) in enumerate(fitted):
        for part_name, part_pose in pose.parts.items():
            key = role_of.get(part_name, part_name)
            by_role.setdefault(key, {})[index] = part_pose

    tracks = {}
    for part_name, per_frame in by_role.items():
        keys = []
        for index, moment in enumerate(times):
            part_pose = per_frame.get(index)
            if part_pose is None:
                continue
            key = {"t": round(moment, 4)}
            for channel, rest in (("angle", 0.0), ("dx", 0.0), ("dy", 0.0),
                                  ("sx", 1.0), ("sy", 1.0)):
                value = float(getattr(part_pose, channel))
                if abs(value - rest) > 1e-6:
                    key[channel] = round(value, 3)
            keys.append(key)
        if any(len(k) > 1 for k in keys):
            tracks[part_name] = keys

    if not any(abs(k["dx"]) > 1e-6 or abs(k["dy"]) > 1e-6 for k in root):
        root = None
    return motion_module.Animation(
        name, frames=frames, fps=fps, loop=loop, root=root, tracks=tracks,
        note=note or ("solved from a generated animation: the motion is the "
                      "model's, every pixel is the artist's"))


# Below this, the solve did not find the pose -- it found the best pose the rig
# is capable of, and that was not close. Measured on the corpus knight's attack:
# frames scoring 1.00, 1.00, .79, .77, .51, .52, .52, .39. The collapse at frame
# five is the arm needing to bend through a joint that does not exist.
REACHED = 0.70

# A split is only worth taking if it buys more than this. A second joint always
# fits at least as well -- it is strictly more freedom -- so accepting any
# improvement grows a skeleton of one-pixel bones that fit noise.
WORTH_SPLITTING = 0.06


def unreached(fitted, floor=REACHED):
    """Indices of the frames the rig could not reach, worst first.

    This is the whole diagnostic. A clip the rig CAN express fits near 1.00
    throughout; where agreement falls, the rig is missing a joint, and the frame
    index says which pose exposed it. Guessing which limbs need an elbow is
    replaced by running a clip that needs one.
    """
    return [index for index, (_pose, score)
            in sorted(enumerate(fitted), key=lambda pair: pair[1][1])
            if score < float(floor)]


def split_part(rig, name, at=0.5):
    """`rig` with one part cut into two segments end to end, upper parented to
    the original's parent and lower to the upper.

    The cut is a fraction ALONG the part's own longer axis, because that is the
    axis a limb bends across; a knee is partway down a leg, not partway across
    it. Returns None when the part is too short to divide -- a two-pixel mitten
    has nowhere to put a joint.
    """
    from . import rig as rig_module
    part = rig.by_name(name)
    if part is None or part.pivot is None:
        return None
    x0, y0, x1, y1 = part.box
    px, py = part.pivot
    # WHICH WAY the limb runs, decided by the pivot rather than by the box's
    # aspect. The pivot is the joint and the limb extends away from it, so the
    # axis with the greater reach from the pivot is its length.
    #
    # Using the box's longer side instead is wrong and was: the corpus knight's
    # left leg is eight wide and six tall, so it split SIDE BY SIDE into two
    # half-legs standing next to each other rather than into a thigh and a shin.
    # Its right leg, six by six, happened to split correctly, which is how the
    # bug survived a glance.
    across = max(px - x0, x1 - px)
    along = max(py - y0, y1 - py)
    tall = along >= across
    length = (y1 - y0) if tall else (x1 - x0)
    if length < 4:
        return None
    cut = int(round((y0 if tall else x0) + length * float(at)))
    if cut <= (y0 if tall else x0) or cut >= (y1 if tall else x1):
        return None

    # WHICH SEGMENT HOLDS THE JOINT. The axis is settled above; the direction
    # along it is a second question and getting it wrong inverts the chain.
    #
    # A leg hangs DOWN from a hip, so the segment at the low end of the axis is
    # the anchored one and the shin hangs off it. A quadruped's head-and-neck
    # rises UP from the withers, and a stalk rises from its base: there the
    # anchored segment is at the HIGH end and the skull hangs off it. Splitting
    # a deer's head as though it were a leg produced `head` = the skull, keeping
    # a pivot fifteen rows BELOW ITS OWN BOX, parented to the body, with the
    # neck that actually touches the withers hanging off the skull.
    #
    # This is the same mistake as the one recorded above, one level down: that
    # one chose the wrong AXIS, this one the wrong direction along it.
    near_low = (py <= (y0 + y1) / 2.0) if tall else (px <= (x0 + x1) / 2.0)
    if tall:
        low_box, high_box = (x0, y0, x1, cut), (x0, cut, x1, y1)
        low_far_pivot, high_far_pivot = ((x0 + x1) // 2, cut), ((x0 + x1) // 2, cut)
    else:
        low_box, high_box = (x0, y0, cut, y1), (cut, y0, x1, y1)
        low_far_pivot, high_far_pivot = (cut, (y0 + y1) // 2), (cut, (y0 + y1) // 2)
    if near_low:
        upper_box, lower_box, lower_pivot = low_box, high_box, low_far_pivot
    else:
        upper_box, lower_box, lower_pivot = high_box, low_box, high_far_pivot

    lower_name = name + "_lower"
    parts = []
    for other in rig.parts:
        if other.name == name:
            parts.append(rig_module.Part(name, part.role, upper_box, part.parent,
                                         part.pivot, part.z, part.confidence,
                                         part.tags))
            # ROLE `segment`, not the original's role. Both halves sharing a
            # role is not a naming nicety: `motion.select` binds a bare
            # selector by role, so a clip's `head` track matched the neck AND
            # the skull, each rotating by the full angle and the skull
            # inheriting the neck's on top of its own. Splitting a part must
            # not change what an existing clip does to it; with the far half
            # held apart, `head` addresses the anchored segment alone and the
            # rest of the chain rides it exactly as the whole part used to.
            parts.append(rig_module.Part(lower_name, "segment", lower_box, name,
                                         lower_pivot, part.z, part.confidence,
                                         part.tags))
            continue
        copy = _copy_part(other)
        if copy.parent == name:
            # Anything hanging off this limb belongs on the FREE end, not the
            # anchored one: a sword rides the hand, and leaving it on the upper
            # segment would pin it to the shoulder while the arm bends away.
            copy.parent = lower_name
        parts.append(copy)
    return rig_module.Rig(rig.size, parts, rig.character_class, rig.facing,
                          anchor=rig.anchor, actor=rig.actor, notes=list(rig.notes))


def better_split(cutout, targets, name, margin=None, cuts=(0.4, 0.5, 0.6),
                 floor=REACHED, worth=WORTH_SPLITTING, passes=((7, 1.0),)):
    """(rig, cut, gain) if giving `name` a second joint helps, else None.

    Fits the clip with the rig as it is, then again for each candidate cut, and
    keeps the best -- but only if it buys more than `worth`. A second joint is
    strictly more freedom and so always fits at least as well; accepting any
    improvement at all grows a skeleton of one-pixel bones that fit noise.

    Scored on the frames the rig COULD NOT REACH rather than on the whole clip.
    A walk that already fits at 0.95 has nothing to teach about elbows, and
    averaging those frames in would drown the signal from the four that failed.
    """
    from . import cutout as cutout_module
    rig = cutout.rig
    if margin is None:
        margin = render_module.suggest_margin(rig)
    base = fit_clip(cutout, targets, margin=margin, passes=passes)
    hard = unreached(base, floor)
    if not hard:
        return None
    reference = cutout.reference
    before = sum(base[i][1] for i in hard) / float(len(hard))

    best, seen = None, set()
    for cut in cuts:
        grown = split_part(rig, name, cut)
        if grown is None:
            continue
        # A short limb collapses every candidate cut onto the same row, and then
        # the "sweep" is one rig measured three times. Measured on the corpus
        # knight, whose arms are four pixels tall: cuts at 0.4, 0.5 and 0.6 all
        # round to row 22 and score an identical 0.731, which reads as a robust
        # plateau and is a single data point wearing three hats.
        shape = (grown.by_name(name).box, grown.by_name(name + "_lower").box)
        if shape in seen:
            continue
        seen.add(shape)
        try:
            cut_out = cutout_module.cut(grown, reference)
        except Exception:
            continue
        margin_now = render_module.suggest_margin(grown)
        scored = fit_clip(cut_out, [targets[i] for i in hard],
                          margin=margin_now, passes=passes)
        after = sum(score for _pose, score in scored) / float(len(scored))
        if best is None or after > best[2]:
            best = (grown, cut, after)
    if best is None or best[2] - before < float(worth):
        return None
    if len(seen) < 2:
        # One distinct rig is not a search. The part is too short for the cut
        # point to mean anything, and reporting a "best" cut here would invent a
        # precision the measurement does not have.
        return None
    return best[0], best[1], best[2] - before


def _copy_part(part):
    from . import rig as rig_module
    return rig_module.Part(part.name, part.role, part.box, part.parent,
                           part.pivot, part.z, part.confidence, part.tags)
