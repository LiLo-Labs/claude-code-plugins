"""Lay the frames out on one texture.

Two layouts, because engines genuinely disagree:

**grid** -- every frame in an identically sized cell, one row per clip. Bigger
than it needs to be, and the only thing several importers can read without an
atlas file at all: Unity's Grid By Cell Size, GameMaker's strip import, RPG
Maker's fixed 3x4 character sheet. It is the default for that reason.

**packed** -- shelf packing, tight. Smaller texture, and unusable without the
atlas JSON. Worth it when the sheet is large or the frames vary a lot in size.

Two details that look like polish and are not:

**Padding** keeps a neighbouring frame's pixels out of this frame when the GPU
samples slightly outside the rect, which it does whenever the sprite is drawn at
a non-integer position or a non-integer scale.

**Extrude** duplicates each frame's edge pixels outward into that padding. With
bilinear filtering on, padding alone gives a transparent halo at the sprite's
edge; extrude gives the character's own colour instead. Neither costs anything
at runtime and skipping them is why generated sheets so often show seams.
"""

import numpy as np

from . import image as img


class Clip:
    """One animation, in one direction, with the frames already stabilised."""

    def __init__(self, name, frames, fps=10, loop=True, direction=None,
                 loop_start=None, loop_end=None,
                 anchor=(0, 0), fidelity="drawn", note=""):
        self.name = name
        self.frames = list(frames)
        self.fps = float(fps)
        self.loop = bool(loop)
        # Where the repeat begins and ends, when the whole clip is not the loop.
        self.loop_start = None if loop_start is None else int(loop_start)
        self.loop_end = None if loop_end is None else int(loop_end)
        self.direction = direction
        self.anchor = tuple(int(v) for v in anchor)
        self.fidelity = fidelity
        self.note = note

    @property
    def key(self):
        return "%s_%s" % (self.name, self.direction) if self.direction else self.name

    def frame_name(self, index):
        return "%s_%03d" % (self.key, index)

    def __repr__(self):
        return "Clip(%s, %d frames @ %gfps)" % (self.key, len(self.frames), self.fps)


class Placement:
    def __init__(self, name, clip, index, x, y, width, height, anchor, trimmed=None):
        self.name = name
        self.clip = clip
        self.index = index
        self.x, self.y = int(x), int(y)
        self.width, self.height = int(width), int(height)
        self.anchor = anchor
        self.trimmed = trimmed   # (source_size, offset) when the frame was trimmed

    @property
    def rect(self):
        return (self.x, self.y, self.width, self.height)

    def to_dict(self):
        return {"name": self.name, "clip": self.clip, "index": self.index,
                "x": self.x, "y": self.y, "w": self.width, "h": self.height,
                "anchor": list(self.anchor)}


class Sheet:
    def __init__(self, pixels, placements, clips, layout, cell=None, padding=0,
                 extrude=0, scale=1):
        self.pixels = pixels
        self.placements = placements
        self.clips = clips
        self.layout = layout
        self.cell = cell          # (w, h) for a grid layout, None for packed
        self.padding = padding
        self.extrude = extrude
        self.scale = scale        # the export upscale already applied

    @property
    def size(self):
        height, width = self.pixels.shape[:2]
        return (width, height)

    def by_clip(self):
        grouped = {}
        for placement in self.placements:
            grouped.setdefault(placement.clip, []).append(placement)
        for entries in grouped.values():
            entries.sort(key=lambda placement: placement.index)
        return grouped

    def clip(self, key):
        for entry in self.clips:
            if entry.key == key:
                return entry
        return None


def _next_power_of_two(value):
    power = 1
    while power < value:
        power *= 2
    return power


