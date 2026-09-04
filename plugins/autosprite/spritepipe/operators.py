"""Named rewrites of a keyframe table, so a principle is written once.

Every animation in this plugin is a table of numbers, and that is deliberate:
a user who does not like the run has to be able to open it, see
`leg_near: 0 -> +42 -> -42`, change the 42 and re-render. The cost of that is
real -- each of the things that separates motion which reads as ANIMATION from
motion which reads as parts moving has to be typed out again in every clip, by
hand, and gets typed out slightly differently each time.

An operator is the principle itself, as a function. It takes an animation and a
rig and returns another animation, and the only thing it ever touches is
keyframe numbers. So:

  - the artefact is still a table you can read and argue with. An operator is a
    source you can also read, and the table it produced is what ships.
  - the palette guarantee is untouched by construction. An operator reaches a
    pixel only through the same 3x3 matrix and the same ramp step that every
    number already in the library reaches it through. There is no third path,
    and an operator cannot open one, because it has nothing to write to but a
    keyframe.
  - a principle applies to every clip at once. `lag` written here is
    follow-through on a tail, a cape, a plume, a canopy and a chain, on all
    twenty-eight clips, rather than a twenty-ninth clip.

The address is `motion.select`'s -- a bare role, `name:X` or `trait:X` -- and
deliberately nothing more. An operator that needed its own expression language
would be a language a vision model has to emit correctly, and the one it
already has is a thirteen-word closed vocabulary it gets wrong often enough to
need repairing on the way in.

Operators are BAKED: most of them write an explicit key at every frame time.
That is exact, because rendering only ever samples those times -- but only at
the frame count they were baked at, which is why `pipeline` runs `--frames`
before this and never after.
"""

import copy
import math

from .motion import CHANNELS, EASINGS, REST, Animation, Lane, Track, phases, select
from .skeleton import PartPose

OPERATORS = {}


def operator(name, note, params=()):
    """Register a rewrite. `params` is what a JSON author may pass."""
    def register(function):
        OPERATORS[name] = {"name": name, "apply": function, "note": note,
                           "params": tuple(params)}
        return function
    return register


def apply_all(animation, rig, ops):
    """Run every op in order. Returns a new Animation; never mutates the input."""
    for entry in ops or ():
        name = entry.get("op")
        found = OPERATORS.get(name)
        if found is None:
            raise ValueError("no operator %r; have %s"
                             % (name, ", ".join(sorted(OPERATORS))))
        arguments = {key: value for key, value in entry.items() if key != "op"}
        animation = found["apply"](animation, rig, **arguments)
    return animation


def problems(ops):
    """What is wrong with a list of ops, as a list. Empty means usable."""
    found = []
    if not isinstance(ops, list):
        return ["ops must be a list of {\"op\": ...} objects"]
    for index, entry in enumerate(ops):
        if not isinstance(entry, dict) or "op" not in entry:
            found.append("op %d has no \"op\" name: %r" % (index, entry))
            continue
        known = OPERATORS.get(entry["op"])
        if known is None:
            found.append("op %d is %r, which is not an operator (%s)"
                         % (index, entry["op"], ", ".join(sorted(OPERATORS))))
            continue
        extra = set(entry) - {"op"} - set(known["params"])
        if extra:
            found.append("op %d (%s) does not take %s; it takes %s"
                         % (index, entry["op"], ", ".join(sorted(extra)),
                            ", ".join(known["params"])))
    return found


# ---------------------------------------------------------------------------
# the shared machinery: every operator below writes a baked track
# ---------------------------------------------------------------------------

def _departure(pose, channel):
    """How far one channel is from rest. Scales and rotations differ."""
    value = getattr(pose, channel)
    return value / REST[channel] if REST[channel] else value


def _restore(channel, factor):
    return factor * REST[channel] if REST[channel] else factor


def _bake(animation, rig, selector, per_frame, spread=None):
    """Replace `selector`'s track with an explicit key at every frame time.

    `per_frame(t, base)` returns the PartPose that frame should hold. The base
    is whatever the selector already resolves to, so an operator adds to the
    authored motion rather than replacing it.
    """
    clone = animation if isinstance(animation, Animation) else animation
    existing = clone.tracks.get(selector)
    keys = []
    for moment in clone.times():
        base = (existing.sample(moment, clone.loop) if existing is not None
                else PartPose())
        pose = per_frame(moment, base)
        key = {"t": moment}
        for channel in CHANNELS:
            key[channel] = round(float(getattr(pose, channel)), 5)
        keys.append(key)
    if spread is None:
        spread = existing.spread if existing is not None else 0.0
    # The axis travels with the spread. An operator that kept the spread and
    # dropped the axis would leave the wave the same size and silently turn it
    # back to declaration order, which is the failure this is hardest to see.
    along = existing.along if existing is not None else None
    clone.tracks[selector] = Track(keys, clone.easing, spread=spread, along=along)
    return clone


