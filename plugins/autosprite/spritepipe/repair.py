"""When a character comes apart, damp exactly the part that broke it.

Every frame here is the user's own pixels, rotated. Nothing can be redrawn, so
there is one honest response to a limb that swings clear of the body: swing it
less. The hard part is knowing WHICH limb, and by how little.

Both are measurable. `quality.shed` already says which frame of a clip sheds
most; rendering each part alone into that frame and intersecting it with the
loose pixels says which parts drew them. Damping only those roles, by the
smallest step that puts the character back together, costs almost nothing in
motion: measured across the corpus, the six clips this repaired lost between
0.2 and 1.5 points of frame-to-frame change while their shed went to zero. The
other roles keep their full swing, which is why the cycle still reads.

Measured over the whole corpus and all seven clips, worst-frame shed summed to
103.7% before and 15.4% after, with eleven of the fourteen broken clips landing
at exactly zero.

This runs only on a clip that is already measurably broken, so a build where
nothing is wrong pays nothing but the one comparison it was going to make
anyway.
"""

import copy

from . import image as img
from . import quality as quality_module
from .skeleton import Pose, posed

# Below this a frame is as whole as the source art already was, and there is
# nothing to repair. It is the same figure `pipeline` warns at.
TOLERANCE = 0.005

# Tried in order, first one that works wins. Coarse on purpose: the aim is a
# clip that holds together, not the largest swing that technically survives,
# and every extra step is another full render.
STEPS = (0.8, 0.6, 0.4, 0.2)


def _loose_by_part(cutout, rig, pose, margin, render_module):
    """How many of each part's pixels are not connected to the main blob."""
    whole = render_module.render_pose(cutout, pose, margin=margin)
    loose = quality_module.loose(img.alpha_mask(whole))
    counts = {}
    for part in rig.parts:
        if not loose.any():
            counts[part.name] = 0
            continue
        alone = copy.copy(cutout)
        alone.sprites = [sprite for sprite in cutout.sprites
                         if sprite.name == part.name]
        drawn = img.alpha_mask(render_module.render_pose(alone, pose, margin=margin))
        counts[part.name] = int((drawn & loose).sum())
    return counts


def blame(cutout, rig, pose, margin, render_module):
    """Which roles drew pixels that came away, and were not already away.

    Renders each part on its own into the same pose and asks whether any of its
    pixels landed in a blob that is not the main one -- then asks the same
    question of the REST pose and keeps only the parts that got worse. Plenty of
    sprites are drawn in two pieces to begin with, and one corpus character has
    a baked contact shadow sitting a row below its boots: without the rest-pose
    subtraction, every frame of every clip blames whichever part owns that
    shadow, and the repair spends its whole budget damping a leg that was never
    the problem.

    A part can be blamed without having moved -- a torso can be left behind by a
    limb that took the connection with it -- so this names everything newly IN
    the debris, and the damping steps below decide what actually helps.
    """
    now = _loose_by_part(cutout, rig, pose, margin, render_module)
    if not any(now.values()):
        return []
    rest = _loose_by_part(cutout, rig, Pose(), margin, render_module)
    blamed = []
    for part in rig.parts:
        if now[part.name] > rest[part.name] and part.role not in blamed:
            blamed.append(part.role)
    return blamed


def damp(animation, roles, scale):
    """The same clip with those roles' rotation scaled down.

    Rotation only. A translation moves a part without changing its shape and
    cannot shear it off; a squash is a ratio the whole pipeline already floors
    elsewhere. It is the swing that throws a limb clear of the body.
    """
    clone = copy.deepcopy(animation)
    for role in roles:
        track = clone.tracks.get(role)
        if track is None:
            continue
        for key in track.keys:
            if "angle" in key:
                key["angle"] = float(key["angle"]) * float(scale)
    return clone


def repair(cutout, rig, animation, frames, reference_pixels, margin,
           render_module, tolerance=TOLERANCE, steps=STEPS):
    """Return (animation, frames, note).

    `frames` are the ones already rendered for this animation, so a clip that
    holds together costs nothing: it is measured, found whole, and handed back
    untouched.
    """
    shed, index = quality_module.shed(frames, reference_pixels)
    if shed <= tolerance or index is None:
        return animation, frames, None

    ground = cutout.ground_points()
    roles = blame(cutout, rig, posed(rig, animation, ground)[index],
                  margin, render_module)
    if not roles:
        return animation, frames, None

    swings = [role for role in roles if role in animation.tracks
              and any("angle" in key for key in animation.tracks[role].keys)]
    if not swings:
        # The potion's spin is the case: its squash lives on the root track, and
        # a squash is not what this repairs. Flooring one was measured twice and
        # reverted twice -- see HANDOFF's dead ends -- because a sprite comes
        # apart in the MIDDLE of a squash, not at its extreme.
        return animation, frames, (
            "%s: %.1f%% of the character comes away on frame %d, drawn by %s, "
            "and nothing in this clip swings it there -- a squash or a "
            "translation is pulling it apart, which damping cannot fix"
            % (animation.name, shed * 100, index, " and ".join(roles)))

    for scale in steps:
        trial = damp(animation, swings, scale)
        drawn = render_module.render_sequence(
            cutout, posed(rig, trial, ground), margin=margin)
        after, _ = quality_module.shed(drawn, reference_pixels)
        if after <= tolerance:
            return trial, drawn, (
                "%s: %s swung far enough to come away from the character "
                "(%.1f%% of it loose on frame %d), so that swing was reduced to "
                "%d%%; the rest of the cycle is untouched"
                % (animation.name, " and ".join(swings), shed * 100, index,
                   scale * 100))

    # Nothing in reach fixed it. Say so rather than shipping a quieter version
    # of a broken clip: a rig this far out needs a better rig, not less motion.
    return animation, frames, (
        "%s: %.1f%% of the character comes away on frame %d, drawn by %s, and "
        "damping that swing does not put it back together -- the rig is likely "
        "wrong for this character rather than the motion being too large"
        % (animation.name, shed * 100, index, " and ".join(swings)))
