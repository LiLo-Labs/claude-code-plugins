"""Everything that is not a character: props, buildings, plants, cloth, machines.

Two kinds of motion live here and they are not the same kind of thing.

**Whole-object clips** -- bob, spin, tumble, pulse, swing -- move the sprite as
one piece. For a coin or a potion that is not a lesser path, it is the right
answer: articulating a gem would make it worse. The interesting one is the spin.
A 2D object turning about its vertical axis has no back face to draw, so it
narrows to nothing and reappears mirrored; that is exactly how a hand-drawn coin
spin works, and `flip_from` is the instant it passes edge-on.

**Trait-addressed clips** -- turn, sway, gust, ripple, creak -- move the parts a
subject actually has, and they are addressed by what those parts ARE rather than
by a name. `trait:spinner` is "the thing that turns about a hub", which is a
windmill's sails, a waterwheel, a cog and a fan; `trait:stalk` is "fixed at its
base, free at its tip", which is a tree's canopy, a flag, a cape and a field of
wheat. One clip, written once, drives all of them -- and drives nothing at all
on a subject that has none, which the build reports rather than shipping a
sheet of identical frames.

That is the difference between this and offering a house that bobs.
"""

from .motion import Animation


def _library():
    bob = Animation(
        "bob", frames=4, fps=6, loop=True,
        note="a pickup breathing in place, so the player's eye finds it. Two "
             "things about four numbers. It rises fast and sinks slowly rather "
             "than bobbing evenly, because a symmetric rise and fall draws the "
             "SAME picture going up and coming down and a four-frame clip "
             "cannot afford to spend one on a repeat. And the keys sit exactly "
             "on the four frame times at whole-pixel heights, because a clip "
             "this short has nowhere to hide: a key between frames means the "
             "renderer samples a height nobody chose and rounds two of them "
             "together",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.25, "dy": -2.0},
              {"t": 0.5, "dy": -3.0}, {"t": 0.75, "dy": -1.0}])

    spin = Animation(
        "spin", frames=8, fps=12, loop=True, flip_from=0.5,
        note="a coin turning about its vertical axis: it squashes to edge-on at the "
             "quarter points and comes back mirrored, which is the whole trick",
        root=[{"t": 0.0, "sx": 1.0}, {"t": 0.25, "sx": 0.14}, {"t": 0.5, "sx": 1.0},
              {"t": 0.75, "sx": 0.14}, {"t": 1.0, "sx": 1.0}])

    tumble = Animation(
        "tumble", frames=8, fps=12, loop=True,
        note="a thrown item turning end over end; a full turn per cycle so the loop "
             "is seamless without a duplicate frame",
        root=[{"t": 0.0, "angle": 0.0, "easing": "linear"},
              {"t": 0.5, "angle": 180.0, "easing": "linear"},
              {"t": 1.0, "angle": 360.0, "easing": "linear"}])

    pulse = Animation(
        "pulse", frames=6, fps=10, loop=True,
        note="a squash-and-stretch pulse: the volume is kept, so it reads as "
             "elastic rather than as the sprite changing size",
        root=[{"t": 0.0, "sx": 1.0, "sy": 1.0},
              {"t": 0.4, "sx": 1.14, "sy": 0.88},
              {"t": 0.7, "sx": 0.93, "sy": 1.08},
              {"t": 1.0, "sx": 1.0, "sy": 1.0}])

    swing = Animation(
        "swing", frames=6, fps=12, loop=False,
        note="a held weapon's arc, for compositing over a character's attack",
        root=[{"t": 0.0, "angle": 55.0}, {"t": 0.35, "angle": -70.0, "easing": "ease_in"},
              {"t": 0.5, "angle": -85.0}, {"t": 1.0, "angle": 0.0}])

    # --- addressed by trait, so they work on any subject that has one ------

    turn = Animation(
        "turn", frames=8, fps=10, loop=True,
        note="every hub turns a full revolution at a constant rate: sails, a "
             "waterwheel, a cog, a fan. Constant because a windmill does not "
             "ease -- and a full turn per cycle so the loop closes with no "
             "duplicate frame",
        tracks={"trait:spinner": [{"t": 0.0, "angle": 0.0, "easing": "linear"},
                                  {"t": 0.5, "angle": 180.0, "easing": "linear"},
                                  {"t": 1.0, "angle": 360.0, "easing": "linear"}]})

    sway = Animation(
        "sway", frames=8, fps=8, loop=True,
        note="anything fixed at its base and free at its tip rocks in the wind. "
             "Two things stop it reading as a metronome. The spread means each "
             "part in turn starts after the one before, so the motion travels "
             "across a canopy or a field. A stalk hinges and a surface LEANS -- "
             "cloth has no joint to turn about, so the surface half of this "
             "drives `shear` rather than `angle`. And the curve is a gust and a "
             "drift "
             "back rather than an even swing -- an even swing passes through "
             "the same angles on the way out and the way back, so half its "
             "frames are duplicates of the other half, which is what happened "
             "on the first real cape this was run against: five different "
             "pictures out of eight",
        tracks={"trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                         {"t": 0.18, "angle": 8.0,
                                          "easing": "ease_out"},
                                         {"t": 0.42, "angle": 3.0},
                                         {"t": 0.60, "angle": -5.0,
                                          "easing": "ease_out"},
                                         {"t": 0.84, "angle": -1.5}],
                                "spread": 0.09},
                "trait:surface": {"keys": [{"t": 0.0, "shear": 0.0},
                                           {"t": 0.22, "shear": 5.0,
                                            "easing": "ease_out"},
                                           {"t": 0.48, "shear": 1.5},
                                           {"t": 0.66, "shear": -4.0},
                                           {"t": 0.88, "shear": -0.5}],
                                  "spread": 0.09}})

    gust = Animation(
        "gust", frames=10, fps=12, loop=False,
        note="a one-shot: the wind arrives, everything leans away from it, and "
             "it settles back past the rest position before stopping. The "
             "overshoot is what stops it reading as a slider being dragged",
        tracks={"trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                         {"t": 0.25, "angle": 17.0,
                                          "easing": "ease_out"},
                                         {"t": 0.45, "angle": 13.0},
                                         {"t": 0.75, "angle": -4.0},
                                         {"t": 1.0, "angle": 0.0}],
                                "spread": 0.06},
                "trait:crown": [{"t": 0.0, "angle": 0.0},
                                {"t": 0.3, "angle": 6.0, "easing": "ease_out"},
                                {"t": 1.0, "angle": 0.0}]})

    ripple = Animation(
        "ripple", frames=8, fps=10, loop=True,
        note="a broad face that has no joint to hinge about -- water, a banner, "
             "a curtain -- so it LEANS rather than turning: `shear` keeps the "
             "base where the artist drew it and slides everything above it. "
             "Measured on a CC0 flag against the artist\'s own sixteen frames, "
             "shear takes the worst frame from 0.22% loose to 0.03% and lands "
             "closest to the artist in how much of the picture it disturbs. It "
             "travels: the spread is a whole eighth of the cycle, so "
             "consecutive faces are visibly out of step rather than breathing "
             "together. Asymmetric for the same reason `sway` is: a wave that "
             "retraces its own path spends half its frames redrawing pictures "
             "the viewer has already seen",
        tracks={"trait:surface": {"keys": [{"t": 0.0, "shear": 0.0, "dy": 0.0},
                                           {"t": 0.16, "shear": 5.0, "dy": -1.0,
                                            "easing": "ease_out"},
                                           {"t": 0.38, "shear": 2.0, "dy": -1.0},
                                           {"t": 0.58, "shear": -3.5, "dy": 0.0},
                                           {"t": 0.80, "shear": -1.0, "dy": -1.0}],
                                  "spread": 0.125}})

    creak = Animation(
        "creak", frames=6, fps=8, loop=True,
        note="the small idle motion of a thing hung on a building: a shutter, a "
             "sign, a lantern, a door. Deliberately tiny -- it is meant to be "
             "noticed only once the player stops moving",
        tracks={"trait:socket": {"keys": [{"t": 0.0, "angle": 0.0},
                                          {"t": 0.35, "angle": 3.0},
                                          {"t": 0.7, "angle": -2.0}],
                                 "spread": 0.15}})

    # --- palette-space: nothing moves, the shading does --------------------

    flicker = Animation(
        "flicker", frames=6, fps=12, loop=True,
        note="a torch, a lantern, a forge, a rune. Nothing moves at all -- "
             "every pixel stays exactly where the artist put it and steps along "
             "its own shading ramp instead, so the light changes and the "
             "silhouette does not. It STEPS rather than fading, and the steps "
             "are uneven on purpose: an even brighten-and-dim reads as a pulse, "
             "and a flame does not pulse. The step is a whole shade, because a "
             "third of a shade is the same shade. Rest, a small dip and a big "
             "one alternate rather than running together, because a shallow "
             "ramp collapses several sizes of step onto the same picture: a "
             "four-shade flame has three states however many numbers it is "
             "given, so the order has to guarantee that consecutive frames land "
             "on different ones",
        tracks={"trait:glow": {"keys": [{"t": 0.0, "cycle": 0.0},
                                        {"t": 1 / 6.0, "cycle": -1.0},
                                        {"t": 2 / 6.0, "cycle": 0.0},
                                        {"t": 3 / 6.0, "cycle": -2.0},
                                        {"t": 4 / 6.0, "cycle": 1.0},
                                        {"t": 5 / 6.0, "cycle": -3.0}],
                               "spread": 1 / 6.0}})

    shimmer = Animation(
        "shimmer", frames=8, fps=8, loop=True,
        note="light travelling across water or glass: a slow ramp step with a "
             "big spread, so consecutive faces darken one after another rather "
             "than the whole surface catching it at once",
        tracks={"trait:surface": {"keys": [{"t": step / 8.0, "cycle": value}
                                           for step, value in enumerate(
                                               (0, 1, 2, 1, 0, -1, -2, -1))],
                                  "spread": 0.25}})

    return {animation.name: animation for animation in
            (bob, spin, tumble, pulse, swing, turn, sway, gust, ripple, creak,
             flicker, shimmer)}