def _shifted(animation, moment, offset):
    if animation.loop:
        return (moment - offset) % 1.0
    return max(0.0, min(1.0, moment - offset))


def _hash(*items):
    """FNV-1a over the arguments' text.

    Written out rather than reached for because `hash()` is salted per process:
    a build seeded with it would give a different animation every run, which is
    the one thing a pipeline that verifies its own output cannot have.
    """
    value = 0x811c9dc5
    for item in items:
        for byte in str(item).encode("utf-8"):
            value ^= byte
            value = (value * 0x01000193) & 0xFFFFFFFF
    return value


def _wander(moment, name, channel, rate, seed):
    """A loop-closed pseudo-random signal for one part's one channel.

    Whole-numbered frequencies only, so the period is the cycle exactly, and
    amplitude falling as 1/k so the slow shape dominates and the fast one only
    roughens it -- which is what wind sounds like and what a pure sine does
    not. Unnormalised; the caller scales the whole selection together so that
    parts stay in proportion to each other.
    """
    total = 0.0
    for harmonic in range(1, rate + 1):
        phase = _hash("phase", seed, name, channel, harmonic) / float(0xFFFFFFFF)
        total += math.sin(2.0 * math.pi * (harmonic * moment + phase)) / harmonic
    return total


def _curve(points, easing="smooth"):
    return Lane([{"t": float(point["t"]), "v": float(point["v"]),
                  **({"easing": point["easing"]} if "easing" in point else {})}
                 for point in points], easing)


# ---------------------------------------------------------------------------
# the operators
# ---------------------------------------------------------------------------

@operator("lag", params=("on", "of", "frames", "damp", "channels"),
          note="follow-through: what a part does, done again later by the thing "
               "hanging off it. A cape after a torso, a canopy after a trunk, a "
               "tail after a body")
def lag(animation, rig, on, of, frames=1.0, damp=1.0, channels=("angle",)):
    """Add `of`'s motion, delayed and damped, to `on`'s.

    This is the single largest difference between motion that reads as
    animation and motion that reads as parts moving, and it is one line here
    against a rewritten table per clip by hand. On a loop the delay wraps, so
    the lag is exact rather than fading in over the first frames.
    """
    clone = copy.deepcopy(animation)
    source = clone.tracks.get(of)
    if source is None:
        return clone
    offset = float(frames) / float(max(1, clone.frames))
    channels = tuple(channels)

    def frame(moment, base):
        delayed = source.sample(_shifted(clone, moment, offset), clone.loop)
        pose = PartPose(*(getattr(base, channel) for channel in CHANNELS))
        for channel in channels:
            added = float(damp) * (getattr(delayed, channel) - REST[channel])
            setattr(pose, channel, getattr(base, channel) + added)
        return pose

    return _bake(clone, rig, on, frame)


@operator("envelope", params=("on", "curve", "channels"),
          note="amplitude as a function of time: a gust that arrives and dies, "
               "a shiver that builds, a flame that flares. Every other amplitude "
               "control here is one number for the whole clip")
def envelope(animation, rig, on, curve, channels=("angle", "dx", "dy")):
    """Scale `on`'s departure from rest by a curve sampled at each frame.

    The thing a constant cannot say. `damp` makes a whole cycle quieter;
    this makes the middle of it loud and the ends of it quiet, which is what
    every real gust, flinch and flare actually does.
    """
    clone = copy.deepcopy(animation)
    shape = _curve(curve, clone.easing)
    channels = tuple(channels)

    def frame(moment, base):
        gain = shape.sample(moment, clone.loop)
        pose = PartPose(*(getattr(base, channel) for channel in CHANNELS))
        for channel in channels:
            rest = REST[channel]
            setattr(pose, channel, rest + (getattr(base, channel) - rest) * gain)
        return pose

    return _bake(clone, rig, on, frame)


