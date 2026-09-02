"""A limb is attached at one end. Move it as if it were not, and the body tears.

This is the answer to the one failure that three separate attempts at better
SEGMENTATION could not fix, each recorded in HANDOFF with its numbers: a
stretched arm box, a luminance seam carve on the artist's own shading crease,
and an Opus vision rig. All three produce anatomically better parts -- an arm
that starts at the shoulder instead of a 5x4 chip of mitten -- and all three
animate WORSE, and all three fail identically. Give a limb the part of the body
it genuinely attaches to, transform that rigidly, and the shoulder swings as far
as the hand does: on the corpus knight the vision rig's arm carries a strip of
chest with it and snaps the belt, a solid red line across the waist, in half the
frames of a walk.

The fault was never the boxes. It is that every pixel of a part gets the same
matrix. A real arm's shoulder does not move when the arm swings; its hand moves
the whole way; and between them the sleeve stretches. So:

    world(pixel) = parent's world transform @ local(pose * w(pixel), pivot)

`w` runs from 0 at the joint to 1 at the free end. At 0 the local transform is
the identity and the pixel stays exactly where the artist drew it -- which is
what keeps the belt intact. At 1 it is the transform the part would have had all
along, so a part whose pixels are all far from its pivot animates as it always
did.

Three properties are preserved, and they are the ones that matter:

* **REST is still byte-exact.** At rest every channel is already at rest, so
  damping them by any weight leaves the identity.
* **The palette is still a subset.** Every band below is a nearest-neighbour
  transform through the existing supersampled path. Nothing is ever averaged.
* **Nothing is invented.** Skinning only ever moves a pixel less than it would
  have moved. It cannot put a colour anywhere the rigid path would not have.

The weight is damped on the CHANNELS, not on the matrix (see `skeleton.damped`).
Averaging two matrices does not give a rigid transform: a half-weighted 40-degree
rotation would collapse the limb towards a line instead of turning it 20 degrees.

**Implementation: bands, not per-pixel.** A per-pixel transform means a forward
scatter, and a forward scatter leaves holes. Instead the part is cut into K bands
of equal weight, each transformed rigidly by its own damped pose through the
renderer's normal path, and composited from the joint outwards. K is chosen so
that neighbouring bands differ by less than a pixel of travel, and the bands
OVERLAP by one step so the seam between two of them is drawn twice rather than
not at all.
"""

import numpy as np

from . import image as img
from . import skeleton

# Roles whose pixels are all equally the part. A root carries the whole
# character, so weighting it would mean the character's feet translate and its
# head does not -- which is not a bend, it is the body coming apart. Only a part
# hanging off a parent has a joint to be pinned at, and `bands` refuses anything
# without one.
#
# `shadow` is on the floor and never moves at all; `prop` is a held object whose
# whole point is to travel with the hand that holds it.
RIGID_ROLES = frozenset(("shadow", "prop"))

# The most bands one part is ever cut into. Past this the gain is under a tenth
# of a pixel per band and the cost is linear.
MAX_BANDS = 12

# How much of the way to the free end a part is already at full strength. Below
# 1.0 the outer part of a limb moves rigidly together, which is what a forearm
# and a hand do -- the bend is at the shoulder, not spread evenly down the arm.
FULL_AT = 0.7

# Which field decides how much of its part's transform a pixel takes.
#
#   "pivot"       straight-line distance from the joint. Shipped.
#   "attachment"  geodesic distance from where the part touches its parent.
#
# `attachment` is the physically correct statement and it is NOT what ships,
# which is worth saying plainly. Measured across the twelve ground-truth clips
# at matched coverage:
#
#     rigid, no skinning                     30.85%
#     pivot, straight-line       (shipped)   30.46%   6 better, 2 worse
#     pivot, geodesic                        30.91%
#     attachment, geodesic                   30.91-31.36%   2 much better, 7 worse
#
# But the attachment column is not uniformly worse -- it splits cleanly by how
# the character is drawn, and that split is the lead worth following:
#
#     sumohulk walk (face-on)  27.7% -> 19.8%   eldiran walk (face-on)  29.1% -> 21.3%
#     horse walk    (profile)  27.2% -> 36.5%   forest run   (profile)  12.5% -> 16.9%
#
# Both big wins are FACE-ON characters and all three big losses are PROFILE ones.
# That is not noise and it has a reason: `fronted` rewrites a face-on clip's
# swings as TRANSLATIONS, and a translated limb slides off its socket, so pinning
# the socket is the whole fix. A profile limb already rotates about a pivot AT
# its joint, so the joint is pinned for free and attachment weighting only takes
# away motion that was right.
#
# So the next thing to try is not a better field. It is choosing between these
# two by whether the part's pose translates it or turns it.
WEIGHT_FIELD = "pivot"

