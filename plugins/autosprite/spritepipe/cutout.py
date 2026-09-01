"""Cut the character into its parts, using only the character's own pixels.

Two properties matter here and both are testable:

**The partition is exact.** Every opaque pixel belongs to exactly one part, so
compositing the parts back at their rest positions reproduces the reference
image byte for byte. `verify.py` checks it. Without that property the rest frame
of every animation is subtly wrong, and a subtly wrong idle frame is the one the
player stares at longest.

**A swinging limb leaves the body intact.** The near arm's pixels sit on top of
the torso and belong to the arm; the instant the arm rotates, the torso has an
arm-shaped hole in it. So each part is backfilled underneath the parts that
overlap it from in front, by growing that part's own colours into the gap. The
fill is invisible at rest -- the arm still covers it -- and is what the player
sees once the arm moves.
"""

import numpy as np

from . import image as img


class PartSprite:
    def __init__(self, name, pixels, origin, pivot, z, role):
        self.name = name
        self.pixels = pixels        # (h, w, 4) uint8, the part's own art
        self.origin = origin        # (x, y) of pixels[0,0] in reference space
        self.pivot = pivot          # (x, y) in reference space
        self.z = z
        self.role = role

    @property
    def pivot_local(self):
        return (self.pivot[0] - self.origin[0], self.pivot[1] - self.origin[1])

    def __repr__(self):
        return "PartSprite(%s, %dx%d at %s)" % (
            self.name, self.pixels.shape[1], self.pixels.shape[0], self.origin)


class Cutout:
    def __init__(self, rig, sprites, reference):
        self.rig = rig
        self.sprites = sprites      # list, already in draw order
        self.reference = reference

    def by_name(self, name):
        for sprite in self.sprites:
            if sprite.name == name:
                return sprite
        return None

    def rest(self):
        """Composite every part at its rest position. Must equal the reference."""
        width, height = self.rig.size
        canvas = img.blank(height, width)
        for sprite in self.sprites:
            img.paste(canvas, sprite.pixels, sprite.origin[0], sprite.origin[1])
        return canvas


def ownership(rig, mask):
    """Index of the owning part for every pixel; -1 where nothing owns it.

    The smallest box containing a pixel wins. That single rule is what lets a
    vision model draw a head box inside a torso box and still get the right
    answer, and it is why the prompt tells the model that overlap is fine. Ties
    -- two boxes of exactly equal area over one pixel -- go to the part drawn in
    front, because that is the one the user can see and therefore the one they
    would name.
    """
    height, width = mask.shape
    owner = np.full((height, width), -1, dtype=np.int32)
    best = np.full((height, width), np.inf)

    order = sorted(range(len(rig.parts)),
                   key=lambda index: (-rig.parts[index].area, rig.parts[index].z))
    for index in order:
        part = rig.parts[index]
        x0, y0, x1, y1 = part.box
        window = mask[y0:y1, x0:x1]
        area = float(part.area)
        target = best[y0:y1, x0:x1]
        claim = window & (area <= target)
        owner[y0:y1, x0:x1][claim] = index
        target[claim] = area

    # A pixel no box covered still has to go somewhere or it vanishes from every
    # frame. The root carries it: it is the part that never moves relative to
    # itself, so a stray pixel there is stationary rather than flying.
    root = rig.root
    if root is not None:
        stray = mask & (owner < 0)
        if stray.any():
            owner[stray] = rig.parts.index(root)
    return owner


def _grow_into(pixels, holes, rounds=64):
    """Fill `holes` with the nearest existing colour in `pixels`, in place.

    Four-connected dilation rather than a real distance transform: on sprite-
    sized art it converges in a handful of rounds, it introduces no colour that
    was not already in this part, and it needs no dependency beyond numpy.
    """
    solid = img.alpha_mask(pixels)
    if not solid.any() or not holes.any():
        return pixels
    todo = holes & ~solid
    for _ in range(rounds):
        if not todo.any():
            break
        filled = False
        for shift, axis in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            donor = np.roll(solid, shift, axis=axis)
            donor_pixels = np.roll(pixels, shift, axis=axis)
            # Rolling wraps; a donor from the opposite edge is not a neighbour.
            if axis == 0:
                (donor[0] if shift == 1 else donor[-1]).fill(False)
            else:
                (donor[:, 0] if shift == 1 else donor[:, -1]).fill(False)
            take = todo & donor
            if take.any():
                pixels[take] = donor_pixels[take]
                solid |= take
                todo &= ~take
                filled = True
        if not filled:
            break
    return pixels


def cut(rig, reference_pixels, backfill=True):
    """Split the reference into PartSprites according to the rig."""
    mask = img.alpha_mask(reference_pixels)
    owner = ownership(rig, mask)

    sprites = []
    for index, part in enumerate(rig.parts):
        x0, y0, x1, y1 = part.box
        own = (owner[y0:y1, x0:x1] == index)
        pixels = np.where(own[:, :, None], reference_pixels[y0:y1, x0:x1], 0).astype(np.uint8)
        sprites.append(PartSprite(part.name, pixels, (x0, y0), part.pivot,
                                  part.z, part.role))

    if backfill:
        _backfill(rig, sprites, owner, mask)

    sprites.sort(key=lambda sprite: (sprite.z, sprite.name))
    return Cutout(rig, sprites, reference_pixels)


def _backfill(rig, sprites, owner, mask):
    """Grow each part under the parts that overlap it from in front."""
    for index, part in enumerate(rig.parts):
        x0, y0, x1, y1 = part.box
        sprite = next(s for s in sprites if s.name == part.name)
        holes = np.zeros((y1 - y0, x1 - x0), dtype=bool)
        for other_index, other in enumerate(rig.parts):
            if other_index == index or other.z <= part.z:
                continue
            ox0, oy0, ox1, oy1 = other.box
            ix0, iy0 = max(x0, ox0), max(y0, oy0)
            ix1, iy1 = min(x1, ox1), min(y1, oy1)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            window = owner[iy0:iy1, ix0:ix1] == other_index
            holes[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] |= window & mask[iy0:iy1, ix0:ix1]
        if holes.any():
            _grow_into(sprite.pixels, holes)
