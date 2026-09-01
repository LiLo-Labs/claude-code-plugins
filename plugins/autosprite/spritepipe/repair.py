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
    """Which PARTS drew pixels that came away, and were not already away.

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

    Parts rather than roles, because a track is no longer necessarily addressed
    by a role: a clip may drive `trait:stalk` or `name:sails`, and a repair that
    can only look up `accessory` would report a break it is unable to touch.
    """
    now = _loose_by_part(cutout, rig, pose, margin, render_module)
    if not any(now.values()):
        return []
    rest = _loose_by_part(cutout, rig, Pose(), margin, render_module)
    return [part.name for part in rig.parts
            if now[part.name] > rest[part.name]]


def damp(animation, selectors, scale):
    """The same clip with those tracks' rotation scaled down.

    Rotation only. A translation moves a part without changing its shape and
    cannot shear it off; a squash is a ratio the whole pipeline already floors
    elsewhere. It is the swing that throws a limb clear of the body.
    """
    clone = copy.deepcopy(animation)
    for selector in selectors:
        track = clone.tracks.get(selector)
        if track is None:
            continue
        track.adjust("angle", lambda value: value * float(scale))
    return clone


def swinging(animation, rig, names):
    """Every track that rotates a part in `names`, by whatever selector.

    A part may be driven by a role track, a trait track and a name track at
    once, and any of them could be the one throwing it clear.
    """
    from .motion import select

    found = []
    wanted = set(names)
    for selector, track in sorted(animation.tracks.items()):
        if not track.has("angle"):
            continue
        if any(part.name in wanted for part in select(rig, selector)):
            found.append(selector)
    return found


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
    names = blame(cutout, rig, posed(rig, animation, ground)[index],
                  margin, render_module)
    if not names:
        return animation, frames, None
    roles = []
    for name in names:
        part = rig.by_name(name)
        if part is not None and part.role not in roles:
            roles.append(part.role)

    swings = swinging(animation, rig, names)
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
        # Rendered exactly the way the pipeline renders it, levelling included.
        # A planted clip drawn without that pass is a different set of pictures
        # from the ones the build ships, and measuring those would be measuring
        # the wrong thing.
        trial_poses = posed(rig, trial, ground)
        drawn = render_module.render_sequence(cutout, trial_poses, margin=margin)
        if trial.planted:
            drawn = render_module.level_to_floor(cutout, trial_poses, drawn, margin)
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
