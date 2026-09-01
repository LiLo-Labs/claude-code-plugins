"""Who decides which pixels are the arm.

Two backends answer the same question and produce the same artefact:

  TemplateBackend  reads the silhouette. No model, no network, no credentials.
  HeadlessBackend  asks `claude -p` to look at the art.

The template one is not a mock. It is the honest floor of what this pipeline
does with nothing attached: it finds the neck at the narrowest row and the hips
where the silhouette first splits in two, which on a standing character is
right far more often than it is wrong. Every test in this plugin runs against
it, so the whole pipeline is provable without a model in the loop -- and a user
with no `claude` on PATH still gets a working sprite sheet.

The headless one is what makes a rig correct on art the silhouette lies about:
a character holding a staff across their body, a cape that reads as a third leg,
a mount, a robot whose "head" is a sensor pod at the shoulder. Every rig records
which backend built it in `actor`, so nothing downstream can mistake a template
guess for something a model actually looked at.
"""

import json
import os
import subprocess

import numpy as np

from . import image as img
from . import rig as rig_module

# Draw order by role. Far limbs behind the body, near limbs in front of it.
Z_BY_ROLE = {
    "wing_far": -2, "arm_far": -1, "leg_far": 0, "body": 1, "torso": 1,
    "leg_near": 2, "tail": 2, "head": 3, "accessory": 4, "arm_near": 5,
    "prop": 6, "wing_near": 6,
}


FACE_ON = ("front", "back")

# Drawn face-on there is no far side, so a "far" limb is not behind anything and
# must not be drawn behind the torso. It keeps its role, because every animation
# and every exporter dispatches on role and the pair still has to swing in
# counter-phase; only the depth and the name change.
FACE_ON_Z = {"arm_far": 4, "leg_far": 2, "wing_far": 6}
FACE_ON_NAMES = {"arm_far": "arm_left", "arm_near": "arm_right",
                 "leg_far": "leg_left", "leg_near": "leg_right",
                 "wing_far": "wing_left", "wing_near": "wing_right"}


def face_on(parts, notes):
    """Bring a sagittal rig round to face the camera.

    A profile rig is built on a depth axis the picture does not have: `arm_far`
    is drawn BEHIND the torso, which is right for a character in profile and
    wrong for one looking at you, whose arms are both in front and both fully
    drawn. Renaming them left and right is not cosmetic either -- a user reading
    `arm_far` on a front-facing sprite has to guess which arm the rigger meant.
    """
    renamed = False
    for part in parts:
        if part.role in FACE_ON_Z:
            part.z = FACE_ON_Z[part.role]
        if part.role in FACE_ON_NAMES and part.name == part.role:
            part.name = FACE_ON_NAMES[part.role]
            renamed = True
    if renamed:
        notes.append("drawn face-on: the paired limbs are the character's left "
                     "and right, both in front of the torso, and the animations "
                     "trade their swing for a lift")


# --------------------------------------------------------------------------
# silhouette measurements the template rigger reasons from
# --------------------------------------------------------------------------

def row_widths(mask):
    """Opaque pixel count per row."""
    return mask.sum(axis=1)


def runs(row):
    """The opaque spans in one row as half-open (x0, x1) pairs.

    Every measurement below is built on this. A silhouette row is not a width --
    it is a set of spans, and the gaps between them are where the arms stop
    being the torso. Collapsing a row to its width throws away exactly the
    signal that tells a limb from a body.
    """
    padded = np.concatenate(([False], row, [False])).astype(np.int8)
    edges = np.diff(padded)
    starts = np.flatnonzero(edges == 1)
    stops = np.flatnonzero(edges == -1)
    return list(zip(starts.tolist(), stops.tolist()))


def row_runs(row):
    """How many separate opaque spans a row has."""
    return len(runs(row))


def row_extent(mask, y0, y1):
    """(x0, x1) horizontal extent of the mask over a band of rows, half-open."""
    band = mask[y0:y1]
    if not band.any():
        return None
    cols = np.flatnonzero(band.any(axis=0))
    return (int(cols[0]), int(cols[-1]) + 1)


def _bbox(spans):
    """(x0, y0, x1, y1) around a list of (y, x0, x1) spans, or None."""
    if not spans:
        return None
    ys = [span[0] for span in spans]
    return (min(span[1] for span in spans), min(ys),
            max(span[2] for span in spans), max(ys) + 1)


