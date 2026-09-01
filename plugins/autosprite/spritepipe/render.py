"""Rasterise a posed rig into one frame.

Every sample is nearest-neighbour and every composite is an alpha test. That is
the whole reason this plugin can promise the output palette is a subset of the
input palette: no interpolation runs anywhere between the user's PNG and the
sheet, so no colour is ever averaged into existence.

Frames are rendered onto a canvas with a margin around the reference box,
because animation is mostly about leaving that box -- an arm raised overhead, a
jump, a lunge. `stabilize.py` crops every frame of a sheet back to one common
box afterwards, so the margin costs nothing in the output.
"""

import copy

import numpy as np
from PIL import Image as PILImage

from . import image as img
from . import skeleton


def canvas_size(rig, margin):
    width, height = rig.size
    return (width + 2 * margin, height + 2 * margin)


# How far the raster is supersampled before a part is rotated, and how much of a
# block must be covered for it to survive the reduction.
#
# Both were measured rather than chosen, against the property that matters: a
# character must not lose or gain mass when it rotates. Comparing every frame's
# opaque area against the rest pose's, across walk, run, jump and attack, on two
# different rigs of the test character (mean absolute error per frame):
#
#     no supersampling    4.0% and 5.7%
#     3x, coverage 1/3    8.8%          -- and a MEAN of 1.088: pure dilation
#     3x, coverage 1/2    2.4% and 3.8%
#     4x/5x, coverage 1/2 3.1% and 4.8%
#
# Plain nearest-neighbour erodes the character by 4-6% every time a limb turns.
# A generous coverage threshold overcorrects into dilation, which looks solid
# and is why it is tempting: the limbs simply get fatter. A majority threshold
# is the honest one and also the best one, cutting the error by about a third.
# Going finer than 3x is worse, not better, because the finer grid resolves
# detail the output grid cannot hold. 2x and 3x are within noise of each other;
# 3x is kept because it is the better of the two on the vision-built rig, which
# is the one users get by default.
SUPERSAMPLE = 3
COVERAGE = 0.5

ALPHA_FLOOR_CODE = img.ALPHA_FLOOR


def _mode_downscale(pixels, factor, with_outvoted=False):
    """Shrink by `factor`, giving each block the most common colour in it.

    This is the half of supersampling that keeps the palette guarantee: the
    output value of every block is a value that was already in the block, so no
    colour can be averaged into existence. An ordinary box filter would be
    smoother and would invent a new colour at every edge.
    """
    height, width = pixels.shape[:2]
    tall, wide = height // factor, width // factor
    window = pixels[:tall * factor, :wide * factor].astype(np.int64)
    # int64 with -1 as the "not a sample" marker, not uint32 with 0xFFFFFFFF:
    # that value is opaque white, and a white sprite would have every one of its
    # own pixels mistaken for a hole.
    codes = ((window[:, :, 0] << 24) | (window[:, :, 1] << 16)
             | (window[:, :, 2] << 8) | window[:, :, 3])
    blocks = (codes.reshape(tall, factor, wide, factor)
              .transpose(0, 2, 1, 3).reshape(tall, wide, factor * factor))

    opaque = (blocks & 0xFF) > ALPHA_FLOOR_CODE
    cover = opaque.sum(axis=2)
    # Sort the transparent samples to the end so the mode is taken over the
    # opaque ones; a block that survives the coverage test is coloured by what
    # actually drew it, not by the hole around it.
    ordered = np.sort(np.where(opaque, blocks, np.int64(-1)), axis=2)[:, :, ::-1]

    best = ordered[:, :, 0].copy()
    best_run = np.zeros((tall, wide), dtype=np.int32)
    current = ordered[:, :, 0].copy()
    run = np.where(opaque.any(axis=2), 1, 0).astype(np.int32)
    best_run = run.copy()
    for index in range(1, factor * factor):
        value = ordered[:, :, index]
        valid = value >= 0
        same = (value == current) & valid
        run = np.where(same, run + 1, np.where(valid, 1, 0))
        current = np.where(valid, value, current)
        better = run > best_run
        best_run = np.where(better, run, best_run)
        best = np.where(better, current, best)

    keep = cover >= max(1, int(round(factor * factor * COVERAGE)))
    out = np.zeros((tall, wide, 4), dtype=np.uint8)
    best = np.maximum(best, 0)
    out[:, :, 0] = (best >> 24) & 0xFF
    out[:, :, 1] = (best >> 16) & 0xFF
    out[:, :, 2] = (best >> 8) & 0xFF
    out[:, :, 3] = best & 0xFF
    if with_outvoted:
        # What each block WOULD have been if coverage had not vetoed it. A
        # two-pixel neck squashed to less than half a pixel loses that vote and
        # the flask's cork comes off; the colour it lost with is right here, and
        # `_reconnect` puts a thread of it back rather than inventing one.
        outvoted = out.copy()
        outvoted[cover == 0] = 0
        out[~keep] = 0
        return out, outvoted
    out[~keep] = 0
    return out


