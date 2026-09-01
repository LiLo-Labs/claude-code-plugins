"""Turn whatever the user actually has into the one normalised reference the
rest of the pipeline is allowed to assume.

Three things go wrong with real inputs, and all three are silent:

1. **The art is an upscale.** A 32x32 sprite exported at 512x512 is 16x16 blocks
   of flat colour. Rig it at 512 and every rotation shears those blocks into
   staircases. Detect the block size and work at native resolution instead.
2. **The background is opaque.** A PNG off a website has a white or checkered
   background baked in. Cut it out by flooding from the border, not by keying a
   single colour, because anti-aliased art has a halo the key would miss.
3. **The art is anti-aliased.** Then it has hundreds of near-duplicate colours
   and the palette guarantee becomes meaningless. Say so in the report; do not
   quietly posterise the user's art behind their back.
"""

import numpy as np

from . import image as img


class Reference:
    """The normalised character: pixels, palette, and how we got here."""

    def __init__(self, pixels, palette, scale, source_size, report):
        self.pixels = pixels          # (H, W, 4) uint8, trimmed, background removed
        self.palette = palette        # (N, 4) uint8, every colour the art uses
        self.scale = scale            # the integer upscale factor that was undone
        self.source_size = source_size  # (width, height) of the file on disk
        self.report = report          # dict of everything worth telling the user

    @property
    def size(self):
        height, width = self.pixels.shape[:2]
        return (width, height)

    def summary(self):
        width, height = self.size
        return {
            "source_size": list(self.source_size),
            "working_size": [width, height],
            "pixel_scale": self.scale,
            "palette_size": int(len(self.palette)),
            **self.report,
        }


def detect_pixel_scale(array, limit=16):
    """Largest k <= limit for which the image is constant on every k x k block.

    Checked on the opaque region only. A transparent margin is not evidence
    either way and, on a trimmed sprite, is exactly where an off-by-one lands.
    """
    height, width = array.shape[:2]
    best = 1
    for factor in range(2, int(limit) + 1):
        if height % factor or width % factor:
            continue
        blocks = array.reshape(height // factor, factor, width // factor, factor, 4)
        # Every pixel in a block must equal that block's top-left pixel.
        if np.array_equal(blocks, blocks[:, :1, :, :1].repeat(factor, 1).repeat(factor, 3)):
            best = factor
    return best


def _border_seeds(height, width):
    top = [(0, x) for x in range(width)]
    bottom = [(height - 1, x) for x in range(width)]
    left = [(y, 0) for y in range(height)]
    right = [(y, width - 1) for y in range(height)]
    return top + bottom + left + right


def flood_background(array, tolerance=12):
    """Mask of pixels reachable from the border without crossing a colour edge.

    Four-connected flood, compared against the seed's own colour rather than a
    running average, so a gradient background stops the flood instead of eating
    into the character one shade at a time.
    """
    height, width = array.shape[:2]
    rgb = array[:, :, :3].astype(np.int16)
    visited = np.zeros((height, width), dtype=bool)
    background = np.zeros((height, width), dtype=bool)

    stack = []
    for y, x in _border_seeds(height, width):
        if not visited[y, x]:
            visited[y, x] = True
            stack.append((y, x, rgb[y, x].copy()))
            background[y, x] = True

    while stack:
        y, x, seed = stack.pop()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < height and 0 <= nx < width and not visited[ny, nx]:
                visited[ny, nx] = True
                if int(np.abs(rgb[ny, nx] - seed).max()) <= tolerance:
                    background[ny, nx] = True
                    stack.append((ny, nx, seed))
    return background


def remove_background(array, tolerance=12, min_transparent_fraction=0.02):
    """Return (pixels, how) with the background cut to alpha 0.

    If the file already carries real transparency we believe it and stop. An
    artist who exported with alpha has already answered this question, and a
    flood on top of that answer can only lose to it.
    """
    height, width = array.shape[:2]
    transparent = (array[:, :, 3] <= img.ALPHA_FLOOR).sum() / float(height * width)
    if transparent >= min_transparent_fraction:
        return array.copy(), "source alpha (%.0f%% already transparent)" % (transparent * 100)

    background = flood_background(array, tolerance=tolerance)
    covered = background.sum() / float(height * width)
    if covered >= 0.98:
        # The flood ate the whole image: the art is the same colour as its
        # border, so there is no background to find. Leave the pixels alone --
        # unless the image is genuinely uniform, in which case there is no art
        # here at all and `ingest` says so rather than returning a coloured
        # rectangle and letting the user find out at the sheet.
        if len(img.unique_colors(array)) <= 1:
            return array.copy(), "uniform image"
        return array.copy(), "no background found (flood covered the whole image)"

    out = array.copy()
    out[background] = 0
    return out, "flood from border, tolerance %d (%.0f%% removed)" % (tolerance, covered * 100)


def classify_art(palette, pixel_count):
    """Is this palette-based art or a photograph/painting?

    The palette guarantee -- every output colour came from the input -- holds
    either way, but it only *means* something when the palette is small enough
    to be a deliberate choice. Above a few hundred colours, say so.
    """
    count = int(len(palette))
    if count <= 64:
        return "indexed", "%d colours: palette art, transforms stay exact" % count
    if count <= 512:
        return "limited", "%d colours: limited palette, minor edge softening likely" % count
    ratio = count / float(max(1, pixel_count))
    return "continuous", (
        "%d colours (%.0f%% of pixels are unique): anti-aliased or photographic art. "
        "Rotation is still nearest-neighbour so no colour is invented, but edges "
        "will look ragged rather than smooth." % (count, ratio * 100)
    )


def ingest(path, tolerance=12, native=True, max_pixel_scale=16):
    """Load a character image and normalise it into a Reference."""
    raw = img.load(path)
    source_height, source_width = raw.shape[:2]

    keyed, how = remove_background(raw, tolerance=tolerance)
    keyed = img.harden_alpha(keyed)

    if how == "uniform image":
        raise ValueError(
            "%s is a single flat colour with nothing drawn on it. If the "
            "character really is one colour on a background of the same "
            "colour, supply art with alpha instead." % path)

    trimmed, box = img.trim(keyed)
    if box is None:
        raise ValueError(
            "%s has no opaque pixels left after background removal. If the "
            "character is the same colour as its background, pass a lower "
            "--tolerance or supply art with alpha." % path
        )

    scale = detect_pixel_scale(trimmed, limit=max_pixel_scale) if native else 1
    pixels = img.downscale_blocks(trimmed, scale) if scale > 1 else trimmed

    palette = img.unique_colors(pixels)
    height, width = pixels.shape[:2]
    kind, note = classify_art(palette, int(img.alpha_mask(pixels).sum()))

    report = {
        "background": how,
        "content_box": list(box),
        "art_kind": kind,
        "art_note": note,
    }
    if scale > 1:
        report["pixel_scale_note"] = (
            "source is a %dx upscale of a %dx%d grid; rigging and animation run "
            "at native size and the sheet is scaled back up on export" %
            (scale, width, height)
        )
    return Reference(pixels, palette, scale, (source_width, source_height), report)
