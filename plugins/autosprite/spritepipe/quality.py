"""Does the finished frame still look like the character?

Every other check in this plugin proves something about bookkeeping: the rects
line up, the palette holds, the parts reassemble. None of them notices when a
frame is *visibly wrong*, and the failure that matters most to a user is exactly
that -- a limb sheared into loose pixels, a flask whose cork has come off. Mass
is conserved when parts are merely scrambled, so mass does not catch it either.

What a viewer sees is the character coming apart, so measure that: the share of
a frame's pixels that are not connected to its main blob. Measured against the
SOURCE's own figure, because plenty of sprites are drawn in two pieces to begin
with and a drop shadow is not a defect.
"""

import numpy as np

from . import image as img


def label(mask):
    """Label the 8-connected components. Returns (labels, count).

    Background is -1. Everything here that asks "did the character come apart?"
    asks it of these labels, so there is one flood fill rather than one per
    caller.
    """
    height, width = mask.shape
    seen = np.zeros_like(mask)
    labels = np.full(mask.shape, -1, dtype=np.int32)
    count = 0
    # Walk only the opaque pixels. A frame is mostly empty canvas -- a character
    # covers maybe a sixth of it -- and scanning every cell to find the few that
    # matter made this the most expensive thing in a build once three different
    # callers started asking it the same question.
    for start_y, start_x in np.argwhere(mask):
        if seen[start_y, start_x]:
            continue
        stack = [(int(start_y), int(start_x))]
        seen[start_y, start_x] = True
        while stack:
            y, x = stack.pop()
            labels[y, x] = count
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if (0 <= ny < height and 0 <= nx < width
                            and mask[ny, nx] and not seen[ny, nx]):
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        count += 1
    return labels, count


def blob_sizes(mask):
    """Sizes of the 8-connected components, largest first."""
    labels, count = label(mask)
    return sorted((int((labels == index).sum()) for index in range(count)),
                  reverse=True)


def loose(mask):
    """The pixels that are NOT connected to the largest blob."""
    labels, count = label(mask)
    if count <= 1:
        return np.zeros_like(mask)
    sizes = [int((labels == index).sum()) for index in range(count)]
    return (labels >= 0) & (labels != int(np.argmax(sizes)))


def debris(pixels):
    """Share of the opaque pixels not connected to the largest blob, 0..1."""
    sizes = blob_sizes(img.alpha_mask(pixels))
    total = sum(sizes)
    if total <= 0:
        return 0.0
    return sum(sizes[1:]) / float(total)


def shed(frames, reference_pixels):
    """How much MORE debris the frames have than the source art already had.

    A sprite drawn with a detached shadow starts at some non-zero figure, and
    that is not this plugin's doing. Only the excess is.
    """
    base = debris(reference_pixels)
    worst, index = 0.0, None
    for position, frame in enumerate(frames):
        excess = max(0.0, debris(frame) - base)
        if excess > worst:
            worst, index = excess, position
    return worst, index


def disturbed(frames, rest, shape=None):
    """Every pixel any frame of a clip changes from the rest pose.

    The clip's footprint: the region of the picture the animation touches at
    all, whether it moved something there or vacated it.

    `shape` puts the answer in a canvas of a given size, which is how two
    footprints measured from differently-trimmed art get compared. Frames are
    aligned at the TOP-LEFT, which is right because everything here is cropped
    to its own content box, and is the caller's job to have arranged.
    """
    import numpy as _np

    height, width = shape or rest.shape[:2]
    out = _np.zeros((height, width), dtype=bool)
    rest_rows = min(rest.shape[0], height)
    rest_columns = min(rest.shape[1], width)
    for frame in frames:
        rows = min(frame.shape[0], rest_rows)
        columns = min(frame.shape[1], rest_columns)
        patch = _np.zeros((height, width), dtype=bool)
        patch[:rows, :columns] = (frame[:rows, :columns]
                                  != rest[:rows, :columns]).any(axis=2)
        out |= patch
    return out


def footprint(frames, rest, reference_frames):
    """(share, wrong, total): how much of what we move, the artist never moves.

    Every other measurement in this plugin asks whether a frame is INTACT.
    `shed` catches a limb that came away; `distinct_frames` catches a cycle that
    holds still. Both pass, with a perfect score, on an animation that is
    coherent and moves entirely the wrong pixels -- a windmill whose whole roof
    turns with its sails is one connected blob in every frame, and eight
    different pictures.

    So when an asset ships the artist's own frames of the same motion, compare
    the two FOOTPRINTS. Of the pixels our clip disturbs, what share does the
    artist never touch? That number caught a rig whose sails box covered a third
    of the image and which `shed` scored at 0.00%.

    `reference_frames` are the artist's, the first being their rest pose. It is
    deliberately one-sided: under-moving is a quieter failure than moving the
    wrong thing, and is measured by comparing the totals, which are returned.

    The two sets of art are routinely trimmed to slightly different sizes -- our
    rest pose goes through `ingest`, the artist's frames usually do not -- so
    both footprints are measured into one canvas big enough for either, aligned
    at the top-left. Comparing them at their own sizes is a shape error waiting
    to happen, and worse, an off-by-two misalignment when it does not raise.
    """
    if not frames or len(reference_frames) < 2:
        return 0.0, 0, 0
    shape = (max(rest.shape[0], reference_frames[0].shape[0]),
             max(rest.shape[1], reference_frames[0].shape[1]))
    truth = disturbed(reference_frames[1:], reference_frames[0], shape)
    ours = disturbed(frames, rest, shape)
    total = int(ours.sum())
    if not total:
        return 0.0, 0, 0
    wrong = int((ours & ~truth).sum())
    return wrong / float(total), wrong, total