def find_neck(mask, low=0.10, high=0.55):
    """The narrowest row in the upper body. That is the neck.

    Deliberately independent of where the shoulders are, because the obvious
    landmark -- the row where the silhouette widens into the shoulders -- is
    wrong for a whole category of sprite. A chibi's head is the WIDEST part of
    the character, so the body never widens below it, and a shoulder-first
    search puts the "shoulders" two rows down from the crown and the neck above
    them. The rig then has a two-row head on a seventeen-row character and the
    face animates as part of the torso.

    A neck is narrow whether the head above it is bigger or smaller than the
    body below it, so search for narrowness and nothing else. The LAST row
    achieving the minimum is taken, so a head of uniform width resolves to its
    bottom row rather than its top one.
    """
    height = mask.shape[0]
    y0 = max(1, int(height * low))
    y1 = max(y0 + 1, min(int(height * high), height - 1))
    widths = row_widths(mask)[y0:y1].astype(float)
    if widths.size == 0 or not widths.any():
        return max(0, int(height * 0.3))
    widths[widths == 0] = np.inf
    last = int(np.flatnonzero(widths <= float(widths.min()))[-1])
    return int(y0 + last)


def find_shoulder(mask, neck=None):
    """The first row below the neck that is at least as wide as the neck.

    Derived from the neck rather than the other way round. Its only job is to
    say where the arms start, and the arms start where the body stops being a
    neck -- which is true whether the shoulders are broader than the head or
    narrower.
    """
    height = mask.shape[0]
    if neck is None:
        neck = find_neck(mask)
    widths = row_widths(mask)
    limit = min(height, max(neck + 2, int(height * 0.75)))
    for y in range(neck + 1, limit):
        if widths[y] >= widths[neck]:
            return int(y)
    return int(min(neck + 1, height - 1))


def body_mask(mask, keep=0.15):
    """The character without anything detached from it.

    Real sprites routinely carry a baked drop shadow: a separate blob a row or
    two below the feet. It is part of the art and the rig must still own it, but
    it is not part of the BODY, and letting it stand in for the feet breaks
    every measurement taken from the bottom up -- the leg split most of all,
    which then finds a single shadow-shaped run, concludes the legs never part,
    and demotes a person to a one-piece prop.

    So measurements use the largest connected component and boxes use the whole
    mask. Anything holding at least `keep` of the art is kept as body, so a
    character genuinely drawn in two pieces is not thrown away.
    """
    height, width = mask.shape
    seen = np.zeros_like(mask)
    best, best_size, total = None, 0, int(mask.sum())
    kept = np.zeros_like(mask)
    for sy in range(height):
        for sx in range(width):
            if mask[sy, sx] and not seen[sy, sx]:
                stack, blob = [(sy, sx)], []
                seen[sy, sx] = True
                while stack:
                    y, x = stack.pop()
                    blob.append((y, x))
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = y + dy, x + dx
                            if (0 <= ny < height and 0 <= nx < width
                                    and mask[ny, nx] and not seen[ny, nx]):
                                seen[ny, nx] = True
                                stack.append((ny, nx))
                if len(blob) > best_size:
                    best, best_size = blob, len(blob)
                if total and len(blob) >= total * keep:
                    for y, x in blob:
                        kept[y, x] = True
    if not kept.any() and best:
        for y, x in best:
            kept[y, x] = True
    return kept if kept.any() else mask


def find_split(mask, floor=0.35, slack=2):
    """The row where the legs part, found by scanning up from the feet.

    Scanning down from the middle finds the first row with two spans, and on any
    character whose arms hang clear of the body that row is the armpit, not the
    crotch -- the rig then puts the hips at chest height and the character walks
    on its elbows. The legs are different from the arms in one reliable way:
    once they part they STAY parted, down to the floor.

    Down to the floor, but not always THROUGH it. A horse's hooves, a pair of
    boots on a ground line, a baked contact shadow -- any of them merges the last
    row or two back into one span, and requiring the very bottom row to be
    parted threw the whole signal away: a winged pony with six clearly parted
    rows of legs was demoted to a one-piece prop because its hooves met on the
    final row. `slack` is how many merged rows at the bottom to look past.

    None when the character genuinely never parts -- a robe, a slime, a prop. The
    caller falls back to a proportion, and records that it did.
    """
    height = mask.shape[0]
    mask = body_mask(mask)
    rows = [y for y in range(height) if mask[y].any()]
    if not rows:
        return None
    bottom = rows[-1]

    parted = None
    for y in range(bottom, max(-1, bottom - int(slack) - 1), -1):
        if y >= 0 and mask[y].any() and row_runs(mask[y]) >= 2:
            parted = y
            break
    if parted is None:
        return None

    limit = max(1, int(height * floor))
    y = parted
    while y - 1 >= limit and row_runs(mask[y - 1]) >= 2:
        y -= 1
    return int(y)


