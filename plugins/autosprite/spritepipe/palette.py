"""The palette guarantee, and the ramps that make recolouring work.

Every transform in this pipeline is nearest-neighbour, so in principle no output
pixel can carry a colour the input did not have. `enforce` does not trust that
in principle: it checks, and snaps anything that escaped. The check is what
`verify.py` reports, and it is the difference between "we were careful" and "we
can prove it".

`ramps` exists for outfit and skin variants. Recolouring a sprite one flat
colour at a time destroys its shading; recolouring a whole RAMP -- the four or
five shades of one material, ordered dark to light -- keeps it, because the
shading was always relative.
"""

import numpy as np

from . import image as img


def lock(pixels):
    """Every distinct opaque RGBA in the art, as an (N, 4) uint8 array."""
    return img.unique_colors(pixels)


def escapes(pixels, palette):
    """Colours present in `pixels` that are not in `palette`."""
    present = img.unique_colors(pixels)
    if present.size == 0 or palette.size == 0:
        return present
    allowed = {tuple(int(v) for v in colour) for colour in palette}
    return np.array([colour for colour in present
                     if tuple(int(v) for v in colour) not in allowed],
                    dtype=np.uint8).reshape(-1, 4)


def enforce(pixels, palette):
    """Snap every opaque pixel to its nearest palette entry. Usually a no-op.

    Distance is plain squared RGB. Sprite palettes are small and well separated,
    and a perceptual metric here would buy nothing except a dependency: the only
    pixels this ever moves are ones a resampler nudged by a few units, and every
    metric agrees about where those belong.
    """
    if palette.size == 0:
        return pixels
    out = pixels.copy()
    solid = img.alpha_mask(out)
    if not solid.any():
        return out
    known = {tuple(int(v) for v in colour) for colour in palette}
    flat = out[solid]
    unknown = np.array([tuple(int(v) for v in row) not in known for row in flat])
    if not unknown.any():
        return out
    targets = flat[unknown][:, :3].astype(np.int32)
    reference = palette[:, :3].astype(np.int32)
    distance = ((targets[:, None, :] - reference[None, :, :]) ** 2).sum(axis=2)
    picked = palette[np.argmin(distance, axis=1)]
    replaced = flat.copy()
    replaced[unknown] = picked
    out[solid] = replaced
    return out


def luminance(colour):
    red, green, blue = (float(v) for v in colour[:3])
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _hue_sat(colour):
    red, green, blue = (float(v) / 255.0 for v in colour[:3])
    high, low = max(red, green, blue), min(red, green, blue)
    span = high - low
    if span < 1e-6:
        return 0.0, 0.0
    if high == red:
        hue = ((green - blue) / span) % 6.0
    elif high == green:
        hue = (blue - red) / span + 2.0
    else:
        hue = (red - green) / span + 4.0
    return hue * 60.0, span / high


def ramps(palette, pixels=None, hue_tolerance=28.0):
    """Group the palette into shading ramps, each sorted dark to light.

    A ramp is one material: the shades an artist used for the skin, or the
    cloak, or the metal. Two facts define one, and using only the first is why
    naive recolouring merges materials:

    **Shades of one material share a hue.** Artists shade by moving value far
    more than hue, so a hue window with a generous tolerance groups them.

    **Shades of one material TOUCH.** A ramp is painted as light beside midtone
    beside shadow, so its shades are adjacent somewhere in the image. Two
    materials that happen to share a hue -- brown leather boots and tan skin,
    which sit within a few degrees of each other on any real sprite -- do not
    touch, because the body is between them. Requiring adjacency separates them;
    hue alone cannot, at any tolerance.

    Pass `pixels` to use adjacency. Without it this falls back to hue grouping
    alone, which is the right answer when all you have is a palette and no art.

    Two materials of the same hue that genuinely do touch -- a tan glove on a tan
    arm -- still merge. That case is ambiguous from colour alone, and the honest
    resolution is the naming step looking at `ramp_atlas`, not a cleverer
    threshold here.
    """
    count = len(palette)
    if count == 0:
        return []

    traits = [_hue_sat(colour) for colour in palette]
    grey = [saturation < 0.12 for _, saturation in traits]

    def compatible(left, right):
        if grey[left] != grey[right]:
            return False
        if grey[left]:
            return True
        return _hue_gap(traits[left][0], traits[right][0]) <= hue_tolerance

    parent = list(range(count))

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[max(left, right)] = min(left, right)

    if pixels is None:
        for left in range(count):
            for right in range(left + 1, count):
                if compatible(left, right):
                    union(left, right)
    else:
        for left, right in _touching_pairs(pixels, palette):
            if compatible(left, right):
                union(left, right)

    grouped = {}
    for index in range(count):
        grouped.setdefault(find(index), []).append(index)

    out = []
    for rank, root in enumerate(sorted(grouped,
                                       key=lambda key: -len(grouped[key]))):
        members = grouped[root]
        ordered = sorted((palette[index] for index in members), key=luminance)
        hues = [traits[index][0] for index in members if not grey[index]]
        out.append({
            "id": rank,
            "hue": round(sum(hues) / len(hues), 1) if hues else 0.0,
            "grey": all(grey[index] for index in members),
            "colours": [[int(v) for v in colour] for colour in ordered],
        })
    return out


def _touching_pairs(pixels, palette):
    """Every pair of palette indices that are four-adjacent somewhere in the art."""
    lookup = {tuple(int(v) for v in colour): index
              for index, colour in enumerate(palette)}
    flat = pixels.reshape(-1, 4)
    unique, inverse = np.unique(flat, axis=0, return_inverse=True)
    table = np.array([lookup.get(tuple(int(v) for v in row), -1) for row in unique],
                     dtype=np.int32)
    indexed = table[inverse].reshape(pixels.shape[:2])

    pairs = set()
    for left, right in ((indexed[:, :-1], indexed[:, 1:]),
                        (indexed[:-1, :], indexed[1:, :])):
        both = (left >= 0) & (right >= 0) & (left != right)
        if both.any():
            for a, b in zip(left[both].tolist(), right[both].tolist()):
                pairs.add((min(a, b), max(a, b)))
    return pairs


def _hue_gap(left, right):
    gap = abs(left - right) % 360.0
    return min(gap, 360.0 - gap)


def _hue_mean(current, new, count):
    return current + _signed_gap(current, new) / max(1, count)


def _signed_gap(left, right):
    gap = (right - left + 180.0) % 360.0 - 180.0
    return gap


def coverage(pixels, palette):
    """How much of the art each palette entry accounts for, most-used first.

    Useful in the report: an entry that covers 40% of the sprite is the base
    colour and a variant that changes it changes the character; one that covers
    0.3% is an eye highlight and changing it changes nothing anyone will see.
    """
    solid = img.alpha_mask(pixels)
    flat = pixels[solid]
    total = max(1, len(flat))
    counts = []
    for colour in palette:
        hits = int((flat == colour).all(axis=1).sum())
        counts.append({"colour": [int(v) for v in colour],
                       "pixels": hits, "share": round(hits / total, 4)})
    return sorted(counts, key=lambda entry: -entry["pixels"])
