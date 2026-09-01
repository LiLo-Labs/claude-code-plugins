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


def _mode_downscale(pixels, factor):
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
        return _mode_downscale(np.array(moved, dtype=np.uint8), factor)

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
        layer = img.blank(height, width)
        img.paste(layer, sprite.pixels,
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