# The largest share of a part that may be its joint, in `attachment` mode. Above
# this, what looks like an attachment is a limb LYING AGAINST the body rather
# than hinged to it: a horse's tail runs along its rump for its whole length, and
# seeding from that contact holds the tail still through an entire walk.
JOINT_SHARE = 0.35


def _geodesic(mask, seed):
    """Steps from `seed` to every pixel of `mask`, walking only inside `mask`.

    Geodesic, not straight-line, and that is the point: a hand is a long way
    from the shoulder ALONG THE ARM, and a chest pixel the arm's box happened to
    catch is a long way from the shoulder as the crow flies but no distance at
    all along the body. Straight-line distance cannot tell those apart; this
    can.

    A plain 8-connected wavefront. numpy has no distance transform without
    scipy, and at sprite scale a few dozen dilations cost nothing.
    """
    far = np.full(mask.shape, np.inf)
    front = seed & mask
    if not front.any():
        return far
    far[front] = 0.0
    step = 0.0
    while True:
        step += 1.0
        pad = np.zeros((front.shape[0] + 2, front.shape[1] + 2), dtype=bool)
        pad[1:-1, 1:-1] = front
        grown = np.zeros_like(front)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                grown |= pad[dy:dy + front.shape[0], dx:dx + front.shape[1]]
        front = grown & mask & ~np.isfinite(far)
        if not front.any():
            return far
        far[front] = step


def _touching(mask, other):
    """The pixels of `mask` that sit against `other` -- the attachment."""
    if other is None or not other.any():
        return np.zeros(mask.shape, dtype=bool)
    pad = np.zeros((other.shape[0] + 2, other.shape[1] + 2), dtype=bool)
    pad[1:-1, 1:-1] = other
    near = np.zeros_like(other)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            near |= pad[dy:dy + other.shape[0], dx:dx + other.shape[1]]
    return mask & near


def weights(pixels, origin, pivot, parent_mask=None, full_at=FULL_AT,
            joint_share=JOINT_SHARE, field=None):
    """Per-pixel weight for one part sprite: 0 where it is attached, 1 at its
    free end.

    **Attachment, not the pivot.** The first version of this measured distance
    from the pivot and it did not work, for a reason worth keeping: an arm box
    that runs from the shoulder overlaps the chest, and the chest pixels it
    catches are NOT near the pivot -- they run down the inner edge, five or six
    pixels below it. Measured on the corpus knight's vision rig they scored 0.8
    and 0.9 out of 1, so they took nearly the whole swing and went on snapping
    the belt exactly as they had before skinning existed.

    What actually distinguishes them is not where the pivot is, it is that they
    are pressed against the torso. A limb is pinned where it TOUCHES ITS PARENT
    and free where it does not, and that is a thing the cut already knows: the
    ownership map says which pixels are the parent's, and the part's own pixels
    lying against them are the joint.

    The distance from there is geodesic -- it walks inside the part -- so it
    travels down an arm to the hand rather than cutting across the chest. That
    is what separates a hand, far from the shoulder along the limb, from a chest
    pixel that is far from the shoulder in a straight line and touching the body
    all the way.

    Falls back to distance from the pivot when a part touches nothing: a
    detached orb, a floating shadow, a part whose parent lost every pixel it had.
    """
    mask = img.alpha_mask(pixels)
    out = np.zeros(mask.shape, dtype=np.float64)
    if not mask.any():
        return out

    if (field or WEIGHT_FIELD) == "pivot":
        rows, columns = np.nonzero(mask)
        dx = (columns + origin[0]) - float(pivot[0])
        dy = (rows + origin[1]) - float(pivot[1])
        distance = np.hypot(dx, dy)
        reach = float(distance.max())
        if reach <= 0.0:
            out[mask] = 1.0
            return out
        out[mask] = np.clip(distance / max(1e-6, reach * float(full_at)), 0.0, 1.0)
        return out

    seed = None
    if parent_mask is not None and joint_share > 0.0:
        window = parent_mask[origin[1]:origin[1] + mask.shape[0],
                             origin[0]:origin[0] + mask.shape[1]]
        if window.shape == mask.shape:
            found = _touching(mask, window)
            # A JOINT IS SMALL. A horse's tail lies along its rump for its whole
            # length and an arm rests against a hip; contact is not attachment,
            # and a part that is mostly contact has no free end to find this way.
            # Measured on the corpus: the knight's overlapping arm is a quarter
            # contact and the horse's tail is more than half, and pinning the
            # tail by contact holds it still through an entire walk.
            if found.any() and found.sum() <= joint_share * mask.sum():
                seed = found
    if seed is None:
        rows, columns = np.nonzero(mask)
        dx = (columns + origin[0]) - float(pivot[0])
        dy = (rows + origin[1]) - float(pivot[1])
        nearest = np.hypot(dx, dy)
        seed = np.zeros(mask.shape, dtype=bool)
        seed[rows[nearest <= nearest.min() + 1.0],
             columns[nearest <= nearest.min() + 1.0]] = True

    distance = _geodesic(mask, seed)
    finite = np.isfinite(distance) & mask
    if not finite.any():
        out[mask] = 1.0
        return out
    reach = float(distance[finite].max())
    if reach <= 0.0:
        # Every pixel of this part is against its parent. There is no free end,
        # so it moves rigidly rather than not at all -- a part that cannot move
        # is worse than one that moves as it always did.
        out[mask] = 1.0
        return out
    span = max(1e-6, reach * float(full_at))
    out[finite] = np.clip(distance[finite] / span, 0.0, 1.0)
    # A pocket the wavefront could not reach is not attached to the joint at all.
    out[mask & ~finite] = 1.0
    return out