def _extrude_into(sheet, frame, x, y, amount):
    """Repeat the frame's edge pixels `amount` px outward around its rect."""
    if amount <= 0:
        return
    height, width = frame.shape[:2]
    for step in range(1, amount + 1):
        img.paste(sheet, frame[:1, :], x, y - step)              # top
        img.paste(sheet, frame[-1:, :], x, y + height + step - 1)  # bottom
        img.paste(sheet, frame[:, :1], x - step, y)              # left
        img.paste(sheet, frame[:, -1:], x + width + step - 1, y)  # right
    # Corners: a single pixel each, or the diagonal shows through.
    for step_y in range(1, amount + 1):
        for step_x in range(1, amount + 1):
            for corner, cx, cy in ((frame[:1, :1], x - step_x, y - step_y),
                                   (frame[:1, -1:], x + width + step_x - 1, y - step_y),
                                   (frame[-1:, :1], x - step_x, y + height + step_y - 1),
                                   (frame[-1:, -1:], x + width + step_x - 1,
                                    y + height + step_y - 1)):
                img.paste(sheet, corner, cx, cy)


def pack(clips, layout="grid", padding=1, extrude=1, power_of_two=False,
         max_width=4096, scale=1):
    """Lay every clip's frames onto one texture."""
    if not clips:
        raise ValueError("nothing to pack")
    if scale > 1:
        clips = [Clip(clip.name,
                      [img.scale_nearest(frame, scale) for frame in clip.frames],
                      clip.fps, clip.loop, clip.direction,
                      loop_start=clip.loop_start, loop_end=clip.loop_end,
                      anchor=(clip.anchor[0] * scale, clip.anchor[1] * scale),
                      fidelity=clip.fidelity, note=clip.note)
                 for clip in clips]

    builder = {"grid": _pack_grid, "packed": _pack_shelf,
               "strip": _pack_strip}.get(layout)
    if builder is None:
        raise ValueError("unknown layout %r (grid | packed | strip)" % layout)
    pixels, placements, cell = builder(clips, padding, extrude, max_width)

    if power_of_two:
        height, width = pixels.shape[:2]
        target_w, target_h = _next_power_of_two(width), _next_power_of_two(height)
        if (target_w, target_h) != (width, height):
            grown = img.blank(target_h, target_w)
            img.paste(grown, pixels, 0, 0)
            pixels = grown
    return Sheet(pixels, placements, clips, layout, cell, padding, extrude, scale)


def _pack_grid(clips, padding, extrude, max_width):
    """Uniform cells, one row per clip, every frame aligned by its ANCHOR.

    The cell is not "the biggest frame" and frames are not centred in it. Both
    of those are wrong the moment one animation leaves the ground: centring a
    jump's apex frame in its cell puts the character's feet back on the floor
    and deletes the jump.

    Instead the cell is sized by how far the art reaches from the anchor in each
    of the four directions, across every frame in the sheet, and each frame is
    placed so its own anchor lands on the cell's anchor. Every cell then has the
    character's floor contact at the same pixel, which is exactly what an engine
    assumes when it swaps one animation for another.
    """
    gutter = padding + extrude
    left = right = top = bottom = 0
    for clip in clips:
        for frame in clip.frames:
            height, width = frame.shape[:2]
            left = max(left, clip.anchor[0])
            right = max(right, width - clip.anchor[0])
            top = max(top, clip.anchor[1])
            bottom = max(bottom, height - clip.anchor[1])
    cell_w, cell_h = left + right, top + bottom
    cell_anchor = (left, top)
    columns = max(len(clip.frames) for clip in clips)

    step_x, step_y = cell_w + 2 * gutter, cell_h + 2 * gutter
    width, height = columns * step_x, len(clips) * step_y
    if width > max_width:
        raise ValueError("a grid of %d columns is %dpx wide, over the %dpx limit; "
                         "use --layout packed or a smaller --scale"
                         % (columns, width, max_width))

    pixels = img.blank(height, width)
    placements = []
    for row, clip in enumerate(clips):
        offset_x = cell_anchor[0] - clip.anchor[0]
        offset_y = cell_anchor[1] - clip.anchor[1]
        for index, frame in enumerate(clip.frames):
            x = index * step_x + gutter + offset_x
            y = row * step_y + gutter + offset_y
            img.paste(pixels, frame, x, y)
            _extrude_into(pixels, frame, x, y, extrude)
            placements.append(Placement(
                clip.frame_name(index), clip.key, index,
                index * step_x + gutter, row * step_y + gutter, cell_w, cell_h,
                cell_anchor))
    return pixels, placements, (cell_w, cell_h)


