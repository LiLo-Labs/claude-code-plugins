"""Eight-direction movement from the references the user actually has.

This is where it would be easy to lie. A top-down or isometric game needs the
character seen from eight yaws, and one side-on drawing does not contain seven
of them: nothing in a profile says what the back of the head looks like. So
every direction this module produces records how it was made and how much to
trust it:

  drawn         a reference was supplied for this view
  mirrored      the opposite side, flipped -- exact for a symmetric character
  foreshortened a neighbouring view squashed towards its edge-on width; a real
                technique for the 3/4 views and honest about being an approximation
  substituted   no neighbour was close enough; the nearest view is used as-is

`--reference-front` and `--reference-back` turn the substituted and foreshortened
views into drawn ones. The report says which directions are still approximate,
so the user knows exactly what to draw next to fix it.
"""

import math

import numpy as np

from . import image as img

# Yaw in degrees, measured from east, increasing clockwise on screen: the
# character walking right is 0, walking down the screen (towards the camera) is
# 90, walking left is 180, away from the camera is 270.
DIRECTIONS = {"E": 0.0, "SE": 45.0, "S": 90.0, "SW": 135.0,
              "W": 180.0, "NW": 225.0, "N": 270.0, "NE": 315.0}

SETS = {
    "1": ["E"],
    "2": ["E", "W"],
    "4": ["E", "S", "W", "N"],
    "8": ["E", "SE", "S", "SW", "W", "NW", "N", "NE"],
}

# What each supplied reference is a view of.
VIEW_YAW = {"side": 0.0, "front": 90.0, "back": 270.0}

# Below this the squash is more distortion than foreshortening, so the view is
# marked substituted and left at full width rather than smeared into a line.
MIN_SQUASH = 0.55


def signed_gap(source, target):
    return (target - source + 180.0) % 360.0 - 180.0


def choose_source(target_yaw, available):
    """Pick the view to build `target_yaw` from, and say how.

    A view and its mirror both count as candidates, because mirroring a
    character costs nothing and is exact whenever the character is symmetric --
    which for a sprite is nearly always, and where it is not (a sword on one
    hip) the user can supply the other side as its own reference.
    """
    best = None
    for name, yaw in available.items():
        for flip in (False, True):
            source_yaw = (180.0 - yaw) % 360.0 if flip else yaw
            gap = abs(signed_gap(source_yaw, target_yaw))
            if best is None or gap < best[0] - 1e-9:
                best = (gap, name, flip)
    gap, name, flip = best

    if gap < 1e-6:
        return name, flip, 1.0, ("mirrored" if flip else "drawn")
    squash = math.cos(math.radians(gap))
    if squash < MIN_SQUASH:
        return name, flip, 1.0, "substituted"
    return name, flip, squash, "foreshortened"


def squash_frame(frame, factor):
    """Narrow a frame about its horizontal centre, nearest-neighbour.

    Foreshortening a 2D sprite is a horizontal scale and nothing else: a body
    turning away from the camera loses width and keeps height. Doing it on the
    finished frame rather than on the rig means it composes with any animation
    and cannot desynchronise a limb from its body.
    """
    if factor >= 0.999:
        return frame.copy()
    height, width = frame.shape[:2]
    narrow = max(1, int(round(width * factor)))
    columns = np.clip((np.arange(narrow) / factor).astype(np.int64), 0, width - 1)
    thin = frame[:, columns]
    out = img.blank(height, width)
    img.paste(out, thin, (width - narrow) // 2, 0)
    return out


class DirectionPlan:
    def __init__(self, name, yaw, source, flip, squash, fidelity):
        self.name = name
        self.yaw = yaw
        self.source = source
        self.flip = flip
        self.squash = squash
        self.fidelity = fidelity

    def apply(self, frame):
        out = squash_frame(frame, self.squash) if self.squash < 0.999 else frame.copy()
        return out[:, ::-1].copy() if self.flip else out

    def to_dict(self):
        return {"name": self.name, "yaw": self.yaw, "source": self.source,
                "flip": self.flip, "squash": round(self.squash, 4),
                "fidelity": self.fidelity}


def plan(direction_set, references):
    """Plans for each direction, given which reference views exist.

    `references` is a dict like {"side": ..., "front": ...}; only the keys are
    read here. `side` is assumed present -- it is the reference the user gave.
    """
    names = SETS.get(str(direction_set))
    if names is None:
        names = [name.strip().upper() for name in str(direction_set).split(",")
                 if name.strip()]
        unknown = [name for name in names if name not in DIRECTIONS]
        if unknown:
            raise ValueError("unknown directions %s; use one of %s or a comma list of %s"
                             % (", ".join(unknown), "/".join(sorted(SETS)),
                                ", ".join(DIRECTIONS)))
    available = {name: VIEW_YAW[name] for name in references if name in VIEW_YAW}
    if not available:
        available = {"side": 0.0}

    plans = []
    for name in names:
        yaw = DIRECTIONS[name]
        source, flip, squash, fidelity = choose_source(yaw, available)
        plans.append(DirectionPlan(name, yaw, source, flip, squash, fidelity))
    return plans


def advice(plans):
    """What the user could draw to make the approximate directions exact.

    The cardinals are fixable: S and N become exact the moment a front or back
    reference exists. The diagonals are not -- a 3/4 view is its own drawing,
    and no combination of the three cardinal references contains it. Saying so
    is more useful than implying another upload will clear the warning.
    """
    by_fidelity = {}
    for entry in plans:
        by_fidelity.setdefault(entry.fidelity, []).append(entry.name)

    lines = []
    missing = []
    if any(name in ("S",) for name in by_fidelity.get("substituted", [])):
        missing.append("--reference-front")
    if any(name in ("N",) for name in by_fidelity.get("substituted", [])):
        missing.append("--reference-back")
    substituted = sorted(by_fidelity.get("substituted", []))
    if substituted:
        lines.append("%s %s no reference near enough and reuse the side view "
                     "unchanged.%s"
                     % (", ".join(substituted), "have" if len(substituted) > 1 else "has",
                        (" Supply %s to draw %s properly."
                         % (" and ".join(missing),
                            "them" if len(substituted) > 1 else "it")) if missing else ""))
    diagonals = sorted(by_fidelity.get("foreshortened", []))
    if diagonals:
        lines.append("%s %s foreshortened from the nearest view. That is the "
                     "standard approximation for 3/4 sprites; only a drawing of "
                     "that exact angle improves on it."
                     % (", ".join(diagonals), "are" if len(diagonals) > 1 else "is"))
    return " ".join(lines)
