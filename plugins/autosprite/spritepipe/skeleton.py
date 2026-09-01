"""Forward kinematics: what each part's transform is once its parents have moved.

A pose is a small dictionary of per-part offsets -- an angle, a translation, a
squash. Nothing here touches a pixel. Keeping the kinematics separate from the
raster is what makes the motion library reviewable: a walk cycle is a table of
numbers you can read and argue with, not a rendering side effect.

Angles are degrees, clockwise positive, because screen y points down and a
clockwise-positive convention makes "swing the arm forward" a positive number
for a right-facing character. Everything rotates about its own pivot, and the
pivot is in reference-image coordinates.
"""

import math

import numpy as np

IDENTITY = np.eye(3)


class PartPose:
    """One part's departure from rest.

    Five of the six channels are an affine transform and are consumed by
    `local()` below. `cycle` is not: it is a whole-numbered step along the
    part's own colour ramp, applied to the pixels rather than to their
    positions, and the renderer handles it separately. It is here because it is
    keyed, eased, blended and composed exactly like the others -- a torch's
    flicker is authored in the same table as a torch's sway -- and because
    keeping it out would have meant a second parallel animation system for
    everything a subject does that is not a movement.
    """

    __slots__ = ("angle", "dx", "dy", "sx", "sy", "cycle")

    def __init__(self, angle=0.0, dx=0.0, dy=0.0, sx=1.0, sy=1.0, cycle=0.0):
        self.angle = float(angle)
        self.dx = float(dx)
        self.dy = float(dy)
        self.sx = float(sx)
        self.sy = float(sy)
        self.cycle = float(cycle)

    def blend(self, other, amount):
        """Linear blend towards `other`. Used to ease between keyframes."""
        keep = 1.0 - amount
        return PartPose(self.angle * keep + other.angle * amount,
                        self.dx * keep + other.dx * amount,
                        self.dy * keep + other.dy * amount,
                        self.sx * keep + other.sx * amount,
                        self.sy * keep + other.sy * amount,
                        self.cycle * keep + other.cycle * amount)

    def compose(self, other):
        """This pose with `other`'s DEPARTURE FROM REST applied on top.

        Rest is angle 0, no translation, scale 1, so composing is adding the
        rotations and translations and multiplying the squashes. That is
        already how a root track folds into the root part; it is now also how a
        trait-addressed layer folds into a role-addressed base, which is what
        lets "every stalk trails by a frame" be one line that leaves each
        part's own swing alone.
        """
        return PartPose(self.angle + other.angle,
                        self.dx + other.dx, self.dy + other.dy,
                        self.sx * other.sx, self.sy * other.sy,
                        self.cycle + other.cycle)

    def __repr__(self):
        return "PartPose(angle=%.1f, d=(%.1f, %.1f), s=(%.2f, %.2f), cycle=%+.1f)" % (
            self.angle, self.dx, self.dy, self.sx, self.sy, self.cycle)


class Pose:
    """A whole character at one instant: per-part poses plus a global offset."""

    def __init__(self, parts=None, dx=0.0, dy=0.0, flip=False):
        self.parts = dict(parts or {})
        self.dx = float(dx)      # whole-character translation, in pixels
        self.dy = float(dy)
        self.flip = bool(flip)   # mirror horizontally (west from east)

    def get(self, name):
        return self.parts.get(name) or PartPose()

    def set(self, name, pose):
        self.parts[name] = pose
        return self

    def blend(self, other, amount):
        names = set(self.parts) | set(other.parts)
        blended = {name: self.get(name).blend(other.get(name), amount) for name in names}
        keep = 1.0 - amount
        return Pose(blended, self.dx * keep + other.dx * amount,
                    self.dy * keep + other.dy * amount, other.flip if amount > 0.5 else self.flip)


def translate(dx, dy):
    matrix = np.eye(3)
    matrix[0, 2], matrix[1, 2] = dx, dy
    return matrix


def rotate(degrees):
    radians = math.radians(degrees)
    cos, sin = math.cos(radians), math.sin(radians)
    return np.array([[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]])


def scale(sx, sy):
    return np.array([[sx, 0.0, 0.0], [0.0, sy, 0.0], [0.0, 0.0, 1.0]])


def local(part_pose, pivot):
    """A part's own transform: rotate and squash about its pivot, then shift."""
    px, py = float(pivot[0]), float(pivot[1])
    return (translate(px + part_pose.dx, py + part_pose.dy)
            @ rotate(part_pose.angle)
            @ scale(part_pose.sx, part_pose.sy)
            @ translate(-px, -py))


# Roles that do not follow the character at all.
GROUNDED = ("shadow",)


def world_transforms(rig, pose):
    """{part name: 3x3 matrix} in reference-image coordinates.

    Parents are visited before children, so a child simply multiplies onto a
    transform that is already final. `rig.descend()` guarantees that order and
    `rig.validate` guarantees the tree it walks has no cycle to fall into.
    """
    root_shift = translate(pose.dx, pose.dy)
    transforms = {}
    for part in rig.descend():
        if part.role in GROUNDED:
            # A baked ground shadow is not part of the character; it is the
            # floor the character stands on, drawn into the same sprite. Riding
            # the root would lift it fifteen rows at the apex of a jump and bob
            # it two pixels per walk step -- the ground line pumping with the
            # animation. It gets the identity, and stays exactly where the
            # artist drew it.
            transforms[part.name] = np.eye(3)
            continue
        parent = transforms.get(part.parent, root_shift)
        transforms[part.name] = parent @ local(pose.get(part.name), part.pivot)
    return transforms


def apply_point(matrix, point):
    x, y, w = matrix @ np.array([float(point[0]), float(point[1]), 1.0])
    return (x / w, y / w)


def mirror(width):
    """Reflect about the vertical centreline of a `width`-wide image."""
    return np.array([[-1.0, 0.0, float(width) - 1.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])


def lowest_point(rig, pose, points):
    """The lowest row the character reaches in this pose, in reference space."""
    transforms = world_transforms(rig, pose)
    best = None
    for name, block in points.items():
        moved = transforms[name] @ block
        low = float((moved[1] / moved[2]).max())
        best = low if best is None else max(best, low)
    return best


def plant(rig, poses, points):
    """Put the character's lowest point on one row in every pose.

    A leg here is one rigid piece rotating about the hip, so swinging it forward
    by t degrees lifts its foot by L(1 - cos t) -- 10% of the leg at 26 degrees,
    which on a 64px character is six pixels of daylight under a walking figure.
    A real leg does not do this because it bends; ours cannot, so the correction
    goes on the root instead.

    What comes back is the walk's body bob, for free and correctly phased: with
    the feet held down, the body is at its lowest where the legs are splayed at
    contact and at its highest where they pass vertically underneath. That is
    the bob a walk cycle is supposed to have, and it now scales itself to the
    character instead of being a hand-authored pixel count.

    Only for animations where a foot is genuinely down throughout. A run has a
    flight phase and a jump is nothing but one.
    """
    lows = [lowest_point(rig, pose, points) for pose in poses]
    floor = max(lows)
    for pose, low in zip(poses, lows):
        pose.dy += floor - low
    return poses


def posed(rig, animation, points=None):
    """The poses to actually render: the animation's own, planted if it claims
    to be grounded. Everything that renders a clip goes through here, so the
    repair loop cannot end up measuring poses the pipeline did not draw."""
    poses = animation.poses(rig)
    if animation.planted and points:
        plant(rig, poses, points)
    return poses