def _affine_coefficients(matrix):
    """PIL wants the INVERSE map, output -> input, as six floats.

    Getting this backwards produces a frame that is transformed the wrong way
    and still looks plausible for a symmetric pose, which is the kind of bug
    that survives a casual eyeball and shows up as a limp three days later.
    """
    inverse = np.linalg.inv(matrix)
    return (inverse[0, 0], inverse[0, 1], inverse[0, 2],
            inverse[1, 0], inverse[1, 1], inverse[1, 2])


def _one_piece(layer):
    """Was this layer drawn as a single connected blob?"""
    from . import quality
    mask = img.alpha_mask(layer)
    if not mask.any():
        return False
    return len(quality.blob_sizes(mask)) == 1


def _reconnect(frame, outvoted, whole=True):
    """Put back the thinnest thread of a piece the reduction voted away.

    A transform must not break something the artist drew in one piece. The
    flask is the case: squashed to 40% its two-pixel neck falls below the
    coverage threshold while its four-pixel rim survives, so the cork comes off
    and floats. No amount of damping the motion fixes that, because the failure
    is in the MIDDLE of the squash range rather than at its extreme -- which is
    why flooring the squash was measured and reverted twice.

    So repair it where it happens. Where the reduction split one piece into
    several, join each stray back to the main one along the shortest line
    between them, colouring each pixel with what its own block would have been
    had coverage not vetoed it. Every colour therefore came from the block it is
    drawn in, and the palette guarantee is untouched.
    """
    from . import quality

    labels, count = quality.label(img.alpha_mask(frame))
    if count <= 1:
        return frame
    if not (whole() if callable(whole) else whole):
        # Whatever came apart was already apart. A floating orb, a detached
        # shadow, a character the artist drew in two: none of that is the
        # renderer's business to weld together.
        return frame
    sizes = [int((labels == index).sum()) for index in range(count)]
    main = int(np.argmax(sizes))
    main_points = np.argwhere(labels == main)
    out = frame.copy()
    for index in range(count):
        if index == main:
            continue
        stray = np.argwhere(labels == index)
        gaps = ((stray[:, None, :] - main_points[None, :, :]) ** 2).sum(axis=2)
        here, there = np.unravel_index(int(np.argmin(gaps)), gaps.shape)
        start, end = stray[here], main_points[there]
        steps = int(max(abs(start[0] - end[0]), abs(start[1] - end[1])))
        for step in range(1, steps):
            y = int(round(start[0] + (end[0] - start[0]) * step / steps))
            x = int(round(start[1] + (end[1] - start[1]) * step / steps))
            if out[y, x, 3]:
                continue
            colour = outvoted[y, x]
            if not colour[3]:
                colour = frame[end[0], end[1]]
            out[y, x] = colour
    return out


def _transform_layer(layer, matrix, size, supersample=SUPERSAMPLE):
    """Apply a world transform to one part's layer.

    Rotating sprite-sized art at 1:1 with nearest-neighbour has two visible
    failures, and they are the two things that make a generated sheet look
    broken rather than stylised: a flat block staircases along its edges, and a
    two-pixel-wide limb breaks into a dotted diagonal because whole rows of it
    fall between samples.

    Rotating sprite-sized art at 1:1 with nearest-neighbour erodes it: whole
    rows of a thin limb fall between samples, and the character loses about 4%
    of its mass every time a limb turns (see the measurements above the
    constants). The edges of a flat block staircase for the same reason.

    Both are sampling artefacts, so both go away by sampling more: the layer is
    scaled up, transformed there, and reduced by taking the most common colour
    in each block. Every step is still nearest-neighbour and the reduction only
    ever picks a colour the block already had, so the palette guarantee is
    untouched -- which is why this is done here rather than by rotating with
    bilinear and cleaning up afterwards.
    """
    if np.allclose(matrix, skeleton.IDENTITY):
        # An untouched part is copied, not resampled. Most parts in most frames
        # take this path, and it keeps them provably pixel-exact.
        out = img.blank(size[1], size[0])
        img.paste(out, layer, 0, 0)
        return out

    factor = max(1, int(supersample))
    if factor > 1:
        big_layer = img.scale_nearest(layer, factor)
        scale = skeleton.scale(factor, factor)
        big_matrix = scale @ matrix @ np.linalg.inv(scale)
        moved = PILImage.fromarray(np.ascontiguousarray(big_layer), mode="RGBA").transform(
            (size[0] * factor, size[1] * factor), PILImage.AFFINE,
            _affine_coefficients(big_matrix), resample=PILImage.NEAREST)
        small, outvoted = _mode_downscale(np.array(moved, dtype=np.uint8),
                                          factor, with_outvoted=True)
        # The cheap half of the test first: nothing to repair unless the
        # reduction actually split the layer, and that is one flood fill on the
        # small image rather than two including the full-size source.
        return _reconnect(small, outvoted, whole=lambda: _one_piece(layer))

    source = PILImage.fromarray(np.ascontiguousarray(layer), mode="RGBA")
    moved = source.transform(size, PILImage.AFFINE, _affine_coefficients(matrix),
                             resample=PILImage.NEAREST)
    return np.array(moved, dtype=np.uint8)


