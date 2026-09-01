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
    def __init__(self, rig, sprites, reference, strays=0):
        self.rig = rig
        self.sprites = sprites      # list, already in draw order
        self.reference = reference
        # How many opaque pixels fell outside every declared box and were
        # absorbed by the root. Not an error -- boxes are not a tiling -- but a
        # large number means the rig missed something the user can see.
        self.strays = strays
        self._ramps = None

    def ramp_table(self):
        """The shading ramps of the source art, for the `cycle` channel.

        Built from the WHOLE reference rather than per part, so a step means the
        same thing everywhere: two parts sharing a material step together, which
        is what makes a lit window and its frame brighten as one thing.
        Computed once and kept, because a clip may ask for it on every frame.
        """
        if self._ramps is None:
            from . import palette as palette_module
            self._ramps = palette_module.ramp_steps(
                palette_module.lock(self.reference), self.reference)
        return self._ramps

    def by_name(self, name):
        for sprite in self.sprites:
            if sprite.name == name:
                return sprite
        return None

    def ground_points(self):
        """Every part's opaque pixels, in reference coordinates, ready to transform.

        Used to find where the character's lowest point actually is in a pose.
        The declared BOX is not good enough for that: when a leg rotates, the
        box's lowest corner is a corner, not a foot, and the two differ by
        enough to leave a character floating.

        A `shadow` part is excluded, because it is the floor rather than the
        character and would report the same row in every frame.
        """
        points = {}
        for sprite in self.sprites:
            part = self.rig.by_name(sprite.name)
            if part is not None and part.role == "shadow":
                continue
            rows, columns = np.nonzero(img.alpha_mask(sprite.pixels))
            if not rows.size:
                continue
            points[sprite.name] = np.stack(
                [columns + sprite.origin[0], rows + sprite.origin[1],
                 np.ones(rows.shape)], axis=0)
        return points

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
    reach = _reach(rig, mask)

    order = sorted(range(len(rig.parts)),
                   key=lambda index: (-rig.parts[index].area, rig.parts[index].z))
    for index in order:
        part = rig.parts[index]
        x0, y0, x1, y1 = part.box
        window = mask[y0:y1, x0:x1]
        area = float(part.area)
        target = best[y0:y1, x0:x1]
        claim = window & (area <= target)
        limit = reach[index]
        if limit is not None:
            claim = claim & limit[y0:y1, x0:x1]
        owner[y0:y1, x0:x1][claim] = index
        target[claim] = area

    # A pixel no box covered still has to go somewhere or it vanishes from every
    # frame. The root carries it: it is the part that never moves relative to
    # itself, so a stray pixel there is stationary rather than flying. `cut`
    # grows the root's extraction window to reach them.
    root = rig.root
    if root is not None:
        stray = mask & (owner < 0)
        if stray.any():
            owner[stray] = rig.parts.index(root)

    _prefer_near(rig, owner, mask)
    return owner


def _reach(rig, mask):
    """Per part, the pixels of its box it is allowed to claim -- or None.

    Only one kind of part is limited, and it is the one that turns. A part with
    the `spinner` trait sweeps a full revolution about its pivot, so everything
    it owns travels a circle centred there; a pixel further from the hub than
    the pivot's distance to the nearest edge of the part's own box leaves that
    box entirely on the way round, which means the rigger who drew the box did
    not mean to include it. Sails drawn as a cross through a tower cannot be
    separated from the tower by a rectangle -- but they can by a disc.

    A pixel a spinner gives up is not lost: the claim loop is still running, so
    it falls to the next smallest box that covers it, and the root's
    absorb-the-strays rule below catches whatever is left. Ownership stays a
    total function, so REST is untouched -- which is the property that makes
    this safe to do at all.

    Measured against the artist's own four sail-rotation frames: of the pixels
    our clip disturbs, the share the artist never moves goes from 40% to 9%,
    and `quality.shed` reports 0.00% either way. See `quality.footprint`.
    """
    limits = [None] * len(rig.parts)
    grid = None
    for index, part in enumerate(rig.parts):
        if not part.has_trait("spinner") or part.pivot is None:
            continue
        x0, y0, x1, y1 = part.box
        px, py = part.pivot
        radius = min(px - x0, x1 - px, py - y0, y1 - py)
        if radius <= 0:
            # The hub is outside its own box; there is no disc to speak of and
            # clipping to nothing would silently empty the part.
            continue
        if grid is None:
            grid = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
        rows, columns = grid
        limits[index] = ((columns - px) ** 2 + (rows - py) ** 2) <= radius ** 2
    return limits


