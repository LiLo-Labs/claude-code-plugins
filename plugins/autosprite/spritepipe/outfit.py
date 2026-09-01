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


def _free_end(part):
    """The end of a limb away from its own hinge.

    A limb's pivot is its shoulder or hip; the hand is at the other end. Which
    end that is depends on which way the limb is drawn, so it is measured rather
    than assumed: whichever of the box's two ends is further from the pivot,
    along whichever axis the limb is longer.
    """
    x0, y0, x1, y1 = part.box
    px, py = part.pivot or ((x0 + x1) // 2, y0)
    if (y1 - y0) >= (x1 - x0):
        far = y0 if abs(py - y0) > abs(py - y1) else y1
        return ((x0 + x1) // 2, int(far))
    far = x0 if abs(px - x0) > abs(px - x1) else x1
    return (int(far), (y0 + y1) // 2)


def _point(part, where):
    x0, y0, x1, y1 = part.box
    if where == "free_end":
        return _free_end(part)
    if where == "top":
        return ((x0 + x1) // 2, y0)
    if where == "bottom":
        return ((x0 + x1) // 2, y1)
    return ((x0 + x1) // 2, (y0 + y1) // 2)


def sockets(rig):
    """Every attachment point this rig actually has, as {name: (part, point)}.

    A rig with no far arm has no off-hand, and says so by not offering one --
    which is a better answer than offering a socket that puts a shield in the
    middle of the torso.
    """
    found = {}
    for name, (role, where, _role, _z) in SOCKETS.items():
        part = rig.first_role(role)
        if part is None:
            continue
        found[name] = (part.name, _point(part, where))
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
    available = sockets(host_rig)
    placements = []
    for item in items:
        socket = item["socket"]
        if socket not in available:
            raise ValueError(
                "this rig has no %r socket; it offers %s. A socket is derived "
                "from the parts the rig actually has, so a character with no "
                "far arm has no off-hand"
                % (socket, ", ".join(sorted(available)) or "none"))
        owner, point = available[socket]
        grip = grip_of(item["pixels"], item.get("grip"))
        # Where the item's top-left lands so its grip sits on the socket point.
        placements.append((item, owner, point,
                           (point[0] - grip[0], point[1] - grip[1])))

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
            "%s attached at the %s, riding %s"
            % (item["name"], item["socket"], owner)
            for item, owner, _point, _offset in placements])
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
