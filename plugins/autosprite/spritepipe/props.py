"""Props: weapons, pickups, coins, gems -- everything that is not a character.

A prop has no skeleton worth building, so it rigs as one piece and animates as
one piece. That is not a lesser path: a spinning coin, a bobbing potion and a
pulsing pickup are all whole-object transforms, and articulating them would make
them worse.

The one interesting case is the spin. A 2D object rotating about its vertical
axis has no back face to draw, so it narrows to nothing and reappears mirrored.
That is exactly how hand-drawn coin spins work, and `flip_from` in the animation
is the instant it passes edge-on.
"""

from .motion import Animation


def _library():
    bob = Animation(
        "bob", frames=4, fps=6, loop=True,
        note="a pickup breathing in place, so the player's eye finds it",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.5, "dy": -2.0}, {"t": 1.0, "dy": 0.0}])

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

    return {animation.name: animation for animation in (bob, spin, tumble, pulse, swing)}


LIBRARY = _library()
PRESET_SETS = {
    "pickup": ["bob", "spin"],
    "coin": ["spin"],
    "weapon": ["swing", "bob"],
    "all": ["bob", "spin", "tumble", "pulse", "swing"],
}


def get(name):
    if name in LIBRARY:
        return LIBRARY[name]
    raise KeyError("no prop animation %r; have %s" % (name, ", ".join(sorted(LIBRARY))))


def resolve(names):
    wanted = []
    for name in names:
        wanted.extend(PRESET_SETS.get(name, [name]))
    seen, out = set(), []
    for name in wanted:
        if name not in seen:
            seen.add(name)
            out.append(get(name))
    return out
