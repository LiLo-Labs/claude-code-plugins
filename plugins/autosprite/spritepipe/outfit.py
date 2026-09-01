"""Attach a separate item image to a character, so one item fits every character.

The problem this solves is not compositing. It is that a sword drawn once has to
end up in the right hand of a character it has never met, at the right size, in
front of the arm rather than behind it, and then swing with that arm through
every frame of every clip -- without the sword being redrawn and without the
character being redrawn.

The trick is to do it BEFORE anything else runs. An item is composited onto the
character's own art at rest, and the result becomes the source image the rest of
the pipeline sees. Two things fall out of that, and both matter more than the
convenience:

- **Every existing check still means what it meant.** REST still proves the
  parts reassemble into the source exactly, because the composed image IS the
  source. PALETTE still proves every output colour came from the input, because
  the input now contains the sword's colours too. Nothing had to be relaxed.
- **The item animates for free.** It is a part of the rig parented to the arm,
  so forward kinematics carries it. There is no separate item pipeline to keep
  in step, and a clip written years before the sword existed swings it.

A SOCKET is where an item goes: a named point on a named part. Sockets are
DERIVED from the rig rather than declared, which is what makes "works with every
character" true rather than aspirational -- a hand is the free end of the near
arm, and every humanoid rig has one whether or not its author thought about
outfitting.

The one real limitation, stated rather than discovered: an item goes IN FRONT of
the part it hangs on. Compositing at rest cannot record pixels that are hidden
at rest, so a scabbard behind a body would lose whatever the body covers. A
back-mounted item needs the item's own art to stay separate, which is a
different mechanism from this one.
"""

import numpy as np

from . import image as img
from . import rig as rig_module

# Where things go on a body, and what each is called. `part` is the role the
# socket hangs off; the point is derived from that part's own geometry.
SOCKETS = {
    "hand": ("arm_near", "free_end", "prop", 2),
    "off_hand": ("arm_far", "free_end", "prop", -1),
    "head": ("head", "top", "accessory", 2),
    "waist": ("torso", "bottom", "accessory", 2),
    "chest": ("torso", "middle", "accessory", 2),
}

# How long a thing in this socket is, as a multiple of the long axis of the part
# it hangs on. A sword is longer than the forearm holding it; a hat is about as
# wide as the head under it. These are the animator's rules of thumb, and they
# are what makes ONE sword fit every character rather than one sword fitting
# the character it happened to be drawn beside.
#
# The measurement that made this necessary: the CC0 sword is 30px long, and
# across seventeen corpus characters the arm it hangs on runs from 1px to 21px,
# so pasting it at its drawn size put it anywhere from 1.4x to 30x the length of
# that arm -- a twenty-one-fold spread, and on a 15px character a sword twice as
# tall as the character.
PROPORTIONS = {
    "hand": 2.0,
    "off_hand": 2.0,
    "head": 1.1,
    "waist": 1.0,
    "chest": 1.0,
}

# Pixel art does not scale by 0.37. A sprite reduced by a simple ratio keeps its
# grid -- every source pixel becomes a whole number of destination pixels, or a
# whole number of source pixels becomes one -- and one reduced by an arbitrary
# fraction gets a blade that is two pixels wide in one place and one in another.
# So the derived scale is snapped to the nearest of these before it is used.
RATIOS = (1 / 6.0, 1 / 5.0, 1 / 4.0, 1 / 3.0, 2 / 5.0, 1 / 2.0, 2 / 3.0,
          3 / 4.0, 1.0, 4 / 3.0, 3 / 2.0, 2.0, 3.0, 4.0)


def _long_axis(box):
    x0, y0, x1, y1 = box
    return max(x1 - x0, y1 - y0)


def snap_ratio(wanted):
    """The nearest simple ratio, in log space so 1/2 and 2 are equally near."""
    import math
    if wanted <= 0:
        return 1.0
    return min(RATIOS, key=lambda ratio: abs(math.log(ratio) - math.log(wanted)))


def fit(item_pixels, host_rig, socket, scale=None):
    """How much to scale an item so it belongs to this character.

    Returns the factor and the reason, because a silent resize is the kind of
    thing a user notices in the output and cannot explain. An explicit `scale`
    is taken as given and only reported -- the rule of thumb is a default, not
    a policy, and a dagger is a short sword rather than a small character.
    """
    if scale is not None:
        return float(scale), "as asked"
    available = sockets(host_rig)
    if socket not in available:
        return 1.0, "no such socket"
    owner, _point = available[socket]
    part = host_rig.by_name(owner)
    reach = _long_axis(part.box) * PROPORTIONS.get(socket, 1.0)
    box = img.content_box(item_pixels)
    drawn = _long_axis(box) if box is not None else max(item_pixels.shape[:2])
    if not drawn or not reach:
        return 1.0, "nothing drawn to measure"
    snapped = snap_ratio(reach / float(drawn))
    if snapped == 1.0:
        return 1.0, "already the right size for this %s" % owner
    return snapped, ("%gx: %d px drawn against a %d px %s"
                     % (snapped, drawn, _long_axis(part.box), owner))