@operator("taper", params=("on", "gain", "channels"),
          note="a selection whose parts move by different amounts: a cape that "
               "moves more at the hem, a canopy that moves more at the tip")
def taper(animation, rig, on, gain, channels=("angle", "dx", "dy")):
    """Give part i of a matched set its own amplitude, `gain[0]` to `gain[1]`.

    `spread` gives an ordered selection its own TIMING; this gives it its own
    SIZE, and between them a chain of segments reads as a chain rather than as
    several copies of one thing. Emitted as `name:` tracks, which outrank the
    selector they came from, so the original is removed rather than left to
    compose on top of its own tapered copies.

    Both halves read the SAME placement -- `motion.phases`, and the track's own
    axis if it has one. That is the point of doing it this way rather than by
    rank: a canopy tapering toward its tip and a wave travelling toward its tip
    have to agree about which end is the tip, and if one counts parts while the
    other measures the image, they agree only while the rig is listed tidily.
    """
    clone = copy.deepcopy(animation)
    parts = select(rig, on)
    source = clone.tracks.get(on)
    if source is None or not parts:
        return clone
    low, high = float(gain[0]), float(gain[-1])
    channels = tuple(channels)
    spread = source.spread
    places = phases(rig, parts, source.along)
    reach = max(places) or 1.0
    del clone.tracks[on]

    for index, part in enumerate(parts):
        share = 0.0 if len(parts) == 1 else places[index] / reach
        factor = low + (high - low) * share
        moment_shift = places[index] * spread
        keys = []
        for moment in clone.times():
            base = source.sample(_shifted(clone, moment, moment_shift), clone.loop)
            key = {"t": moment}
            for channel in CHANNELS:
                rest = REST[channel]
                value = getattr(base, channel)
                if channel in channels:
                    value = rest + (value - rest) * factor
                key[channel] = round(float(value), 5)
            keys.append(key)
        clone.tracks["name:%s" % part.name] = Track(keys, clone.easing)
    return clone


@operator("damp", params=("on", "factor", "channels"),
          note="the whole of one track, quieter. What `repair` does to a limb "
               "that swings clear of the body, as reviewable data")
def damp(animation, rig, on, factor, channels=("angle",)):
    clone = copy.deepcopy(animation)
    if on not in clone.tracks:
        return clone
    for channel in tuple(channels):
        rest = REST[channel]
        clone.tracks[on].adjust(channel,
                                lambda value, rest=rest: rest + (value - rest) * float(factor))
    return clone


@operator("settle", params=("on", "overshoot", "cycles", "decay", "channel"),
          note="a one-shot that arrives and rings down instead of stopping "
               "dead. Follow-through for a motion with an end")
def settle(animation, rig, on, overshoot=0.2, cycles=1.5, decay=0.6,
           channel="angle"):
    """Ring the tail of a one-shot down around its final value.

    A motion that stops exactly on its target reads as a slider being released.
    Everything with mass overshoots and comes back, and how far it overshoots is
    how heavy it looks.
    """
    import math

    clone = copy.deepcopy(animation)
    source = clone.tracks.get(on)
    if source is None or clone.loop:
        return clone
    rest = REST[channel]
    times = clone.times()
    final = getattr(source.sample(times[-1], False), channel)
    start = getattr(source.sample(times[0], False), channel)
    swing = final - start
    if abs(swing) < 1e-6:
        return clone
    # The ring occupies the tail of the clip, after the motion has arrived.
    arrival = _arrival(source, times, channel, clone.loop)

    def frame(moment, base):
        pose = PartPose(*(getattr(base, name) for name in CHANNELS))
        if moment <= arrival or arrival >= 1.0:
            return pose
        phase = (moment - arrival) / (1.0 - arrival)
        amount = (-float(overshoot) * swing
                  * math.sin(2.0 * math.pi * float(cycles) * phase)
                  * (1.0 - phase) ** (1.0 / max(1e-6, float(decay))))
        setattr(pose, channel, final + amount)
        return pose

    return _bake(clone, rig, on, frame)


def _arrival(track, times, channel, loop):
    """When the curve stops travelling: the frame after its largest step."""
    values = [getattr(track.sample(moment, loop), channel) for moment in times]
    if len(values) < 2:
        return 1.0
    steps = [abs(values[index + 1] - values[index]) for index in range(len(values) - 1)]
    return times[min(len(times) - 1, steps.index(max(steps)) + 1)]


