"""The rig: which pixels are which part of the character, and where they hinge.

This is the only artefact in the pipeline that a model has an opinion about, and
it is deliberately the smallest one. A part is a name, an axis-aligned box in the
reference image, a parent, and a pivot -- four things a vision model can be held
to and a human can correct in ten seconds by editing one line of JSON.

Everything a model is *bad* at stays out: no masks, no per-pixel boundaries, no
angles, no timing. Those come from the pixels and from `motion.py`, which are
deterministic and therefore reviewable.

Coordinates are integer pixels in the reference image's own frame, origin
top-left. Boxes are half-open (x0, y0, x1, y1). Pivots may sit outside their own
box -- a shoulder joint is usually just inside the torso, not inside the arm.
"""

import json

# The motion library dispatches on `role`, never on `name`. A user may rename
# "arm_near" to "sword_arm" and every animation still works, because the role
# underneath is unchanged. Anything not in this list animates as `body`: it
# follows its parent and is never independently swung.
ROLES = (
    "body",        # the root mass; everything hangs off it
    "torso",       # upper body, leans and twists
    "head",        # counter-bobs, tilts
    "arm_near",    # the arm on the camera side
    "arm_far",     # the arm on the far side, drawn behind the body
    "leg_near",
    "leg_far",
    "tail",        # trails the body with a lag
    "wing_near",
    "wing_far",
    "shadow",      # a baked ground shadow; stays on the floor, never moves
    "prop",        # a held item; rides the near arm if one exists
    "accessory",   # hats, capes, scarves; ride the parent with a small lag
)

PAIRED = {
    "arm_near": "arm_far", "arm_far": "arm_near",
    "leg_near": "leg_far", "leg_far": "leg_near",
    "wing_near": "wing_far", "wing_far": "wing_near",
}

# What a part IS, as opposed to what a humanoid calls it.
#
# The role list above is thirteen anatomical names, and it is simultaneously the
# part vocabulary, the animation address space and the z-order table -- for
# every subject in the world. That is why a windmill is offered a house that
# bobs: `sails` is not in the list, and nothing in the list means "this turns
# about its hub".
#
# A trait is the property an animation actually wants to address. "Fixed at its
# base, free at its tip, so it trails" is a real universal: it is true of a
# tail, a cape, a chimney's plume, a tree's canopy and a flag, and false of an
# arm. `arm_near` is not a universal of anything. Addressing a lag at `stalk`
# is one line that works on all five; addressing it at `tail` works on one.
TRAITS = (
    "mass",       # the main body; everything else hangs off it
    "crown",      # sits on top of the mass and counter-moves
    "limb",       # swings from a joint at one end
    "support",    # a limb that reaches the floor and takes weight
    "stalk",      # fixed at its base, free at its tip; it trails
    "spinner",    # turns continuously about a hub -- sails, wheels, cogs
    "surface",    # a broad face that ripples rather than hinges -- cloth, water
    "socket",     # attached and swappable; rides its host
    "ground",     # not part of the subject at all; the floor under it
    "glow",       # emits or catches light, so it brightens and dims in place
    "flow",       # something moves THROUGH it while it stays where it is --
                  # rain, snow, a waterfall, a river, a conveyor, smoke
)

TRAITS_BY_ROLE = {
    "body": ("mass",),
    "torso": ("mass",),
    "head": ("crown",),
    "arm_near": ("limb",),
    "arm_far": ("limb",),
    "leg_near": ("limb", "support"),
    "leg_far": ("limb", "support"),
    "tail": ("stalk",),
    "wing_near": ("limb",),
    "wing_far": ("limb",),
    "shadow": ("ground",),
    "prop": ("socket",),
    # Documented as "ride the parent with a small lag", which is what a stalk
    # does. A cape and a scarf are stalks; a hat is the odd one out and its
    # rigger can drop the tag.
    "accessory": ("socket", "stalk"),
}


class Part:
    def __init__(self, name, role, box, parent=None, pivot=None, z=0,
                 confidence=1.0, tags=()):
        self.name = str(name)
        self.role = str(role)
        self.box = tuple(int(v) for v in box)
        self.parent = parent
        self.pivot = tuple(int(v) for v in pivot) if pivot is not None else None
        self.z = int(z)
        self.confidence = float(confidence)
        # Traits this part has beyond the ones its role implies. This is the
        # escape hatch out of the thirteen-name enum: a windmill's sails keep
        # whatever role the rig gave them and are tagged `spinner`, and every
        # animation addressed at spinners then drives them.
        self.tags = tuple(str(tag) for tag in tags)

    @property
    def traits(self):
        """Everything this part can be addressed as, role and tags together."""
        found = list(TRAITS_BY_ROLE.get(self.role, ()))
        for tag in self.tags:
            if tag not in found:
                found.append(tag)
        return tuple(found)

    def has_trait(self, trait):
        return trait in self.traits

    @property
    def width(self):
        return self.box[2] - self.box[0]

    @property
    def height(self):
        return self.box[3] - self.box[1]

    @property
    def area(self):
        return self.width * self.height

    def to_dict(self):
        document = {"name": self.name, "role": self.role, "box": list(self.box),
                    "parent": self.parent,
                    "pivot": list(self.pivot) if self.pivot else None,
                    "z": self.z, "confidence": round(self.confidence, 3)}
        if self.tags:
            document["tags"] = list(self.tags)
        return document

    @classmethod
    def from_dict(cls, data):
        return cls(data["name"], data.get("role", "body"), data["box"],
                   data.get("parent"), data.get("pivot"), data.get("z", 0),
                   data.get("confidence", 1.0), data.get("tags", ()))

    def __repr__(self):
        return "Part(%s, %s, box=%s, z=%d)" % (self.name, self.role, self.box, self.z)