def core_and_limbs(mask, y0, y1, center_x):
    """Split a band into (core_box, left_box, right_box) by runs around a centre.

    In the arm band a row is typically three spans -- far arm, torso, near arm --
    and the torso is the span the body's centreline passes through. The spans
    either side of it are the arms. A row with only one span has its arms
    touching the body there and contributes nothing, which is correct: those
    pixels belong to the torso and must not swing.
    """
    core, left, right = [], [], []
    for y in range(y0, y1):
        spans = runs(mask[y])
        if not spans:
            continue
        holder = None
        for span in spans:
            if span[0] <= center_x < span[1]:
                holder = span
                break
        if holder is None:
            holder = max(spans, key=lambda span: span[1] - span[0])
        for span in spans:
            if span == holder:
                core.append((y,) + span)
            elif span[1] <= holder[0]:
                left.append((y,) + span)
            else:
                right.append((y,) + span)
    return _bbox(core), _bbox(left), _bbox(right)


def _complete_pair(left, right, reference_box, width=None):
    """Given one of a symmetric pair, invent its partner by mirroring.

    A silhouette routinely resolves only one of a pair: on a profile the near
    arm hides the far one, and a cape or a long coat can swallow one leg
    entirely. Emitting the one that was found and stopping there produces a rig
    that `validate` rejects outright -- paired limbs animate in counter-phase
    and need both halves -- so a real character would fail to build at all
    rather than animate imperfectly.

    Mirroring about the parent's centreline is the right guess and a cheap one:
    on a symmetric character it is where the partner actually is, and where it
    is not, it is still hidden behind the body and never seen.

    The mirror is SHIFTED back inside the image rather than truncated when it
    lands outside. On a character trimmed tight to an outstretched arm, the
    reflection falls past the opposite edge, and a truncated box is an empty or
    one-pixel limb -- which validates, animates, and looks like the character
    lost an arm anyway.

    Returns (left, right, mirrored) where `mirrored` says a partner was invented.
    """
    if (left is None) == (right is None):
        return left, right, False
    centre = (reference_box[0] + reference_box[2]) / 2.0
    found = left if right is None else right
    x0, y0, x1, y1 = found
    span = x1 - x0
    mirror_x0 = int(round(2 * centre - x1))
    mirror_x1 = mirror_x0 + span
    if width is not None:
        if mirror_x0 < 0:
            mirror_x0, mirror_x1 = 0, min(int(width), span)
        elif mirror_x1 > width:
            mirror_x0, mirror_x1 = max(0, int(width) - span), int(width)
    partner = (mirror_x0, y0, mirror_x1, y1)
    if partner[2] <= partner[0]:
        partner = found
    if right is None:
        return left, partner, True
    return partner, right, True


def leg_columns(mask, belly, height, floor_share=0.6, gap=1):
    """Where a side-on animal's legs are, read as COLUMNS rather than rows.

    `pair_boxes` reads a band row by row and halves any row that has not parted
    yet. That is right under a biped's hips, where an unparted row really is two
    legs touching. It is wrong under a quadruped, where the unparted row is the
    last row of a single hoof: on the pegasus, one such row at the very bottom
    stretched the far leg's box from 5 pixels wide to 15, so a box holding BOTH
    leg pairs rotated about its middle and sheared a tenth of the animal off.

    A leg, seen side-on, is a run of columns that reaches down towards the
    floor. Everything shallower is belly fringe, a contact shadow or the tip of
    a dragging tail, and must not widen a leg's box. So measure each column's
    reach below the belly line, keep the columns that reach at least
    `floor_share` of the deepest, and return their runs, bridging gaps of up to
    `gap` columns so a two-pixel notch inside one hoof does not split it.
    """
    height = int(height)
    belly = int(belly)
    if belly >= height:
        return []
    below = mask[belly:height]
    width = mask.shape[1]
    reach = [0] * width
    for x in range(width):
        column = np.nonzero(below[:, x])[0]
        reach[x] = int(column[-1]) + 1 if len(column) else 0
    deepest = max(reach) if reach else 0
    if deepest <= 0:
        return []
    floor = max(2, int(deepest * float(floor_share)))
    found, start, missing = [], None, 0
    for x in range(width + 1):
        deep = x < width and reach[x] >= floor
        if deep:
            if start is None:
                start = x
            missing = 0
        elif start is not None:
            missing += 1
            if missing > gap or x >= width:
                found.append((start, x - missing + 1))
                start, missing = None, 0
    return found


