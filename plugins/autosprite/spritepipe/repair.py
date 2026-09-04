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


# Tried in that order. Rotation is the usual culprit and the cheapest thing to
# reduce, so it gets its own pass before translation is touched at all.
CHANNEL_SETS = (("angle",), ("angle", "dx", "dy"))


def damp(animation, selectors, scale, channels=("angle",)):
    """The same clip with those tracks' motion scaled down.

    Rotation first, because it is what usually throws a limb clear of the body
    and because reducing it costs the least readability. But a translation can
    take a part away too, and this file used to say it could not: "a translation
    moves a part without changing its shape and cannot shear it off". Shearing a
    part is not the failure `shed` measures -- COMING AWAY is, and a part that
    merely abuts its parent rather than overlapping it comes away the moment it
    is moved at all.

    A top-down RPG character found it. Its legs are a five-pixel stub below a
    torso they do not overlap, so the face-on walk's 1.4px lift detached them on
    five clips at 6%, and no amount of damping the rotation helped because the
    rotation was never the problem. Reducing the lift to 80% takes the walk and
    the run to exactly zero.

    A squash is still left alone: it is a ratio, and the pipeline floors it
    elsewhere.
    """
    clone = copy.deepcopy(animation)
    for selector in selectors:
        track = clone.tracks.get(selector)
        if track is None:
            continue
        for channel in channels:
            track.adjust(channel, lambda value: value * float(scale))
    return clone


def swinging(animation, rig, names, channels=("angle",)):
    """Every track that MOVES a part in `names` or its partner limb.

    A part may be driven by a role track, a trait track and a name track at
    once, and any of them could be the one throwing it clear.

    A limb's PARTNER is included for two reasons, and the second would be enough
    on its own. Damping one leg of a pair and not the other makes the cycle
    limp -- the two are in counter-phase and are meant to be the same limb seen
    twice. And the break often needs both: on a top-down RPG character whose
    legs are a stub under the torso, the far leg was blamed and damping it alone
    left 5.96% loose however far it was reduced, because the near leg was
    lifting away at the same instant; damping the pair took it to zero.
    """
    from .motion import select
    from .rig import PAIRED

    wanted = set(names)
    for name in list(names):
        part = rig.by_name(name)
        partner = PAIRED.get(part.role) if part is not None else None
        if partner:
            wanted.update(other.name for other in rig.by_role(partner))

    found = []
    for selector, track in sorted(animation.tracks.items()):
        if not any(track.has(channel) for channel in channels):
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

    attempts = [(channels, swinging(animation, rig, names, channels))
                for channels in CHANNEL_SETS]
    attempts = [(channels, tracks) for channels, tracks in attempts if tracks]
    if not attempts:
        # The potion's spin is the case: its squash lives on the root track, and
        # a squash is not what this repairs. Flooring one was measured twice and
        # reverted twice -- see HANDOFF's dead ends -- because a sprite comes
        # apart in the MIDDLE of a squash, not at its extreme.
        return animation, frames, (
            "%s: %.1f%% of the character comes away on frame %d, drawn by %s, "
            "and nothing in this clip moves it there -- a squash is pulling it "
            "apart, which damping cannot fix"
            % (animation.name, shed * 100, index, " and ".join(roles)))

    def rendered(trial):
        """Exactly the way the pipeline renders it, levelling included.

        A planted clip drawn without that pass is a different set of pictures
        from the ones the build ships, and measuring those would be measuring
        the wrong thing.
        """
        trial_poses = posed(rig, trial, ground)
        drawn = render_module.render_sequence(cutout, trial_poses, margin=margin)
        if trial.planted:
            drawn = render_module.level_to_floor(cutout, trial_poses, drawn, margin)
        return drawn

    swings = attempts[-1][1]
    for channels, swings in attempts:
        for scale in steps:
            trial = damp(animation, swings, scale, channels)
            drawn = rendered(trial)
            if quality_module.shed(drawn, reference_pixels)[0] <= tolerance:
                return trial, drawn, (
                    "%s: %s moved far enough to come away from the character "
                    "(%.1f%% of it loose on frame %d), so its %s was reduced to "
                    "%d%%; the rest of the cycle is untouched"
                    % (animation.name, " and ".join(swings), shed * 100, index,
                       "swing" if channels == ("angle",) else "swing and travel",
                       scale * 100))

    # Nothing in reach fixed it, in either channel set. Say so rather than
    # shipping a quieter version of a broken clip: a rig this far out needs a
    # better rig, not less motion.
    return animation, frames, (
        "%s: %.1f%% of the character comes away on frame %d, drawn by %s, and "
        "damping its swing and its travel does not put it back together -- the "
        "rig is likely wrong for this character rather than the motion being "
        "too large"
        % (animation.name, shed * 100, index, " and ".join(swings)))