def _pack_strip(clips, padding, extrude, max_width):
    """Every frame in one row, clips end to end. A horizontal strip.

    The oldest sprite-sheet layout there is, and still the one several importers
    want by default: GameMaker's Import Strip, and anything that slices by
    dividing the width by a frame count. It is the same cells as the grid,
    unrolled, so the anchor alignment carries over unchanged.
    """
    pixels, placements, cell = _pack_grid(clips, padding, extrude, 1 << 30)
    gutter = padding + extrude
    step_x = cell[0] + 2 * gutter
    step_y = cell[1] + 2 * gutter
    total = len(placements)
    width = total * step_x
    if width > max_width:
        raise ValueError("a strip of %d frames is %dpx wide, over the %dpx limit; "
                         "use --layout grid" % (total, width, max_width))

    strip = img.blank(step_y, width)
    ordered = sorted(placements, key=lambda p: (p.clip, p.index))
    out = []
    for slot, placement in enumerate(ordered):
        window = pixels[placement.y - gutter:placement.y - gutter + step_y,
                        placement.x - gutter:placement.x - gutter + step_x]
        img.paste(strip, window, slot * step_x, 0)
        out.append(Placement(placement.name, placement.clip, placement.index,
                             slot * step_x + gutter, gutter,
                             placement.width, placement.height, placement.anchor))
    return strip, out, cell


def _pack_shelf(clips, padding, extrude, max_width):
    """Shelf packing: tallest first, rows filled left to right.

    Not optimal -- MaxRects would beat it by a few percent -- but it is stable,
    it is 30 lines, and on sprite frames that are all within a factor of two of
    each other the few percent is not worth a dependency or the bug surface.
    """
    gutter = padding + extrude
    entries = []
    for clip in clips:
        for index, frame in enumerate(clip.frames):
            entries.append((clip, index, frame))
    entries.sort(key=lambda entry: (-entry[2].shape[0], -entry[2].shape[1]))

    widest = max(frame.shape[1] for _, _, frame in entries) + 2 * gutter
    limit = max(widest, min(max_width, int(np.ceil(np.sqrt(
        sum((frame.shape[0] + 2 * gutter) * (frame.shape[1] + 2 * gutter)
            for _, _, frame in entries))) * 1.15)))

    spots, cursor_x, cursor_y, shelf_h = [], 0, 0, 0
    for clip, index, frame in entries:
        frame_h, frame_w = frame.shape[:2]
        need_w, need_h = frame_w + 2 * gutter, frame_h + 2 * gutter
        if cursor_x + need_w > limit and cursor_x > 0:
            cursor_x, cursor_y, shelf_h = 0, cursor_y + shelf_h, 0
        spots.append((clip, index, frame, cursor_x + gutter, cursor_y + gutter))
        cursor_x += need_w
        shelf_h = max(shelf_h, need_h)

    width = max(x + frame.shape[1] + gutter for _, _, frame, x, _ in spots)
    height = max(y + frame.shape[0] + gutter for _, _, frame, _, y in spots)
    pixels = img.blank(height, width)

    placements = []
    for clip, index, frame, x, y in spots:
        img.paste(pixels, frame, x, y)
        _extrude_into(pixels, frame, x, y, extrude)
        placements.append(Placement(clip.frame_name(index), clip.key, index,
                                    x, y, frame.shape[1], frame.shape[0], clip.anchor))
    placements.sort(key=lambda placement: (placement.clip, placement.index))
    return pixels, placements, None
