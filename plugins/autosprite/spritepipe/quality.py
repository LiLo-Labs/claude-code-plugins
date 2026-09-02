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


def connected_share(mask):
    """The largest blob's share of the pixels. 1.0 is one connected thing."""
    sizes = blob_sizes(mask)
    total = sum(sizes)
    return (max(sizes) / float(total)) if total else 1.0


def scattered(pixels, floor=0.6):
    """Whether this art is inherently in pieces, so `shed` cannot mean anything.

    `shed` asks how much of the subject came AWAY from it, which presumes there
    is an "it" -- one connected thing that a limb can detach from. A sheet of
    rain, a flock, a spray of sparks is not that: it is fifty separate marks,
    and moving them changes which ones happen to touch, so the number wanders
    without anything having gone wrong.

    Measured on the corpus, every one of twenty-eight real character and prop
    sprites has a largest blob of 96.2% to 100% of its pixels, so the floor here
    has a very wide margin and only ever fires on art that really is scattered.
    """
    return connected_share(img.alpha_mask(pixels)) < float(floor)


def conserved(frames, rest):
    """(worst, index): the largest share of pixels any frame gained or lost.

    What to ask instead of `shed` when the art is scattered. It is a weaker
    question about shape and a much stronger one about bookkeeping: a wrap is a
    bijection, so a scrolling sheet of rain must hold EXACTLY the pixel count it
    started with in every frame, and any drift at all is a bug rather than a
    matter of degree.
    """
    base = int(img.alpha_mask(rest).sum())
    if not base:
        return 0.0, None
    worst, index = 0.0, None
    for position, frame in enumerate(frames):
        drift = abs(int(img.alpha_mask(frame).sum()) - base) / float(base)
        if drift > worst:
            worst, index = drift, position
    return worst, index


def disturbed(frames, rest, shape=None):
    """Every pixel any frame of a clip changes from the rest pose.

    The clip's footprint: the region of the picture the animation touches at
    all, whether it moved something there or vacated it.

    `shape` puts the answer in a canvas of a given size, which is how two
    footprints measured from differently-sized art get compared. Frames are
    aligned at the top-left; `footprint` below is what arranges for that to be
    meaningful.
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


def _aligned(frames, offset):
    """Frames with a render margin cropped off, so they sit where `rest` does.

    `render_pose` draws into a canvas with a MARGIN -- room for a limb swung to
    horizontal -- so the character sits `margin` pixels in from the corner,
    while the art it is judged against is trimmed flush. Comparing them as given
    measures one picture against a SHIFTED COPY of another and reports nonsense
    with total confidence: on a flag it turns a real 21.4% into 84.0%, and
    nothing about that number looks wrong. The sensitivity is brutal and worth
    knowing -- one pixel out either way, on the same flag, reads 27.2% and
    25.4%.

    The offset is not inferable -- a frame's own content box moves with the
    animation -- so the caller passes it, and it is exactly the `margin` they
    rendered with.
    """
    x, y = offset
    if not x and not y:
        return frames
    return [frame[y:, x:] for frame in frames]


def coverage(frames, rest, reference_frames, offset=(0, 0)):
    """How much we move as a share of how much the artist moves.

    The other half of `footprint`, which is one-sided on purpose and therefore
    gameable by doing less. 1.0 is the same amount of the picture disturbed;
    below 1.0 is under-moving, which `footprint` does not punish and a viewer
    reads as a stiffer animation.
    """
    if not frames or len(reference_frames) < 2:
        return 0.0
    frames = _aligned(frames, offset)
    reference_rest = reference_frames[0]
    shape = (max(rest.shape[0], reference_rest.shape[0]),
             max(rest.shape[1], reference_rest.shape[1]))
    theirs = int(disturbed(reference_frames[1:], reference_rest, shape).sum())
    ours = int(disturbed(frames, rest, shape).sum())
    return (ours / float(theirs)) if theirs else 0.0


def footprint(frames, rest, reference_frames, offset=(0, 0)):
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

    **So this number means nothing on its own.** A clip that moves ten pixels,
    all of them right, scores 0% and is not an animation. Read it with
    `coverage` below and compare at MATCHED coverage, or the metric rewards
    doing less: on a flag, damping the wave took the error from 21.4% to 19.7%
    by moving a third fewer pixels than the artist does, and on a 15px character
    it reached 0.0% while moving 22 pixels against the artist's 102.

    Two rests, not one, is the other way to get a meaningless answer. Both
    footprints have to be measured from the SAME pose. Every clip here starts
    from the source image, and an artist's strips usually do not -- on a CC0
    16x16 brawler, only the idle strip opens on the standing pose, while the
    walk, jump and punch strips open 41 to 78 silhouette pixels away from it on
    a 156-pixel character. Passing such a strip as `reference_frames` measures
    their motion from their guard and ours from standing, and reported this
    plugin's `attack` at 78.9% where the parallel figure is 48.4%. When the
    artist's strip does not open on the source pose, pass the source itself as
    `reference_frames[0]` and their whole strip after it.

    Pass `offset` -- the margin `frames` were rendered with -- or the comparison
    is silently meaningless. Rendered frames carry a margin and the art they are
    judged against does not, so measuring them as given compares a picture with
    a SHIFTED COPY of another one; on a flag that reports 84.0% where the truth
    is 21.4%, and the number looks entirely plausible. It is a parameter rather
    than something inferred because a frame's own content box moves with the
    animation, so there is nothing honest to infer it from.
    """
    if not frames or len(reference_frames) < 2:
        return 0.0, 0, 0
    frames = _aligned(frames, offset)
    reference_rest = reference_frames[0]
    shape = (max(rest.shape[0], reference_rest.shape[0]),
             max(rest.shape[1], reference_rest.shape[1]))
    truth = disturbed(reference_frames[1:], reference_rest, shape)
    ours = disturbed(frames, rest, shape)
    total = int(ours.sum())
    if not total:
        return 0.0, 0, 0
    wrong = int((ours & ~truth).sum())
    return wrong / float(total), wrong, total
