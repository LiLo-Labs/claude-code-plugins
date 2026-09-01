"""What the user looks at before they believe any of this.

A sprite sheet is unreviewable as a sheet. Nobody can tell a good walk cycle
from a limping one by reading 8 cells in a grid -- the whole judgement is in the
timing, which a still image does not have. So the pipeline always writes a
looping GIF per clip at the clip's real frame rate, and a contact sheet with the
frames numbered for talking about which one is wrong.

The GIFs are the deliverable of the review step, not a nicety. A rig that put
the hips at chest height is obvious in one second of animation and invisible in
the JSON.
"""

import os

import numpy as np
from PIL import Image as PILImage

from . import image as img


def _to_paletted(frame, background):
    """RGBA -> P with one index reserved for transparency.

    GIF has no alpha channel, only a single transparent index, so every
    partially transparent pixel has to become fully one or fully the other. The
    pipeline hardens alpha long before this, so nothing is lost -- but the
    background colour still shows through anywhere the sprite is absent, which
    is why it is a parameter and defaults to something no sprite palette
    contains.
    """
    solid = img.alpha_mask(frame)
    flat = frame[:, :, :3].copy()
    flat[~solid] = background
    picture = PILImage.fromarray(np.ascontiguousarray(flat), mode="RGB")
    # 255 colours, leaving index 255 free to mean "transparent".
    paletted = picture.convert("P", palette=PILImage.ADAPTIVE, colors=255)
    palette = paletted.getpalette() or []
    palette = (palette + [0] * 768)[:768]
    palette[255 * 3:255 * 3 + 3] = list(background)
    paletted.putpalette(palette)
    pixels = np.array(paletted)
    pixels[~solid] = 255
    out = PILImage.fromarray(pixels, mode="P")
    out.putpalette(palette)
    return out


def write_gif(frames, path, fps=10, loop=True, background=(255, 0, 255), scale=1):
    """One clip as an animated GIF at its real frame rate."""
    if not frames:
        return None
    if scale > 1:
        frames = [img.scale_nearest(frame, scale) for frame in frames]
    images = [_to_paletted(frame, background) for frame in frames]
    duration = max(20, int(round(1000.0 / max(0.001, float(fps)))))
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=duration, loop=0 if loop else 1,
                   transparency=255, disposal=2, optimize=False)
    return path


def contact_sheet(clips, path, scale=1, background=(28, 28, 34, 255), gutter=2):
    """Every clip as a labelled row, for pointing at the frame that is wrong."""
    if not clips:
        return None
    cell_w = max(frame.shape[1] for clip in clips for frame in clip.frames)
    cell_h = max(frame.shape[0] for clip in clips for frame in clip.frames)
    columns = max(len(clip.frames) for clip in clips)
    label = 9

    step_x = cell_w * scale + gutter
    step_y = cell_h * scale + gutter + label
    canvas = img.blank(len(clips) * step_y + gutter, columns * step_x + gutter)
    canvas[:, :] = background

    for row, clip in enumerate(clips):
        for index, frame in enumerate(clip.frames):
            drawn = img.scale_nearest(frame, scale) if scale > 1 else frame
            x = gutter + index * step_x + (cell_w * scale - drawn.shape[1]) // 2
            y = gutter + row * step_y + label + (cell_h * scale - drawn.shape[0])
            img.paste(canvas, drawn, x, y)
            _tick(canvas, gutter + index * step_x, gutter + row * step_y, index)
    img.save(canvas, path)
    return path


_DIGITS = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
}


def _tick(canvas, x, y, number, colour=(150, 150, 160, 255)):
    """A 3x5 frame number. A tiny bitmap font beats a font dependency here."""
    for offset, character in enumerate(str(int(number))):
        glyph = _DIGITS.get(character)
        if glyph is None:
            continue
        for row, bits in enumerate(glyph):
            for column, bit in enumerate(bits):
                if bit == "1":
                    py, px = y + 1 + row, x + 1 + offset * 4 + column
                    if 0 <= py < canvas.shape[0] and 0 <= px < canvas.shape[1]:
                        canvas[py, px] = colour


def write_all(clips, outdir, scale=1, background=(255, 0, 255)):
    """A GIF per clip plus one contact sheet. Returns what was written."""
    os.makedirs(outdir, exist_ok=True)
    written = {"gifs": {}}
    for clip in clips:
        path = os.path.join(outdir, "%s.gif" % clip.key)
        if write_gif(clip.frames, path, clip.fps, clip.loop, background, scale):
            written["gifs"][clip.key] = path
    sheet_path = os.path.join(outdir, "contact-sheet.png")
    written["contact_sheet"] = contact_sheet(clips, sheet_path, scale=scale)
    return written
