"""Give every frame in a sheet the same box and the same anchor.

An engine positions a sprite by one point. If the sprite's frames have different
sizes, or the same size but different content offsets, the character slides
around while it animates -- feet leaving the floor on the walk, the head drifting
during idle. It is the single most common thing wrong with a generated sheet and
it is entirely mechanical to prevent.

Frames arrive here all rendered on the same margined canvas, so they already
share a coordinate system. The job is to find one box that holds every frame's
content, crop them all to it, and report where the anchor ended up.
"""

from . import image as img


def union_box(frames, padding=0):
    """The smallest box containing the content of every frame."""
    boxes = [img.content_box(frame) for frame in frames]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return None
    x0 = min(box[0] for box in boxes)
    y0 = min(box[1] for box in boxes)
    x1 = max(box[2] for box in boxes)
    y1 = max(box[3] for box in boxes)
    if padding:
        height, width = frames[0].shape[:2]
        x0, y0 = max(0, x0 - padding), max(0, y0 - padding)
        x1, y1 = min(width, x1 + padding), min(height, y1 + padding)
    return (x0, y0, x1, y1)


def crop_all(frames, box):
    return [img.crop(frame, box) for frame in frames]


def stabilise(frames, anchor, padding=0):
    """Crop every frame to one common box.

    `anchor` is in the frames' shared (margined) coordinate system; the returned
    anchor is in the cropped one.

    Returns (frames, box, anchor, report).
    """
    box = union_box(frames, padding=padding)
    if box is None:
        return frames, None, anchor, {"empty": list(range(len(frames)))}

    cropped = crop_all(frames, box)
    moved = (int(anchor[0]) - box[0], int(anchor[1]) - box[1])

    empty = [index for index, frame in enumerate(cropped)
             if not img.alpha_mask(frame).any()]
    report = {
        "box": list(box),
        "size": [box[2] - box[0], box[3] - box[1]],
        "anchor": list(moved),
        "empty": empty,
        "duplicates": duplicate_runs(cropped),
    }
    return cropped, box, moved, report


def duplicate_runs(frames):
    """Consecutive identical frames, as [first_index, count] pairs.

    Not an error -- a hold is a legitimate animation beat, and `attack` above
    holds its contact frame on purpose. But three identical frames in a walk
    cycle means the amplitudes are too small for the character's size, and the
    user should be told rather than left to wonder why it looks frozen.
    """
    runs = []
    index = 1
    while index < len(frames):
        if img.equal(frames[index], frames[index - 1]):
            start, count = index - 1, 2
            while index + 1 < len(frames) and img.equal(frames[index + 1], frames[index]):
                index += 1
                count += 1
            runs.append([start, count])
        index += 1
    return runs


def anchor_drift(frames, anchor):
    """How far the character's floor contact moves from the anchor, per frame.

    A walk cycle should hold near zero. A jump should not -- leaving the floor is
    the point. Reported, never corrected: correcting it would flatten the jump.
    """
    drift = []
    for frame in frames:
        box = img.content_box(frame)
        if box is None:
            drift.append(None)
            continue
        floor_x = (box[0] + box[2]) / 2.0
        drift.append([round(floor_x - anchor[0], 2), round(box[3] - anchor[1], 2)])
    return drift


def fit_to_cell(frames, anchor, size):
    """Put every frame in a `size` x `size` cell with the anchor in one place.

    autosprite.io lets a user choose the frame size, and a game engine usually
    wants one: a fixed cell is what a tile-based importer, a uniform atlas and a
    character controller with a fixed collision box all expect. It is also
    stricter than what the pipeline does by default, which is to trim each clip
    to its own tight box.

    The anchor -- bottom-centre of the character, the point that must not
    wander -- goes to the bottom-centre of the cell, so every clip of every
    character stands on the same floor at the same place.

    Raises if the art does not fit. Cropping a character to make it fit is the
    one thing that must not happen quietly.
    """
    size = int(size)
    out = []
    for index, frame in enumerate(frames):
        height, width = frame.shape[:2]
        dx = size // 2 - int(anchor[0])
        dy = size - int(anchor[1])
        if width + dx > size or dx < 0 or height + dy > size or dy < 0:
            raise ValueError(
                "frame %d is %dx%d anchored at %s and does not fit a %dpx cell; "
                "use --frame-size %d or larger"
                % (index, width, height, tuple(anchor), size,
                   max(width, height, width + dx, height + dy)))
        cell = img.blank(size, size)
        img.paste(cell, frame, dx, dy)
        out.append(cell)
    return out, (size // 2, size)