def split_leg_groups(columns):
    """Split leg column runs into the trailing group and the leading group.

    A quadruped's four legs read as two clusters far apart with, at most, a
    small gap inside each cluster where one leg of a pair shows past the other.
    The largest gap between runs is therefore the animal's own length, and it is
    the only place the split can honestly go.
    """
    if len(columns) < 2:
        return None
    gaps = [(columns[i + 1][0] - columns[i][1], i) for i in range(len(columns) - 1)]
    _, at = max(gaps)
    return columns[:at + 1], columns[at + 1:]


def pair_boxes(mask, y0, y1):
    """Split a band into a left box and a right box, one limb each.

    Below the hips both spans are legs, so there is no core to exclude. A row
    that has not parted yet is halved down the middle; a row with three or more
    spans (a tail between the legs, a trailing cape) gives its middle spans to
    whichever side they sit closer to.
    """
    left, right = [], []
    for y in range(y0, y1):
        spans = runs(mask[y])
        if not spans:
            continue
        if len(spans) == 1:
            x0, x1 = spans[0]
            middle = (x0 + x1) // 2
            left.append((y, x0, max(x0 + 1, middle)))
            right.append((y, min(x1 - 1, middle), x1))
            continue
        left.append((y,) + spans[0])
        right.append((y,) + spans[-1])
        for span in spans[1:-1]:
            near_left = abs(span[0] - spans[0][1]) <= abs(spans[-1][0] - span[1])
            (left if near_left else right).append((y,) + span)
    return _bbox(left), _bbox(right)


# --------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------

class Backend:
    actor = "deterministic:backend@0.1.0"

    def rig(self, reference, character_class="auto", facing="right", intent=""):
        raise NotImplementedError