@operator("anticipate", params=("on", "amount", "lead", "channel"),
          note="the wind-up: a swing that goes backwards before it goes "
               "forwards, so the viewer sees it coming")
def anticipate(animation, rig, on, amount=0.18, lead=0.15, channel="angle"):
    """Make room at the start of a one-shot and wind up into it.

    Nothing in the library can express this without extra hand-typed keys,
    because all five original easings are monotone in 0..1 and none of them can
    go the wrong way first.

    It has to MAKE the room. A curve keyed to start at t=0 is already moving on
    frame 0, so there is nowhere to put a wind-up; the animator's answer is to
    push the action later and spend the freed frames going backwards, and that
    is what this does. The whole original curve is compressed into the tail, so
    the motion still ends where and when it did -- what changes is that the
    viewer sees it coming.

    One-shots only. A cycle has no start to wind up from, and compressing one
    would put a discontinuity at the loop.
    """
    clone = copy.deepcopy(animation)
    source = clone.tracks.get(on)
    if source is None or clone.loop:
        return clone
    times = clone.times()
    values = [getattr(source.sample(moment, False), channel) for moment in times]
    swing = max(values) - min(values)
    window = max(1e-6, min(0.5, float(lead)))
    if swing < 1e-6:
        return clone
    start = values[0]
    # Which way the motion goes, so the wind-up goes the other way.
    direction = 1.0 if max(values) - start >= start - min(values) else -1.0

    def frame(moment, base):
        pose = PartPose(*(getattr(base, name) for name in CHANNELS))
        if moment >= window:
            later = source.sample((moment - window) / (1.0 - window), False)
            for name in CHANNELS:
                setattr(pose, name, getattr(later, name))
            return pose
        share = 1.0 - abs(moment - window / 2.0) / (window / 2.0)
        setattr(pose, channel,
                start - direction * float(amount) * swing * max(0.0, share))
        return pose

    return _bake(clone, rig, on, frame)


@operator("hinge", params=("on", "degrees", "ease"),
          note="a door, a shutter, a lid, a book cover: something that swings "
               "about an edge in the third dimension, which flat-on is a "
               "narrowing rather than a turn")
def hinge(animation, rig, on, degrees=80.0, ease="smooth"):
    """Open a part about its own edge by narrowing it, not by rotating it.

    A door that ROTATES goes through the wall. What a door does is turn about a
    vertical axis, and seen flat-on that is `sx = cos(theta)` about the hinge
    edge -- the far edge sweeps towards the hinge and the drawing gets narrower
    while its height and its hinge side stay exactly where they were.

    The rig is what makes it read: the part's pivot has to sit ON the hinge
    edge, or the door narrows about its middle and swings out of its own frame.
    Nothing here can check that -- it is a fact about the drawing -- so it is
    said out loud rather than assumed.
    """
    import math

    clone = copy.deepcopy(animation)
    shape = EASINGS.get(ease, EASINGS["smooth"])
    span = math.radians(float(degrees))

    def frame(moment, base):
        pose = PartPose(*(getattr(base, channel) for channel in CHANNELS))
        pose.sx = base.sx * math.cos(span * shape(min(1.0, max(0.0, moment))))
        return pose

    return _bake(clone, rig, on, frame)


@operator("retime", params=("curve",),
          note="a time warp on the whole clip: the same poses in the same "
               "order, arrived at on a different schedule. A stagger, a limp, "
               "a beat held before the release")
def retime(animation, rig, curve):
    """Sample every track at f(t) instead of t.

    The one operator that touches the whole clip rather than a selection,
    because timing is not a property of a part. Everything here can already say
    what a pose IS and nothing could say WHEN -- so an uneven gait had to be
    faked by moving every keyframe of every track by hand, consistently, which
    is exactly the kind of thing that gets done inconsistently.

    `curve` maps 0..1 to 0..1. The identity changes nothing; a curve that rises
    slowly and then quickly holds the start of the clip and rushes its end.
    """
    clone = copy.deepcopy(animation)
    warp = _curve(curve, clone.easing)
    tracks = list(clone.tracks.items())
    if clone.root is not None:
        tracks.append(("root", clone.root))

    for selector, track in tracks:
        keys = []
        for moment in clone.times():
            warped = min(1.0, max(0.0, warp.sample(moment, False)))
            pose = track.sample(warped, clone.loop)
            key = {"t": moment}
            for channel in CHANNELS:
                key[channel] = round(float(getattr(pose, channel)), 5)
            keys.append(key)
        rebaked = Track(keys, clone.easing, spread=track.spread,
                        along=track.along)
        if selector == "root":
            clone.root = rebaked
        else:
            clone.tracks[selector] = rebaked
    return clone