def steps(part_pose, pivot, pixels, origin, count):
    """How far apart the extremes of this part travel under `part_pose`.

    Used to pick the number of bands: cutting a part into more bands than there
    are pixels of differential travel across it puts several bands on the same
    pixel, which costs a transform and changes nothing.
    """
    mask = img.alpha_mask(pixels)
    if not mask.any():
        return 1
    rows, columns = np.nonzero(mask)
    points = np.stack([columns + origin[0], rows + origin[1],
                       np.ones(rows.shape)], axis=0)
    matrix = skeleton.local(part_pose, pivot)
    moved = (matrix @ points)[:2] - points[:2]
    travel = float(np.hypot(*(moved.max(axis=1) - moved.min(axis=1))))
    return int(np.clip(round(travel) + 1, 1, count))


def bands(part, part_pose, pixels, origin, weight, max_bands=MAX_BANDS):
    """[(mask, damped pose)] from the joint outwards, or None to stay rigid.

    Returns None -- meaning "render this part exactly as before" -- for a part
    with no parent, a role in `RIGID_ROLES`, a pose that does not move it, or a
    pose whose extremes travel less than a pixel apart. That last case is most
    parts in most frames, so skinning costs almost nothing on a still limb.
    """
    if part.parent is None or part.role in RIGID_ROLES or part.pivot is None:
        return None
    count = steps(part_pose, part.pivot, pixels, origin, max_bands)
    if count <= 1:
        return None
    mask = img.alpha_mask(pixels)
    edges = np.linspace(0.0, 1.0, count + 1)
    # One step of overlap on each side. Two neighbouring bands differ by under a
    # pixel of travel by construction, so drawing their shared row twice is a
    # sub-pixel disagreement; NOT drawing it is a hole straight through the limb.
    slack = (edges[1] - edges[0]) * 0.5
    out = []
    for index in range(count):
        low, high = edges[index] - slack, edges[index + 1] + slack
        band = mask & (weight >= low) & (weight <= high)
        if not band.any():
            continue
        # The GREATEST weight in the band, not its midpoint and not its mean.
        # Both of those shorten a limb's reach: the outermost band of a thin leg
        # holds pixels from 0.8 to 1.0, so its mean is 0.95 and the foot gets 95%
        # of the swing it used to. That is a silent global change to the
        # amplitude of every clip -- skinning is meant to pin the JOINT, not to
        # damp the whole animation -- and on a 14px leg it is the difference
        # between a foot that clears the floor by a pixel and one that does not.
        #
        # The maximum pins the joint just as well, because the innermost band's
        # greatest weight is still nearly zero, and it guarantees the free end
        # travels exactly as far as it did before skinning existed.
        out.append((band, skeleton.damped(part_pose, float(weight[band].max()))))
    return out or None