class TemplateBackend(Backend):
    """Rig from the silhouette alone. Deterministic, offline, always available."""

    actor = "deterministic:template@0.1.0"

    def rig(self, reference, character_class="auto", facing="right", intent=""):
        mask = img.alpha_mask(reference.pixels)
        height, width = mask.shape
        kind = character_class
        if kind == "auto":
            kind = self.classify(mask)
        if kind == "creature" and facing in FACE_ON:
            # `_creature` builds a SIDE-ON animal: head at the leading end, tail
            # trailing, legs under the belly. None of that survives the camera
            # moving round to the front, and `classify` cannot know -- it reads
            # the silhouette, and a stocky character drawn face-on is wider than
            # it is tall exactly like a horse. The corpus's 16px roguelike hero
            # was rigged with its left arm as a head and its right arm as a tail.
            kind = "humanoid"
            notes_from_class = ("wider than tall, which usually means a side-on "
                                "animal, but it is drawn face-on -- rigged as an "
                                "upright character instead")
        else:
            notes_from_class = None

        builder = {"humanoid": self._humanoid, "creature": self._creature,
                   "prop": self._prop}.get(kind, self._prop)
        parts, notes = builder(mask, width, height, facing)
        if notes_from_class:
            notes.insert(0, notes_from_class)

        for part in parts:
            part.z = Z_BY_ROLE.get(part.role, 1)
        if facing in FACE_ON:
            face_on(parts, notes)
        built = rig_module.Rig((width, height), parts, kind, facing,
                               anchor=(width // 2, height), actor=self.actor,
                               notes=notes)
        return built

    def classify(self, mask):
        """humanoid / creature / prop, from legs first and proportion second.

        Aspect ratio alone gets this wrong on exactly the shapes it matters for:
        a cut gem is wider than it is tall and is not a quadruped, and a robed
        figure never parts and is not a barrel. The reliable signal is whether
        the silhouette has LEGS -- a bottom that parts and stays parted -- and
        proportion only then decides whether they are a person's or an animal's.

        With no legs, the question is whether the shape has a NECK: a row
        markedly narrower than the mass below it. That works for a chibi, whose
        head is the widest part of the character and which therefore has no
        shoulder step at all. Testing for widening shoulders instead demotes
        every big-headed sprite -- a large fraction of all pixel art -- to a
        one-piece prop.
        """
        height, width = mask.shape
        tall = height >= width * 1.15
        if find_split(mask) is not None:
            return "humanoid" if tall else "creature"
        if tall and self._has_neck(mask):
            return "humanoid"
        return "prop"

    def _has_neck(self, mask, ratio=0.8):
        """Is there a row narrow enough, with enough mass below it, to be a neck?"""
        neck = find_neck(mask)
        widths = row_widths(mask)
        below = widths[neck + 1:]
        if below.size == 0 or not below.any():
            return False
        return float(widths[neck]) <= float(below.max()) * ratio

    def _has_shoulders(self, mask, ratio=1.25):
        shoulder = find_shoulder(mask)
        widths = row_widths(mask).astype(float)
        above, below = widths[:shoulder], widths[shoulder:]
        if above.size == 0 or below.size == 0 or not above.any():
            return False
        return float(below.max()) >= float(above.max()) * ratio

    def _humanoid(self, mask, width, height, facing):
        notes = []
        neck = find_neck(mask)
        shoulder = find_shoulder(mask, neck)
        split = find_split(mask)
        if split is None:
            split = int(height * 0.62)
            notes.append("the silhouette never parts, so the hip line is a "
                         "proportion (62% of height) rather than a measurement")
        hip = max(neck + 2, min(int(split), height - 1))
        arm_top = max(neck + 1, min(shoulder, hip - 1))

        full = row_extent(mask, 0, height) or (0, width)
        center_x = (full[0] + full[1]) // 2

        head_extent = row_extent(mask, 0, neck + 1) or full
        core, left_arm, right_arm = core_and_limbs(mask, arm_top, hip, center_x)
        torso_box = core or (full[0], neck + 1, full[1], hip)
        # The torso owns everything from the neck down to the hips, whatever the
        # arm band measured: `core` starts at the shoulders and would otherwise
        # leave the collarbone rows unowned.
        torso_box = (torso_box[0], neck + 1, torso_box[2], hip)
        left_leg, right_leg = pair_boxes(mask, hip, height)

        if left_arm is None and right_arm is None:
            # Arms never separate from the body. Give each side the outer third
            # of the torso so the walk cycle still has something to swing, and
            # say that is what happened.
            third = max(1, (torso_box[2] - torso_box[0]) // 3)
            left_arm = (torso_box[0], arm_top, torso_box[0] + third, hip)
            right_arm = (torso_box[2] - third, arm_top, torso_box[2], hip)
            notes.append("the arms never separate from the body in the "
                         "silhouette, so each arm is the outer third of the "
                         "torso; a vision rig will do better here")
        else:
            left_arm, right_arm, mirrored = _complete_pair(
                left_arm, right_arm, torso_box, width)
            if mirrored:
                notes.append("only one arm separates from the body in the "
                             "silhouette; the other is its mirror about the "
                             "torso's centreline")
        left_leg, right_leg, mirrored_legs = _complete_pair(
            left_leg, right_leg, torso_box, width)
        if mirrored_legs:
            notes.append("only one leg separates from the body in the "
                         "silhouette; the other is its mirror about the "
                         "torso's centreline")

        far_arm, near_arm = (left_arm, right_arm) if facing == "right" else (right_arm, left_arm)
        far_leg, near_leg = (left_leg, right_leg) if facing == "right" else (right_leg, left_leg)

        parts = [
            rig_module.Part("torso", "torso", torso_box, None,
                            ((torso_box[0] + torso_box[2]) // 2, hip)),
            rig_module.Part("head", "head",
                            (head_extent[0], 0, head_extent[1], neck + 1), "torso",
                            ((head_extent[0] + head_extent[1]) // 2, neck)),
        ]
        for name, role, box in (("arm_far", "arm_far", far_arm),
                                ("arm_near", "arm_near", near_arm),
                                ("leg_far", "leg_far", far_leg),
                                ("leg_near", "leg_near", near_leg)):
            if box is None or box[2] <= box[0] or box[3] <= box[1]:
                continue
            pivot_y = box[1] if role.startswith("arm") else hip
            parts.append(rig_module.Part(name, role, box, "torso",
                                         ((box[0] + box[2]) // 2, pivot_y)))

        notes.append("shoulders at row %d, neck at row %d, hips at row %d"
                     % (shoulder, neck, hip))
        return parts, notes

    def _creature(self, mask, width, height, facing):
        """A side-on animal: body, head at the leading end, tail trailing, and a
        leg under each half of the belly."""
        belly = find_split(mask, floor=0.45)
        if belly is None:
            belly = int(height * 0.62)
        belly = max(2, min(int(belly), height - 1))
        notes = ["side-on creature: head at the %s end, belly line at row %d"
                 % (facing, belly)]

        head_span = max(1, int(width * 0.30))
        tail_span = max(1, int(width * 0.16))
        head_bottom = max(1, int(belly * 0.95))
        if facing == "right":
            head_box = (width - head_span, 0, width, head_bottom)
            tail_box = (0, int(height * 0.10), tail_span, max(int(height * 0.10) + 1, int(belly * 0.8)))
        else:
            head_box = (0, 0, head_span, head_bottom)
            tail_box = (width - tail_span, int(height * 0.10),
                        width, max(int(height * 0.10) + 1, int(belly * 0.8)))


        parts = [rig_module.Part("body", "body", (0, 0, width, belly), None,
                                 (width // 2, belly)),
                 rig_module.Part("head", "head", head_box, "body",
                                 ((head_box[0] + head_box[2]) // 2, head_box[3])),
                 rig_module.Part("tail", "tail", tail_box, "body",
                                 (tail_box[2] if facing == "right" else tail_box[0],
                                  (tail_box[1] + tail_box[3]) // 2))]
        groups = split_leg_groups(leg_columns(mask, belly, height))
        if groups is None:
            # Only one cluster of legs reaches the floor: this reads as a biped
            # or a creature standing square, so fall back to the row-wise split.
            left_leg, right_leg = pair_boxes(mask, belly, height)
            lead, trail = ((right_leg, left_leg) if facing == "right"
                           else (left_leg, right_leg))
            legs = [("leg_near", "leg_near", lead), ("leg_far", "leg_far", trail)]
            notes.append("the legs never separate into fore and hind, so they "
                         "are split down the middle as a biped's are")
        else:
            trailing, leading = groups
            fore_columns, hind_columns = ((leading, trailing) if facing == "right"
                                          else (trailing, leading))
            legs = (self._leg_pair(mask, fore_columns, belly, height, "foreleg", "arm")
                    + self._leg_pair(mask, hind_columns, belly, height, "hindleg", "leg"))
            notes.append("four legs: the columns reaching the floor form two "
                         "clusters, forelegs at x%s and hindlegs at x%s"
                         % (fore_columns[0][0], hind_columns[0][0]))
        for name, role, box in legs:
            if box is None or box[2] <= box[0] or box[3] <= box[1]:
                continue
            parts.append(rig_module.Part(name, role, box, "body",
                                         ((box[0] + box[2]) // 2, belly)))
        return [p for p in parts if p.width > 0 and p.height > 0], notes

    @staticmethod
    def _leg_pair(mask, columns, belly, height, name, role_stem):
        """One end of a quadruped: a near leg, and its partner behind it.

        Where the cluster resolves into two column runs, both legs are drawn and
        each gets its own; where it resolves into one, the near leg hides the far
        one, and the far part is emitted over the same box. `cutout` gives every
        shared pixel to the near partner, so the far leg is then empty -- which
        is what a profile view actually shows, and keeps the pair complete for
        the animations that swing them in counter-phase.
        """
        def box_of(x0, x1):
            band = mask[belly:height, x0:x1]
            rows = np.nonzero(band.any(axis=1))[0]
            if not len(rows):
                return None
            return (x0, belly, x1, belly + int(rows[-1]) + 1)

        if len(columns) >= 2:
            near = box_of(columns[-1][0], columns[-1][1])
            far = box_of(columns[0][0], columns[0][1])
        else:
            near = box_of(columns[0][0], columns[0][1])
            far = near
        return [("%s_near" % name, "%s_near" % role_stem, near),
                ("%s_far" % name, "%s_far" % role_stem, far)]

    def _prop(self, mask, width, height, facing):
        return ([rig_module.Part("body", "body", (0, 0, width, height), None,
                                 (width // 2, height))],
                ["one piece: props animate as a whole, never articulated"])


DESCRIBE_PROMPT = """You are looking at one game character sprite, shown at its \
native resolution and then again at 6x so you can see individual pixels. The \
image is %(width)dx%(height)d pixels, origin top-left, and the character fills \
it edge to edge -- it has already been trimmed.

Your job is to say which rectangle of this image is which part of the character, \
so that a skeletal animator can cut those rectangles out and swing them.

%(intent)s

Answer with JSON only. No prose, no markdown fence.

{
  "class": "humanoid" | "creature" | "prop",
  "facing": "right" | "left" | "front" | "back",
  "parts": [
    {"name": "torso", "role": "torso", "box": [x0, y0, x1, y1],
     "parent": null, "pivot": [x, y], "confidence": 0.0-1.0}
  ]
}

Rules that decide whether this rig works or produces a broken character:

- **Boxes are fractions of the image, 0.0 to 1.0**, as [left, top, right, bottom].
  Do not use pixels. 0,0 is the top-left corner.
- **role must be one of**: %(roles)s. The animator dispatches on role and
  ignores name, so a "sword_arm" named part with role "arm_near" animates
  correctly. Use "body" for anything that should simply ride its parent.
- **Exactly one part has "parent": null.** That is the root -- torso for a
  humanoid, body for anything else. Every other part names its parent.
- **pivot is the joint: the point that stays still when the part rotates.**
  A shoulder, not the middle of the arm. A neck, not the middle of the head.
  It usually sits just inside the PARENT, on the edge they share.
- **near vs far**: "near" is the limb on the camera side, drawn in front of the
  body; "far" is the one drawn behind it. If both limbs are visible, the one
  that overlaps the torso is near. If only one arm is visible, call it arm_near
  and still emit an arm_far box over the same pixels -- a one-armed walk cycle
  reads as a bug.
- **Cover the whole character.** Every opaque pixel should fall inside at least
  one box, or it will be dropped from every frame. Overlap is fine and expected;
  the smallest box containing a pixel is the one that owns it, so a head box
  inside a torso box does the right thing.
- **Do not invent parts you cannot see.** A character with no tail gets no tail.
  Confidence below 0.5 on a part means "I think this is here"; the pipeline
  weights it and shows it to the user for confirmation.

Look at the 6x image before answering. On sprites the difference between a hand \
and a hilt is four pixels."""


class HeadlessBackend(Backend):
    """`claude -p` with the reference image on disk. No API key involved.

    The session already holds credentials, so a plain `claude -p --allowed-tools
    Read` can open a PNG off the filesystem and look at it. That is the whole
    mechanism, and it means this plugin costs a user nothing beyond the Claude
    subscription they already have.

    **Name the model.** The headless default is Sonnet, and on a 32x32 sprite the
    difference between Sonnet and Opus is the difference between "arm" and "arm,
    but it is actually the scabbard". Opus is the default here for that reason.
    """

    def __init__(self, workdir, model="claude-opus-5", timeout=300, executable="claude"):
        self.workdir = workdir
        self.model = model
        self.timeout = timeout
        self.executable = executable
        self.actor = "llm:%s@headless" % model
        self.last_raw = None

    def available(self):
        from shutil import which
        return which(self.executable) is not None

    def rig(self, reference, character_class="auto", facing="right", intent=""):
        os.makedirs(self.workdir, exist_ok=True)
        native = os.path.join(self.workdir, "rig-input-native.png")
        zoomed = os.path.join(self.workdir, "rig-input-6x.png")
        img.save(reference.pixels, native)
        img.save(img.scale_nearest(reference.pixels, 6), zoomed)

        height, width = reference.pixels.shape[:2]
        prompt = DESCRIBE_PROMPT % {
            "width": width, "height": height,
            "roles": ", ".join(rig_module.ROLES),
            "intent": ("The user says this is: %s\n" % intent) if intent else "",
        }
        prompt += "\n\nRead these two files: %s and %s\n" % (native, zoomed)

        answer = self._ask(prompt)
        self.last_raw = answer
        return self.parse(answer, reference, facing)

    def _ask(self, prompt):
        command = [self.executable, "-p", prompt, "--allowed-tools", "Read",
                   "--model", self.model, "--output-format", "json"]
        try:
            finished = subprocess.run(command, capture_output=True, timeout=self.timeout)
        except FileNotFoundError:
            raise RuntimeError("no %r on PATH; use --backend template to rig from the "
                               "silhouette instead" % self.executable)
        except subprocess.TimeoutExpired:
            raise RuntimeError("`claude -p` did not answer within %ds" % self.timeout)
        if finished.returncode != 0:
            raise RuntimeError("`claude -p` failed (%d): %s"
                               % (finished.returncode, finished.stderr.decode()[:400]))
        payload = json.loads(finished.stdout.decode())
        return payload.get("result", "") if isinstance(payload, dict) else str(payload)

    def parse(self, answer, reference, facing="right"):
        """Turn the model's JSON into a validated Rig, repairing what is repairable.

        A model that returns a box slightly outside the image, or forgets a
        pivot, has still done the hard part. Clamp and infer rather than throw:
        the failures worth refusing are structural (no root, no parts), not
        arithmetic.
        """
        data = _extract_json(answer)
        height, width = reference.pixels.shape[:2]
        raw_parts = data.get("parts") or []
        if not raw_parts:
            raise ValueError("the vision backend returned no parts; re-run with "
                             "--backend template or pass --intent to say what "
                             "the character is")

        notes, parts = [], []
        for entry in raw_parts:
            name = str(entry.get("name") or entry.get("role") or "part%d" % len(parts))
            role = str(entry.get("role") or "body")
            if role not in rig_module.ROLES:
                notes.append("%s: role %r is not in the vocabulary, animating as body"
                             % (name, role))
                role = "body"
            box = _denormalise_box(entry.get("box"), width, height)
            if box is None:
                notes.append("%s: unusable box %r, dropped" % (name, entry.get("box")))
                continue
            pivot = _denormalise_point(entry.get("pivot"), width, height)
            if pivot is None:
                pivot = ((box[0] + box[2]) // 2, box[1])
                notes.append("%s: no pivot given, using the top-centre of its box" % name)
            parts.append(rig_module.Part(name, role, box, entry.get("parent"), pivot,
                                         Z_BY_ROLE.get(role, 1),
                                         float(entry.get("confidence", 0.7))))

        roots = [part for part in parts if part.parent is None]
        if not roots:
            # Pick the largest part as the root rather than refusing: a rig with
            # a wrong root still animates, a rig with no root cannot be walked.
            largest = max(parts, key=lambda part: part.area)
            largest.parent = None
            notes.append("no root was given; %s is the largest part and was made "
                         "the root" % largest.name)
        elif len(roots) > 1:
            keeper = max(roots, key=lambda part: part.area)
            for extra in roots:
                if extra is not keeper:
                    extra.parent = keeper.name
                    notes.append("%s was a second root; reparented to %s"
                                 % (extra.name, keeper.name))

        known = {part.name for part in parts}
        root_name = next(part.name for part in parts if part.parent is None)
        for part in parts:
            if part.parent is not None and part.parent not in known:
                notes.append("%s named a parent (%r) that does not exist; reparented "
                             "to the root" % (part.name, part.parent))
                part.parent = root_name

        built = rig_module.Rig((width, height), parts,
                               data.get("class", "humanoid"),
                               data.get("facing", facing),
                               anchor=(width // 2, height),
                               actor=self.actor, notes=notes)
        _break_cycles(built)
        return built


def _break_cycles(built):
    """Reparent anything that cannot reach the root, so FK terminates."""
    root = built.root
    if root is None:
        return
    for part in built.parts:
        seen, cursor = set(), part
        while cursor is not None and cursor.parent is not None:
            if cursor.name in seen:
                part.parent = root.name
                built.notes.append("%s sat in a parent cycle; reparented to %s"
                                   % (part.name, root.name))
                break
            seen.add(cursor.name)
            cursor = built.by_name(cursor.parent)


def _extract_json(text):
    """Pull the first JSON object out of a model answer that may be fenced."""
    if isinstance(text, dict):
        return text
    text = str(text).strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, depth = text.find("{"), 0
    if start < 0:
        raise ValueError("no JSON object in the vision answer: %s" % text[:200])
    for index in range(start, len(text)):
        depth += (text[index] == "{") - (text[index] == "}")
        if depth == 0:
            return json.loads(text[start:index + 1])
    raise ValueError("unterminated JSON in the vision answer: %s" % text[:200])


def _denormalise_box(box, width, height):
    if not box or len(box) != 4:
        return None
    try:
        values = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    # Tolerate a model that answered in pixels despite being asked for fractions.
    if max(values) > 1.5:
        x0, y0, x1, y1 = [int(round(v)) for v in values]
    else:
        x0 = int(round(values[0] * width)); x1 = int(round(values[2] * width))
        y0 = int(round(values[1] * height)); y1 = int(round(values[3] * height))
    x0, x1 = sorted((max(0, min(x0, width)), max(0, min(x1, width))))
    y0, y1 = sorted((max(0, min(y0, height)), max(0, min(y1, height))))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _denormalise_point(point, width, height):
    if not point or len(point) != 2:
        return None
    try:
        x, y = float(point[0]), float(point[1])
    except (TypeError, ValueError):
        return None
    if max(abs(x), abs(y)) <= 1.5:
        x, y = x * width, y * height
    return (int(max(0, min(round(x), width))), int(max(0, min(round(y), height))))


def make_backend(name, workdir, model="claude-opus-5"):
    if name in ("template", "none", "deterministic"):
        return TemplateBackend()
    if name in ("claude", "headless", "vision"):
        return HeadlessBackend(workdir, model=model)
    raise ValueError("unknown rig backend %r (template | claude)" % name)