def _prefer_near(rig, owner, mask):
    """A far limb never takes a pixel its near partner's box also covers.

    Rigs routinely carry a `*_far` box drawn over the same pixels as its
    `*_near` partner: on a pure profile only one arm is visible, and the rig
    still needs both halves or the walk cycle has one arm. The vision prompt
    asks for exactly that.

    Smallest-box-wins then decides the shared pixels by whichever box happened
    to be a couple of pixels tighter -- and when that is the far one, the only
    visible arm is drawn BEHIND the body and the character appears to have no
    arms at all. Near means "the one you can see", so near wins the overlap. It
    is the same principle as smallest-box-wins: the part the viewer would point
    at is the part that owns the pixel.
    """
    from .rig import PAIRED

    for index, part in enumerate(rig.parts):
        if not part.role.endswith("_far"):
            continue
        partner_role = PAIRED.get(part.role)
        for other_index, other in enumerate(rig.parts):
            if other.role != partner_role or other_index == index:
                continue
            x0, y0 = max(part.box[0], other.box[0]), max(part.box[1], other.box[1])
            x1, y1 = min(part.box[2], other.box[2]), min(part.box[3], other.box[3])
            if x1 <= x0 or y1 <= y0:
                continue
            window = owner[y0:y1, x0:x1]
            window[(window == index) & mask[y0:y1, x0:x1]] = other_index


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


def extraction_boxes(rig, owner):
    """The window each part is actually cut from: its box, grown to its pixels.

    A part is normally cut from its declared box, because that is where its
    pixels are. The root is the exception: it inherits every pixel no box
    covered, and on a real rig there are always some -- a vision model draws
    boxes around the parts it can name, not a tiling of the image, so a hem, a
    stray tuft of hair or a scrap of shadow falls outside all of them.

    Cutting the root from its declared box would drop exactly those pixels, and
    drop them SILENTLY: the sheet still builds, still looks right, and is
    missing a hundred pixels of the user's art. Growing the window to the
    pixels a part owns is what makes the partition genuinely exact, which is
    the property `verify.py`'s REST check exists to prove.
    """
    boxes = []
    for index, part in enumerate(rig.parts):
        x0, y0, x1, y1 = part.box
        owned = owner == index
        if owned.any():
            rows = np.flatnonzero(owned.any(axis=1))
            cols = np.flatnonzero(owned.any(axis=0))
            x0, y0 = min(x0, int(cols[0])), min(y0, int(rows[0]))
            x1, y1 = max(x1, int(cols[-1]) + 1), max(y1, int(rows[-1]) + 1)
        boxes.append((x0, y0, x1, y1))
    return boxes


def cut(rig, reference_pixels, backfill=True):
    """Split the reference into PartSprites according to the rig."""
    mask = img.alpha_mask(reference_pixels)
    owner = ownership(rig, mask)
    boxes = extraction_boxes(rig, owner)

    sprites = []
    for index, part in enumerate(rig.parts):
        x0, y0, x1, y1 = boxes[index]
        own = (owner[y0:y1, x0:x1] == index)
        pixels = np.where(own[:, :, None], reference_pixels[y0:y1, x0:x1], 0).astype(np.uint8)
        sprites.append(PartSprite(part.name, pixels, (x0, y0), part.pivot,
                                  part.z, part.role))

    if backfill:
        _backfill(rig, sprites, owner, mask, boxes)

    strays = int((mask & _uncovered(rig, mask.shape)).sum())
    sprites.sort(key=lambda sprite: (sprite.z, sprite.name))
    return Cutout(rig, sprites, reference_pixels, strays)


def _uncovered(rig, shape):
    """Mask of the pixels no part's declared box reaches."""
    covered = np.zeros(shape, dtype=bool)
    for part in rig.parts:
        x0, y0, x1, y1 = part.box
        covered[y0:y1, x0:x1] = True
    return ~covered


def _backfill(rig, sprites, owner, mask, boxes):
    """Grow each part under the parts that overlap it from in front."""
    for index, part in enumerate(rig.parts):
        x0, y0, x1, y1 = boxes[index]
        sprite = next(s for s in sprites if s.name == part.name)
        holes = np.zeros((y1 - y0, x1 - x0), dtype=bool)
        for other_index, other in enumerate(rig.parts):
            if other_index == index or other.z <= part.z:
                continue
            ox0, oy0, ox1, oy1 = boxes[other_index]
            ix0, iy0 = max(x0, ox0), max(y0, oy0)
            ix1, iy1 = min(x1, ox1), min(y1, oy1)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            window = owner[iy0:iy1, ix0:ix1] == other_index
            holes[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] |= window & mask[iy0:iy1, ix0:ix1]
        if holes.any():
            _grow_into(sprite.pixels, holes)
