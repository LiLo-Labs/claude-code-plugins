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
    """One part's departure from rest."""

    __slots__ = ("angle", "dx", "dy", "sx", "sy")

    def __init__(self, angle=0.0, dx=0.0, dy=0.0, sx=1.0, sy=1.0):
        self.angle = float(angle)
        self.dx = float(dx)
        self.dy = float(dy)
        self.sx = float(sx)
        self.sy = float(sy)

    def blend(self, other, amount):
        """Linear blend towards `other`. Used to ease between keyframes."""
        keep = 1.0 - amount
        return PartPose(self.angle * keep + other.angle * amount,
                        self.dx * keep + other.dx * amount,
                        self.dy * keep + other.dy * amount,
                        self.sx * keep + other.sx * amount,
                        self.sy * keep + other.sy * amount)

    def __repr__(self):
        return "PartPose(angle=%.1f, d=(%.1f, %.1f), s=(%.2f, %.2f))" % (
            self.angle, self.dx, self.dy, self.sx, self.sy)


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


def world_transforms(rig, pose):
    """{part name: 3x3 matrix} in reference-image coordinates.

    Parents are visited before children, so a child simply multiplies onto a
    transform that is already final. `rig.descend()` guarantees that order and
    `rig.validate` guarantees the tree it walks has no cycle to fall into.
    """
    root_shift = translate(pose.dx, pose.dy)
    transforms = {}
    for part in rig.descend():
        parent = transforms.get(part.parent, root_shift)
        transforms[part.name] = parent @ local(pose.get(part.name), part.pivot)
    return transforms


def apply_point(matrix, point):
    x, y, w = matrix @ np.array([float(point[0]), float(point[1]), 1.0])
    return (x / w, y / w)


def mirror(width):
    """Reflect about the vertical centreline of a `width`-wide image."""
    return np.array([[-1.0, 0.0, float(width) - 1.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
