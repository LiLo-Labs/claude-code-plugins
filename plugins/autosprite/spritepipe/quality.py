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
    for start_y in range(height):
        for start_x in range(width):
            if not mask[start_y, start_x] or seen[start_y, start_x]:
                continue
            stack = [(start_y, start_x)]
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