def _free_end(part):
    """The end of a limb away from its own hinge.

    A limb's pivot is its shoulder or hip; the hand is at the other end. Which
    end that is depends on which way the limb is drawn, so it is measured rather
    than assumed: whichever of the box's two ends is further from the pivot,
    along whichever axis the limb is longer.
    """
    x0, y0, x1, y1 = part.box
    # A box's right and bottom are EXCLUSIVE, so the last pixel of the part is
    # one before them. Taking the far end as x1 or y1 put the socket a pixel
    # outside the limb -- and since an item's grip is at its own content edge,
    # that is a visible gap between a hand and what it is holding. It was on a
    # solid pixel of the character in one corpus rig out of five.
    right, bottom = x1 - 1, y1 - 1
    px, py = part.pivot or ((x0 + x1) // 2, y0)
    if (y1 - y0) >= (x1 - x0):
        far = y0 if abs(py - y0) > abs(py - bottom) else bottom
        return ((x0 + x1) // 2, int(far))
    far = x0 if abs(px - x0) > abs(px - right) else right
    return (int(far), (y0 + y1) // 2)


def _point(part, where):
    x0, y0, x1, y1 = part.box
    if where == "free_end":
        return _free_end(part)
    if where == "top":
        return ((x0 + x1) // 2, y0)
    if where == "bottom":
        return ((x0 + x1) // 2, y1 - 1)
    return ((x0 + x1) // 2, (y0 + y1) // 2)


def _on_pixels(part, where, pixels):
    """The same point, measured on what is DRAWN inside the part's box.

    A box is a rectangle around a limb and a limb is not a rectangle, so the
    box rule puts a hand in the corner of an arm's bounding box -- which on the
    corpus is a transparent pixel a third of the time, and an item hung there
    floats beside the character instead of being held by it. Given the picture,
    the extremity can be measured instead of assumed.

    Returns None when nothing is drawn in the box, so the caller keeps the box
    rule rather than inventing a point.
    """
    x0, y0, x1, y1 = part.box
    height, width = pixels.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    solid = pixels[y0:y1, x0:x1, 3] > 0
    if not solid.any():
        return None
    ys, xs = np.nonzero(solid)
    ys, xs = ys + y0, xs + x0
    if where == "free_end":
        # The drawn pixel furthest from the part's own hinge, which is what a
        # hand IS. Measured rather than taken from whichever box corner is
        # furthest away, because a bent arm's box corner is empty.
        px, py = part.pivot or ((x0 + x1) // 2, y0)
        far = np.argmax((xs - px) ** 2 + (ys - py) ** 2)
        return (int(xs[far]), int(ys[far]))
    if where == "top":
        row = ys.min()
    elif where == "bottom":
        row = ys.max()
    else:
        row = int(round(ys.mean()))
        row = int(ys[np.argmin(np.abs(ys - row))])
    on_row = xs[ys == row]
    return (int(round(on_row.mean())), int(row))


def sockets(rig, pixels=None):
    """Every attachment point this rig actually has, as {name: (part, point)}.

    A rig with no far arm has no off-hand, and says so by not offering one --
    which is a better answer than offering a socket that puts a shield in the
    middle of the torso.

    `pixels` is optional and makes every point better: with the picture in hand
    the point is measured on the part's own drawn pixels rather than on the
    rectangle around them. Without it the box rule still applies, so a caller
    that only has a rig still gets an answer.
    """
    found = {}
    for name, (role, where, _role, _z) in SOCKETS.items():
        part = rig.first_role(role)
        if part is None:
            continue
        point = None if pixels is None else _on_pixels(part, where, pixels)
        found[name] = (part.name, point or _point(part, where))
    return found


def grip_of(pixels, hint=None):
    """Where an item is held, in its own coordinates.

    The bottom centre of what is drawn, which is the hilt of a sword, the foot
    of a staff, the brim of a hat and the base of a lantern. It is wrong for a
    shield, which is why it can be overridden -- but it is right for enough
    items that an item usually needs no metadata at all.
    """
    if hint is not None:
        return (int(hint[0]), int(hint[1]))
    box = img.content_box(pixels)
    if box is None:
        return (pixels.shape[1] // 2, pixels.shape[0])
    x0, y0, x1, y1 = box
    return ((x0 + x1) // 2, y1)


def attach(host_pixels, host_rig, items):
    """Composite items onto the character and return (pixels, rig).

    `items` is a list of dicts: {"socket", "pixels", "name", "grip", "tags"}.
    The canvas grows when an item hangs past the edge, and every box, pivot and
    anchor in the rig moves with it -- a rig is coordinates in one picture, and
    the picture just changed.
    """
    available = sockets(host_rig, host_pixels)
    placements = []
    resized = []
    for item in items:
        socket = item["socket"]
        if socket not in available:
            raise ValueError(
                "this rig has no %r socket; it offers %s. A socket is derived "
                "from the parts the rig actually has, so a character with no "
                "far arm has no off-hand"
                % (socket, ", ".join(sorted(available)) or "none"))
        owner, point = available[socket]
        factor, why = fit(item["pixels"], host_rig, socket, item.get("scale"))
        pixels = item["pixels"]
        if factor != 1.0:
            # Nearest-neighbour in both directions, so no colour is invented
            # and PALETTE still holds by the same argument it always did: the
            # composed picture IS the source the rest of the pipeline reads.
            # Trimmed first, so the factor is measured against what is drawn
            # rather than against whatever margin the item's file carries.
            box = img.content_box(pixels)
            if box is not None:
                pixels = img.crop(pixels, box)
            pixels = img.scale_nearest(pixels, factor)
            if not img.alpha_mask(pixels).any():
                raise ValueError(
                    "%s scaled to %g for the %s and nothing was left of it. "
                    "The item is too small to fit this character; pass an "
                    "explicit scale or draw it larger"
                    % (item["name"], factor, owner))
        item = dict(item, pixels=pixels)
        resized.append((item, factor, why))
        grip = grip_of(pixels, item.get("grip"))
        # Where the item's top-left lands so its grip sits on the socket point.
        placements.append((item, owner, point,
                           (point[0] - grip[0], point[1] - grip[1])))
    items = [entry for entry, _factor, _why in resized]

    taken = {part.name for part in host_rig.parts}
    for item in items:
        if item["name"] in taken:
            raise ValueError(
                "this rig already has a part called %r, and two parts with one "
                "name is a rig that cannot be cut" % item["name"])
        taken.add(item["name"])

    height, width = host_pixels.shape[:2]
    left = top = 0
    right, bottom = width, height
    for item, _owner, _point, (ox, oy) in placements:
        ih, iw = item["pixels"].shape[:2]
        left, top = min(left, ox), min(top, oy)
        right, bottom = max(right, ox + iw), max(bottom, oy + ih)

    shift = (-left, -top)
    canvas = img.blank(bottom - top, right - left)
    img.paste(canvas, host_pixels, shift[0], shift[1])

    parts = [_moved(part, shift) for part in host_rig.parts]
    for item, owner, point, (ox, oy) in placements:
        img.paste(canvas, item["pixels"], ox + shift[0], oy + shift[1])
        ih, iw = item["pixels"].shape[:2]
        _role, _where, role, depth = SOCKETS[item["socket"]]
        owning = next(part for part in parts if part.name == owner)
        parts.append(rig_module.Part(
            item["name"], role,
            (ox + shift[0], oy + shift[1], ox + shift[0] + iw, oy + shift[1] + ih),
            owner, (point[0] + shift[0], point[1] + shift[1]),
            owning.z + depth, 1.0, item.get("tags", ())))

    anchor = host_rig.anchor
    built = rig_module.Rig(
        (canvas.shape[1], canvas.shape[0]), parts, host_rig.character_class,
        host_rig.facing,
        (anchor[0] + shift[0], anchor[1] + shift[1]) if anchor else None,
        host_rig.actor,
        list(host_rig.notes) + [
            "%s attached at the %s, riding %s%s"
            % (item["name"], item["socket"], owner,
               "" if factor == 1.0 else ", scaled %s" % why)
            for (item, owner, _point, _offset), (_entry, factor, why)
            in zip(placements, resized)])
    return canvas, built


def _moved(part, shift):
    x0, y0, x1, y1 = part.box
    pivot = part.pivot
    return rig_module.Part(
        part.name, part.role,
        (x0 + shift[0], y0 + shift[1], x1 + shift[0], y1 + shift[1]),
        part.parent,
        (pivot[0] + shift[0], pivot[1] + shift[1]) if pivot else None,
        part.z, part.confidence, part.tags)