LIBRARY = _library()

# Everything a whole-object clip can do, plus everything a subject's own parts
# can. A subject that has none of a clip's traits does not get a sheet of
# identical frames -- `pipeline` drops the clip and says why.
PRESET_SETS = {
    "pickup": ["bob", "spin"],
    "coin": ["spin"],
    "weapon": ["swing", "bob"],
    "building": ["turn", "creak", "sway", "flicker"],
    "machine": ["turn", "creak"],
    "plant": ["sway", "gust"],
    "cloth": ["ripple", "sway", "gust"],
    "water": ["ripple", "shimmer"],
    "weather": ["ripple", "sway"],
    "light": ["flicker"],
    "all": ["bob", "spin", "tumble", "pulse", "swing",
            "turn", "sway", "gust", "ripple", "creak", "flicker", "shimmer"],
}


def get(name):
    if name in LIBRARY:
        return LIBRARY[name]
    raise KeyError("no prop animation %r; have %s" % (name, ", ".join(sorted(LIBRARY))))


def resolve(names):
    """The same fallthrough as `motion.resolve`, the other way round.

    A subject build asking for `walk` gets the character walk, which will drive
    nothing on a one-piece rig and be dropped with a reason -- which is a better
    answer than a KeyError listing five prop clips.
    """
    from . import motion as motion_module
    return motion_module._resolve(names, PRESET_SETS, LIBRARY, motion_module)
