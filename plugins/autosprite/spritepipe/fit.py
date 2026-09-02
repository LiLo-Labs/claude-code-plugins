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
SWEEPS = (("angle", 38.0), ("dy", 3.0), ("dx", 3.0))
ROOT_SWEEPS = (("dy", 4.0), ("dx", 4.0))
PASSES = ((9, 1.0), (7, 0.28))


def _span(centre, half, count):
    return np.linspace(centre - half, centre + half, int(count))


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


def fit_pose(cutout, target, margin, start=None, passes=PASSES):
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
        best = agreement(_mask_of(cutout, pose, margin, shape), target)
        for count, width in passes:
            for channel, half in ROOT_SWEEPS:
                keep = getattr(pose, channel)
                for value in _span(keep, half * width, count):
                    setattr(pose, channel, float(value))
                    score = agreement(_mask_of(cutout, pose, margin, shape), target)
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
                for channel, half in SWEEPS:
                    keep = getattr(own, channel)
                    for value in _span(keep, half * width, count):
                        setattr(own, channel, float(value))
                        score = agreement(
                            _mask_of(cutout, pose, margin, shape), target)
                        if score > best:
                            best, keep = score, float(value)
                    setattr(own, channel, keep)
    finally:
        render_module.SKIN = was
    return pose, best


def fit_clip(cutout, targets, margin=None, passes=PASSES, warm=True):
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
        pose, score = fit_pose(cutout, target, margin, start=start, passes=passes)
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