@operator("turbulence",
          params=("on", "amount", "rate", "channels", "seed"),
          note="wind is not a sine wave. Every wind clip in the library is one "
               "curve played by every part, so a field reads as machinery; this "
               "gives each part its own small, ragged, LOOP-CLOSED wander on "
               "top of whatever it was already doing")
def turbulence(animation, rig, on, amount=2.0, rate=3, channels=("angle",),
               seed=0):
    """Give every part in a selection its own band-limited wander.

    Three properties, and each is load-bearing.

    **It closes.** The signal is a sum of sines at whole-numbered frequencies
    in the cycle, so its period is the cycle exactly. Sampled noise would need
    its ends stitched and would still drift; this cannot, because there is
    nothing in it that does not repeat. `rate` is the highest harmonic -- 1 is
    a slow lean, 5 is a jitter -- and it must be a whole number for the same
    reason.

    **It does not depend on the rig's typing.** The phase of each part's signal
    is hashed from the part's NAME, with a hash written out here rather than
    Python's, whose salt changes per process and would make a build
    irreproducible. Re-ordering a rig file re-orders nothing; renaming a part
    is the only thing that changes what it does, which is the honest coupling.

    **It composes rather than replaces.** The wander is emitted as `name:`
    tracks holding nothing but the departure, and `name:` outranks the trait or
    role selector the parts were addressed by, so the authored swing composes
    on top: the rotations add. Nothing else in the clip is disturbed, `spread`
    still spreads the authored curve, and a `taper` applied before or after
    this one still finds its own track where it left it.

    `amount` is a true ceiling, not an average: the signal is scaled so that
    the largest departure at any frame of any part is exactly `amount`.
    """
    if int(rate) != rate or int(rate) < 1:
        raise ValueError("turbulence rate must be a whole number of cycles per "
                         "loop (got %r); a fraction does not close the loop"
                         % (rate,))
    clone = copy.deepcopy(animation)
    parts = select(rig, on)
    channels = tuple(channels)
    unknown = [channel for channel in channels if channel not in CHANNELS]
    if unknown:
        raise ValueError("turbulence cannot write %s; the channels are %s"
                         % (", ".join(unknown), ", ".join(CHANNELS)))
    if not parts or not channels or not amount:
        return clone

    times = list(clone.times())
    signals = {}
    peak = 0.0
    for part in parts:
        for channel in channels:
            wander = [_wander(moment, part.name, channel, int(rate), seed)
                      for moment in times]
            signals[(part.name, channel)] = wander
            peak = max(peak, max(abs(value) for value in wander))
    if not peak:
        return clone
    gain = float(amount) / peak

    for part in parts:
        selector = "name:%s" % part.name
        existing = clone.tracks.get(selector)
        keys = []
        for index, moment in enumerate(times):
            base = (existing.sample(moment, clone.loop) if existing is not None
                    else PartPose())
            key = {"t": moment}
            for channel in CHANNELS:
                value = getattr(base, channel)
                if channel in channels:
                    step = signals[(part.name, channel)][index] * gain
                    # Departure from rest, so a squash MULTIPLIES and a
                    # rotation adds -- the same distinction `compose` makes.
                    value = value * (1.0 + step) if REST[channel] else value + step
                key[channel] = round(float(value), 5)
            keys.append(key)
        clone.tracks[selector] = Track(
            keys, clone.easing,
            spread=existing.spread if existing is not None else 0.0,
            along=existing.along if existing is not None else None)
    return clone


@operator("volume", params=("on",),
          note="squash that keeps its volume, as a constructor rather than a "
               "discipline: whatever sy says, sx becomes its reciprocal")
def volume(animation, rig, on):
    clone = copy.deepcopy(animation)
    source = clone.tracks.get(on)
    if source is None:
        return clone

    def frame(moment, base):
        pose = PartPose(*(getattr(base, name) for name in CHANNELS))
        if abs(base.sy) > 1e-6:
            pose.sx = 1.0 / base.sy
        return pose

    return _bake(clone, rig, on, frame)