class Rig:
    def __init__(self, size, parts, character_class="humanoid", facing="right",
                 anchor=None, actor="unknown", notes=None):
        self.size = (int(size[0]), int(size[1]))     # (width, height)
        self.parts = list(parts)
        self.character_class = character_class
        self.facing = facing
        self.anchor = tuple(int(v) for v in anchor) if anchor else None
        self.actor = actor
        self.notes = list(notes or [])

    # -- lookups -------------------------------------------------------------

    def by_name(self, name):
        for part in self.parts:
            if part.name == name:
                return part
        return None

    def by_role(self, role):
        return [part for part in self.parts if part.role == role]

    def first_role(self, role):
        found = self.by_role(role)
        return found[0] if found else None

    @property
    def root(self):
        for part in self.parts:
            if part.parent is None:
                return part
        return None

    def children(self, name):
        return [part for part in self.parts if part.parent == name]

    def draw_order(self):
        """Back to front. Ties broken by name so a rig always draws the same way."""
        return sorted(self.parts, key=lambda part: (part.z, part.name))

    def descend(self):
        """Parts in parent-before-child order, for forward kinematics."""
        order, seen = [], set()
        queue = [self.root] if self.root else []
        while queue:
            part = queue.pop(0)
            if part is None or part.name in seen:
                continue
            seen.add(part.name)
            order.append(part)
            queue.extend(self.children(part.name))
        # Anything unreachable still has to be drawn; validation will have
        # already complained about it.
        order.extend(part for part in self.parts if part.name not in seen)
        return order

    # -- serialisation -------------------------------------------------------

    def to_dict(self):
        return {
            "version": 1,
            "class": self.character_class,
            "facing": self.facing,
            "size": list(self.size),
            "anchor": list(self.anchor) if self.anchor else None,
            "actor": self.actor,
            "notes": self.notes,
            "parts": [part.to_dict() for part in self.parts],
        }

    @classmethod
    def from_dict(cls, data):
        return cls(data["size"], [Part.from_dict(p) for p in data["parts"]],
                   data.get("class", "humanoid"), data.get("facing", "right"),
                   data.get("anchor"), data.get("actor", "unknown"), data.get("notes"))

    def save(self, path):
        with open(path, "w") as handle:
            json.dump(self.to_dict(), handle, indent=2)
            handle.write("\n")

    @classmethod
    def load(cls, path):
        with open(path) as handle:
            return cls.from_dict(json.load(handle))


def validate(rig):
    """Return a list of problems. Empty means the rig is structurally sound.

    Structurally sound is not the same as correct -- a rig that calls the head a
    leg passes every check here. That is what the preview render is for. These
    checks only catch the failures that would make `render` crash or silently
    drop pixels, which are the ones a user cannot see in a picture.
    """
    problems = []
    width, height = rig.size

    if not rig.parts:
        return ["the rig has no parts"]

    names = [part.name for part in rig.parts]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        problems.append("duplicate part names: %s" % ", ".join(duplicates))

    roots = [part for part in rig.parts if part.parent is None]
    if not roots:
        problems.append("no root part (exactly one part must have parent: null)")
    elif len(roots) > 1:
        problems.append("%d root parts (%s); exactly one may have parent: null"
                        % (len(roots), ", ".join(p.name for p in roots)))

    known = set(names)
    for part in rig.parts:
        if part.parent is not None and part.parent not in known:
            problems.append("%s has parent %r, which is not a part" % (part.name, part.parent))
        if part.role not in ROLES:
            problems.append("%s has role %r, which is not one of %s"
                            % (part.name, part.role, ", ".join(ROLES)))
        x0, y0, x1, y1 = part.box
        if x1 <= x0 or y1 <= y0:
            problems.append("%s has an empty box %s" % (part.name, list(part.box)))
        if x0 < 0 or y0 < 0 or x1 > width or y1 > height:
            problems.append("%s box %s falls outside the %dx%d reference"
                            % (part.name, list(part.box), width, height))
        if part.pivot is None:
            problems.append("%s has no pivot" % part.name)

    # Cycles: walk every part up to the root and watch for a repeat.
    for part in rig.parts:
        seen, cursor = set(), part
        while cursor is not None and cursor.parent is not None:
            if cursor.name in seen:
                problems.append("parent cycle through %s" % part.name)
                break
            seen.add(cursor.name)
            cursor = rig.by_name(cursor.parent)

    if roots and len(roots) == 1:
        walked, queue = set(), [roots[0]]
        while queue:
            current = queue.pop()
            if current.name in walked:
                continue
            walked.add(current.name)
            queue.extend(rig.children(current.name))
        orphans = sorted(known - walked)
        if orphans:
            problems.append("unreachable from the root: %s" % ", ".join(orphans))

    # A paired limb whose partner is missing animates as a one-armed character,
    # which is nearly always a rigging miss rather than a design choice.
    for part in rig.parts:
        partner_role = PAIRED.get(part.role)
        if partner_role and not rig.by_role(partner_role):
            problems.append("%s is %s but there is no %s; paired limbs animate in "
                            "counter-phase and need both halves"
                            % (part.name, part.role, partner_role))
    return problems


def anchor_of(rig):
    """The point that must not move between frames: bottom-centre of the art.

    Every engine positions a sprite by one point. If that point wanders as the
    character animates, the character slides around the tile grid without anyone
    telling it to. Bottom-centre is the floor contact for a standing character
    and is what all six exporters below are given as the pivot.
    """
    if rig.anchor:
        return rig.anchor
    width, height = rig.size
    return (width // 2, height)