def render_pose(cutout, pose, margin=0):
    """One frame: every part transformed by its world matrix and composited."""
    rig = cutout.rig
    width, height = canvas_size(rig, margin)
    transforms = skeleton.world_transforms(rig, pose)
    shift = skeleton.translate(margin, margin)

    frame = img.blank(height, width)
    for sprite in cutout.sprites:
        pixels = sprite.pixels
        part_pose = pose.get(sprite.name)
        if abs(part_pose.wave) >= 0.5:
            # In the part's own space, before its transform, so a part the rig
            # has turned on its side waves along its own length rather than
            # along the screen's.
            pixels = img.wave_columns(pixels, part_pose.wave, part_pose.wave_phase)
        step = int(round(part_pose.cycle))
        if step:
            # Before the transform, not after: the supersampled reduction votes
            # on whatever colours the block holds, and it should be voting on
            # the shaded ones. Doing it afterwards would also re-shade the
            # transparent fringe the resampler leaves behind.
            from . import palette as palette_module
            pixels = palette_module.step_ramp(pixels, cutout.ramp_table(), step)
        layer = img.blank(height, width)
        img.paste(layer, pixels,
                  sprite.origin[0] + margin, sprite.origin[1] + margin)
        matrix = shift @ transforms[sprite.name] @ np.linalg.inv(shift)
        moved = _transform_layer(layer, matrix, (width, height))
        img.paste(frame, moved, 0, 0)

    if pose.flip:
        frame = frame[:, ::-1].copy()
    return img.harden_alpha(frame)


def render_sequence(cutout, poses, margin=0):
    return [render_pose(cutout, pose, margin=margin) for pose in poses]


def suggest_margin(rig):
    """Enough room for a limb swung to horizontal and a jump.

    Half the character's larger dimension covers an arm rotated 90 degrees out
    of a rig whose pivot sits at the shoulder; the jump arc adds the rest.
    Cheap to over-allocate -- the frames are cropped to their common content box
    before anything is packed.
    """
    width, height = rig.size
    return int(max(6, round(max(width, height) * 0.6)))


def level_to_floor(cutout, poses, frames, margin=0):
    """Nudge by whole pixels so the character's drawn feet share one row.

    `skeleton.plant` does this exactly, in continuous space, and then the
    rasteriser rounds: a foot computed at y=31.4 and one at y=31.6 land a pixel
    apart. That last pixel is worth closing, because "the feet are on the same
    row in every frame" is a guarantee a game can rely on and "within a pixel"
    is not. Measured across the corpus's walks, the geometric pass leaves seven
    characters one pixel out and this takes all seven to zero.

    A `shadow` part is excluded from the measurement. It is the floor rather
    than the character, it never moves, and it would otherwise report the same
    row in every frame and make this a no-op on exactly the sprites that have
    one.

    Only the frames that are actually off are drawn again.
    """
    rig = cutout.rig
    shadows = [sprite for sprite in cutout.sprites
               if (rig.by_name(sprite.name) or rig.root).role == "shadow"]
    ignore = None
    if shadows:
        ghost = copy.copy(cutout)
        ghost.sprites = shadows
        ignore = img.alpha_mask(render_pose(ghost, skeleton.Pose(), margin=margin))

    lows = []
    for frame in frames:
        mask = img.alpha_mask(frame)
        if ignore is not None:
            mask = mask & ~ignore
        rows = np.nonzero(mask)[0]
        lows.append(int(rows.max()) if rows.size else None)
    drawn = [low for low in lows if low is not None]
    if len(set(drawn)) <= 1:
        return frames

    floor = max(drawn)
    out = []
    for pose, frame, low in zip(poses, frames, lows):
        if low is None or low == floor:
            out.append(frame)
            continue
        pose.dy += floor - low
        out.append(render_pose(cutout, pose, margin=margin))
    return out
