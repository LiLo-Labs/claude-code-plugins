"""The image type the whole pipeline passes around: an (H, W, 4) uint8 array.

Everything here is nearest-neighbour and integer. That is not a performance
choice -- it is the reason `verify.py` can promise that the output palette is a
subset of the input palette. The moment a bilinear resample or an alpha blend
runs over sprite pixels it invents colours that were never in the user's art,
and on pixel art those invented colours read as mud along every edge.
"""

import numpy as np
from PIL import Image as PILImage

# Anything at or below this alpha is treated as absent. Sprite sheets are
# composited by the GPU with alpha testing far more often than with real
# blending, so a pixel that is 40% opaque is a pixel that will flicker.
ALPHA_FLOOR = 8


def load(path):
    """Read a PNG/JPG/GIF/BMP as (H, W, 4) uint8 RGBA."""
    with PILImage.open(path) as handle:
        return np.array(handle.convert("RGBA"), dtype=np.uint8)


def save(array, path):
    """Write (H, W, 4) uint8 RGBA as a PNG. No quantisation, no profile."""
    PILImage.fromarray(np.ascontiguousarray(array), mode="RGBA").save(path, "PNG")


def save_indexed(array, path, max_colors=255):
    """Write as a palette PNG, or return False and write nothing.

    AutoSprite offers a "compressed" export that is a palette-quantised PNG
    around 70% smaller than full RGBA. This plugin can offer the same thing
    without the "quantised" part: the sheet's palette is provably a subset of
    the source art's, so on any sprite with 255 colours or fewer the indexed
    file is LOSSLESS -- the same pixels, in a fraction of the bytes.

    Index 255 is reserved for transparency, so the caller gets an exact
    round-trip or nothing. A sprite with more colours than that is a
    photograph, and it says so rather than throwing away colours the palette
    guarantee promised to keep.
    """
    from PIL import Image as PILImage

    solid = alpha_mask(array)
    colours = unique_colors(array)
    if len(colours) > max_colors:
        return False

    table = {tuple(int(v) for v in colour): index
             for index, colour in enumerate(colours)}
    indexed = np.full(array.shape[:2], max_colors, dtype=np.uint8)
    flat = array[solid]
    if flat.size:
        indexed[solid] = [table[tuple(int(v) for v in row)] for row in flat]

    palette = []
    for colour in colours:
        palette.extend(int(v) for v in colour[:3])
    palette.extend([0, 0, 0] * (256 - len(colours)))

    picture = PILImage.fromarray(indexed, mode="P")
    picture.putpalette(palette[:768])
    picture.save(path, "PNG", transparency=max_colors, optimize=True)
    return True


def blank(height, width):
    return np.zeros((int(height), int(width), 4), dtype=np.uint8)


def alpha_mask(array):
    """Boolean mask of the pixels that actually exist."""
    return array[:, :, 3] > ALPHA_FLOOR


def harden_alpha(array):
    """Force every pixel to fully opaque or fully absent.

    Rotation and translation are done with NEAREST, so alpha only ever arrives
    here as a value the source already had -- except at the boundary of a
    transformed part, where the resampler can leave a stray edge value. Hardening
    keeps the sheet alpha-test clean and keeps frame comparison exact.
    """
    out = array.copy()
    solid = out[:, :, 3] > ALPHA_FLOOR
    out[:, :, 3] = np.where(solid, 255, 0).astype(np.uint8)
    out[~solid] = 0  # zero the colour too, so absent pixels compare equal
    return out


def content_box(array):
    """(x0, y0, x1, y1) half-open bounds of the non-transparent pixels.

    Returns None for an empty image rather than a degenerate box, because every
    caller has something specific and different to say about an empty frame.
    """
    mask = alpha_mask(array)
    if not mask.any():
        return None
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    return (int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1)


def crop(array, box):
    x0, y0, x1, y1 = box
    return array[y0:y1, x0:x1].copy()


def trim(array):
    """Crop to content. Returns (cropped, box); box is None if nothing was there."""
    box = content_box(array)
    if box is None:
        return array.copy(), None
    return crop(array, box), box


def paste(target, source, x, y):
    """Composite `source` onto `target` at (x, y) by alpha test, in place.

    Alpha *test*, not alpha blend: a source pixel either replaces the target
    pixel or leaves it alone. Two sprite parts overlapping must not average into
    a third colour.
    """
    height, width = source.shape[:2]
    tall, wide = target.shape[:2]

    sx0, sy0 = max(0, -x), max(0, -y)
    tx0, ty0 = max(0, x), max(0, y)
    span_x = min(width - sx0, wide - tx0)
    span_y = min(height - sy0, tall - ty0)
    if span_x <= 0 or span_y <= 0:
        return target

    patch = source[sy0:sy0 + span_y, sx0:sx0 + span_x]
    window = target[ty0:ty0 + span_y, tx0:tx0 + span_x]
    window[patch[:, :, 3] > ALPHA_FLOOR] = patch[patch[:, :, 3] > ALPHA_FLOOR]
    return target


def scale_nearest(array, factor):
    """Integer or fractional nearest-neighbour scale. No new colours, ever."""
    if factor == 1:
        return array.copy()
    height, width = array.shape[:2]
    new_h, new_w = max(1, int(round(height * factor))), max(1, int(round(width * factor)))
    rows = np.clip((np.arange(new_h) / factor).astype(np.int64), 0, height - 1)
    cols = np.clip((np.arange(new_w) / factor).astype(np.int64), 0, width - 1)
    return array[rows][:, cols].copy()


def downscale_blocks(array, factor):
    """Undo an integer upscale by sampling the centre of every factor x factor block.

    Only correct when the image really is an upscale of a smaller grid, which is
    what `ingest.detect_pixel_scale` establishes before this is called.
    """
    factor = int(factor)
    if factor <= 1:
        return array.copy()
    height, width = array.shape[:2]
    rows = np.arange(factor // 2, height, factor)
    cols = np.arange(factor // 2, width, factor)
    return array[rows][:, cols].copy()


def unique_colors(array, include_transparent=False):
    """Every distinct RGBA value present, as an (N, 4) uint8 array."""
    flat = array.reshape(-1, 4)
    if not include_transparent:
        flat = flat[flat[:, 3] > ALPHA_FLOOR]
    if flat.size == 0:
        return np.zeros((0, 4), dtype=np.uint8)
    return np.unique(flat, axis=0)


def equal(left, right):
    """Exact pixel equality, shape included. The verifier's whole vocabulary."""
    return left.shape == right.shape and bool(np.array_equal(left, right))
