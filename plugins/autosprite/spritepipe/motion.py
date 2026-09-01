"""The animation library: what a walk cycle actually is, as a table of numbers.

Every animation in this plugin -- the seven built in below and any the user or a
model writes -- is the same thing: a set of keyframe tracks, one per rig ROLE,
sampled at N points in time. Nothing is procedural and nothing is hidden in
code, for one reason: a user who does not like how the run looks must be able to
open the animation, see `leg_near: 0 -> +42 -> -42`, change the 42, and re-render.
A run cycle expressed as a sine call inside a renderer cannot be argued with.

Tracks are keyed by role, not by part name, so an animation written once works
on every rig. A rig with no `tail` simply ignores the tail track.

Conventions, all of which are load-bearing:

- **t runs 0..1** over the animation, whatever its frame count.
- **Angles are degrees, clockwise positive**, for a character facing RIGHT.
  Screen y points down, so clockwise-positive means a positive arm angle swings
  the hand backwards and a negative one swings it forwards. A left-facing rig is
  produced by mirroring the finished frame, never by negating these numbers.
- **Translations are pixels at the reference's native resolution.** A 32px
  character bobs by 1; a 96px character bobs by 3. `scale_motion` handles that.
- **A looping animation's last frame is not its first frame.** Frame i sits at
  t = i/frames, so an 8-frame loop samples 0, 0.125 ... 0.875 and the engine's
  wrap from frame 7 back to frame 0 is exactly one more step. Sampling
  i/(frames-1) instead puts a duplicate frame in every loop, which reads as a
  stutter once per cycle and is the single most common sprite-sheet bug.
"""

import copy
import json

from .skeleton import PartPose, Pose

# Five affine scalars and one that is not a transform at all. `cycle` is a
# whole-numbered step along a part's own colour ramp -- a torch flickering, a
# gem pulsing, a window lighting up, water shimmering. It earns its place next
# to the others because it is the answer to "what does a subject with no limbs
# DO", and because it is provably palette-safe: a step lands on another shade
# of the same ramp, and every ramp comes from the source art's locked palette.
CHANNELS = ("angle", "dx", "dy", "sx", "sy", "cycle")
REST = {"angle": 0.0, "dx": 0.0, "dy": 0.0, "sx": 1.0, "sy": 1.0, "cycle": 0.0}


def smoothstep(u):
    return u * u * (3.0 - 2.0 * u)


EASINGS = {
    "linear": lambda u: u,
    "smooth": smoothstep,
    # Anticipation and impact want to arrive fast and settle, or the other way
    # round. A strike that eases in on both ends has no snap to it.
    "ease_in": lambda u: u * u,
    "ease_out": lambda u: 1.0 - (1.0 - u) ** 2,
    "hold": lambda u: 0.0,     # step: keep the previous key until the next one
}


class Lane:
    """Keyframes for ONE channel of one role, on its own timeline.

    A `Track` key carries a whole pose: `{"t": 0.3, "angle": 8, "sy": 0.92}`.
    That is compact and readable and it has one hard limit -- every channel of a
    role shares one set of instants. Overlapping action and follow-through are
    exactly the thing that limit forbids: "the hand rotates, and the squash it
    answers peaks two frames later" cannot be written, because there is one
    timeline and both values have to sit on it.

    A lane is that timeline, per channel. `sy` can have three keys at times the
    `angle` never mentions, with its own easing on each segment. It is the
    smallest change that makes secondary motion sayable, and it costs the
    existing library nothing: a track with no lanes samples exactly as before.

    Keys are `{"t": float, "v": float}` with an optional per-key `easing`,
    which -- as in `Track` -- is read from the RIGHT key of a segment, because
    an easing describes an arrival.
    """

    def __init__(self, keys, easing="smooth"):
        self.keys = sorted((dict(key) for key in keys), key=lambda key: float(key["t"]))
        if not self.keys:
            raise ValueError("a lane needs at least one keyframe")
        for key in self.keys:
            if "v" not in key:
                raise ValueError("a lane keyframe needs a value: %r" % (key,))
        self.easing = easing

    def sample(self, t, loop):
        """The channel's value at time t. Wraps for a loop, clamps for a one-shot.

        Deliberately the same shape as `Track.sample`, on a scalar instead of a
        pose, so a lane and a track agree about what a looping key list means.
        """
        keys = self.keys
        if len(keys) == 1:
            return float(keys[0]["v"])

        if loop:
            first, last = keys[0], keys[-1]
            if t < float(first["t"]):
                return self._between(last, first, t + 1.0, float(last["t"]),
                                     float(first["t"]) + 1.0)
            if t >= float(last["t"]):
                return self._between(last, first, t, float(last["t"]),
                                     float(first["t"]) + 1.0)
        else:
            if t <= float(keys[0]["t"]):
                return float(keys[0]["v"])
            if t >= float(keys[-1]["t"]):
                return float(keys[-1]["v"])

        for left, right in zip(keys, keys[1:]):
            if float(left["t"]) <= t <= float(right["t"]):
                return self._between(left, right, t, float(left["t"]), float(right["t"]))
        return float(keys[-1]["v"])

    def _between(self, left, right, t, t0, t1):
        span = t1 - t0
        raw = 0.0 if span <= 0 else (t - t0) / span
        ease = EASINGS.get(right.get("easing", self.easing), smoothstep)
        amount = ease(max(0.0, min(1.0, raw)))
        return float(left["v"]) * (1.0 - amount) + float(right["v"]) * amount

    def to_list(self):
        return [dict(key) for key in self.keys]


class Track:
    """Keyframes for one role, as a list of {"t": float, <channel>: value}."""

    def __init__(self, keys=None, easing="smooth", lanes=None, spread=0.0):
        self.keys = sorted((dict(key) for key in keys or ()),
                           key=lambda key: float(key["t"]))
        self.easing = easing
        # Per-channel timelines, which OVERRIDE the pose keys for the channels
        # they name and leave every other channel alone. Written this way round
        # on purpose: the sixteen clips in this library are pose keys and stay
        # byte-for-byte what they were, while a new clip that needs a squash to
        # lag its own rotation writes one lane and inherits the rest.
        self.lanes = {}
        for channel, keyframes in (lanes or {}).items():
            if channel not in CHANNELS:
                raise ValueError("unknown channel %r; expected one of %s"
                                 % (channel, ", ".join(CHANNELS)))
            self.lanes[channel] = (keyframes if isinstance(keyframes, Lane)
                                   else Lane(keyframes, easing))
        if not self.keys and not self.lanes:
            raise ValueError("a track needs at least one keyframe")
        if not self.keys:
            # Lane-only: every channel a lane does not name holds at rest.
            self.keys = [{"t": 0.0}]
        # When this track addresses several parts at once, how much later each
        # one in turn plays it, in normalised time. Zero is lockstep. A nonzero
        # spread is the whole mechanism behind a travelling wave: the wheat at
        # the far side of the field bends after the wheat at the near side, and
        # a chain of segments follows the one before it.
        self.spread = float(spread)

    def has(self, channel):
        """Whether this track says anything at all about one channel."""
        return channel in self.lanes or any(channel in key for key in self.keys)

    def values(self, channel):
        """Every authored value of one channel, for measuring its range.

        A pose key that omits the channel still contributes its REST value,
        because that is what sampling the track there actually returns -- the
        peak-to-peak of a bob authored on half the keys is measured against the
        zero the other half assert, not against nothing.
        """
        if channel in self.lanes:
            return [float(key["v"]) for key in self.lanes[channel].keys]
        return [float(key.get(channel, REST[channel])) for key in self.keys]

    def adjust(self, channel, function):
        """Map a function over every authored value of one channel, in place.

        Only where the channel is actually written: a key that omits it is
        asserting rest, and rest is not a number anyone edited. Returns how many
        values it touched, which is what the critic reports as its edit count.
        """
        if channel in self.lanes:
            keys = self.lanes[channel].keys
            for key in keys:
                key["v"] = function(float(key["v"]))
            return len(keys)
        touched = 0
        for key in self.keys:
            if channel in key:
                key[channel] = function(float(key[channel]))
                touched += 1
        return touched

    def foreshorten(self, swing, channel, amount, peak):
        """Damp every rotation and re-emit what it loses on another channel.

        `Animation.fronted` needs exactly this: seen head-on, a leg's swing
        across the picture becomes a lift off the floor. It lives on Track
        because the two storage forms answer it differently -- a pose key
        already carries both channels at one instant, while an angle LANE has
        instants the target channel may know nothing about, so the offset is
        derived at the angle's own times and sampled from wherever the target
        currently lives.
        """
        if "angle" not in self.lanes:
            for key in self.keys:
                angle = float(key.get("angle", 0.0))
                key["angle"] = angle * swing
                key[channel] = (float(key.get(channel, REST[channel]))
                                + amount * (angle / peak))
            return self

        lane = self.lanes["angle"]
        derived = []
        for key in lane.keys:
            moment, angle = float(key["t"]), float(key["v"])
            if channel in self.lanes:
                base = self.lanes[channel].sample(moment, True)
            else:
                base = getattr(self._pose_at(moment, True), channel)
            entry = {"t": moment, "v": base + amount * (angle / peak)}
            if "easing" in key:
                entry["easing"] = key["easing"]
            derived.append(entry)
        for key in lane.keys:
            key["v"] = float(key["v"]) * swing
        self.lanes[channel] = Lane(derived, self.easing)
        return self

    def sample(self, t, loop):
        """The PartPose at time t. Wraps for a loop, clamps for a one-shot."""
        pose = self._pose_at(t, loop)
        for channel, lane in self.lanes.items():
            setattr(pose, channel, lane.sample(t, loop))
        return pose

    def _pose_at(self, t, loop):
        keys = self.keys
        if len(keys) == 1:
            return _key_pose(keys[0])

        if loop:
            # A looping track is circular: the last key leads back to the first
            # one, a full period later. Without this the frame before the wrap
            # holds still while every other frame moves.
            first, last = keys[0], keys[-1]
            if t < float(first["t"]):
                return self._between(last, first, t + 1.0, float(last["t"]),
                                     float(first["t"]) + 1.0)
            if t >= float(last["t"]):
                return self._between(last, first, t, float(last["t"]),
                                     float(first["t"]) + 1.0)
        else:
            if t <= float(keys[0]["t"]):
                return _key_pose(keys[0])
            if t >= float(keys[-1]["t"]):
                return _key_pose(keys[-1])

        for left, right in zip(keys, keys[1:]):
            if float(left["t"]) <= t <= float(right["t"]):
                return self._between(left, right, t, float(left["t"]), float(right["t"]))
        return _key_pose(keys[-1])

    def _between(self, left, right, t, t0, t1):
        span = t1 - t0
        raw = 0.0 if span <= 0 else (t - t0) / span
        ease = EASINGS.get(right.get("easing", self.easing), smoothstep)
        amount = ease(max(0.0, min(1.0, raw)))
        return _key_pose(left).blend(_key_pose(right), amount)

    def to_list(self):
        return [dict(key) for key in self.keys]

    def to_dict(self):
        """The serialisable form. A plain list when there is nothing but pose
        keys, so every animation written before lanes existed round-trips
        unchanged."""
        if not self.lanes and not self.spread:
            return self.to_list()
        document = {"keys": self.to_list()}
        if self.lanes:
            document["lanes"] = {channel: lane.to_list()
                                 for channel, lane in self.lanes.items()}
        if self.spread:
            document["spread"] = self.spread
        return document

    @classmethod
    def of(cls, data, easing="smooth"):
        """Build from either serialised form, or pass a Track straight through."""
        if isinstance(data, cls):
            return data
        if isinstance(data, dict):
            return cls(data.get("keys"), data.get("easing", easing),
                       data.get("lanes"), data.get("spread", 0.0))
        return cls(data, easing)


def select(rig, selector):
    """The parts a track selector addresses, in the rig's own declaration order.

    Order matters: it is the order a `spread` plays them in, so a rigger who
    lists a windmill's four sails clockwise gets a wave that travels clockwise.
    """
    if selector.startswith("name:"):
        wanted = selector[len("name:"):]
        return [part for part in rig.parts if part.name == wanted]
    if selector.startswith("trait:"):
        wanted = selector[len("trait:"):]
        return [part for part in rig.parts if part.has_trait(wanted)]
    return [part for part in rig.parts if part.role == selector]


def specificity(selector):
    """Lower is more specific. One part beats one role beats a whole trait."""
    if selector.startswith("name:"):
        return 0
    if selector.startswith("trait:"):
        return 2
    return 1


def _key_pose(key):
    return PartPose(*(float(key.get(name, REST[name])) for name in CHANNELS))


class Animation:
    def __init__(self, name, frames, fps=10, loop=True, tracks=None, root=None,
                 easing="smooth", note="", flip_from=None, planted=False,
                 loop_start=None, loop_end=None):
        self.name = name
        # Whether a foot is on the floor throughout. A rigid leg rotated about
        # the hip lifts its own foot, so a clip that claims to be grounded has
        # to be corrected back down -- see `skeleton.plant`. A run has a flight
        # phase and a jump is nothing but one, so neither is grounded.
        self.planted = bool(planted)
        # Where the loop actually repeats, as frame indices, when the whole clip
        # is not the loop. A guard is raised once and then held while the button
        # is down; a game plays 0..loop_end and then jumps back to loop_start
        # rather than replaying the raise. autosprite.io carries the same two
        # fields, and Aseprite's frameTags are what most importers read them from.
        self.loop_start = None if loop_start is None else int(loop_start)
        self.loop_end = None if loop_end is None else int(loop_end)
        # A 2D spin has no back face to draw: the object squashes to nothing and
        # comes back mirrored. `flip_from` is the instant it passes edge-on.
        self.flip_from = flip_from
        self.frames = int(frames)
        self.fps = float(fps)
        self.loop = bool(loop)
        self.easing = easing
        self.note = note
        self.tracks = {role: Track.of(track, easing)
                       for role, track in (tracks or {}).items()}
        self.root = Track.of(root, easing) if root is not None else None

    def times(self):
        """Where each frame samples. See the loop note in the module docstring."""
        if self.frames <= 1:
            return [0.0]
        divisor = float(self.frames) if self.loop else float(self.frames - 1)
        return [index / divisor for index in range(self.frames)]

    def pose_at(self, rig, t):
        """Resolve every track onto the rig's actual parts.

        A track is addressed by a SELECTOR, of which a bare role name is the
        commonest and the only one the built-in library uses:

            "leg_near"        the parts with that role
            "name:sails"      one part, by name
            "trait:stalk"     every part that trails from a fixed base

        When more than one track matches a part, the most specific one is the
        base pose and the rest COMPOSE onto it -- their rotations add, their
        squashes multiply. That ordering is what makes a broad statement safe
        to write: "every stalk lags by a frame" leaves each part's own authored
        swing intact and adds the lag, rather than replacing the swing with it.
        Specificity is name, then role, then trait, and ties break on the
        selector text so the result never depends on dictionary order.
        """
        pose = Pose()
        if self.flip_from is not None:
            pose.flip = t >= float(self.flip_from)

        # Resolve each selector once, not once per part.
        matched = {selector: {part.name: index for index, part
                              in enumerate(select(rig, selector))}
                   for selector in self.tracks}
        for part in rig.parts:
            layers = []
            for selector in sorted(self.tracks):
                index = matched[selector].get(part.name)
                if index is None:
                    continue
                track = self.tracks[selector]
                layers.append((specificity(selector), selector,
                               track.sample(self._shifted(t, index, track.spread),
                                            self.loop)))
            if not layers:
                continue
            layers.sort(key=lambda layer: layer[:2])
            result = layers[0][2]
            for _, _, extra in layers[1:]:
                result = result.compose(extra)
            pose.set(part.name, result)

        if self.root is not None:
            whole = self.root.sample(t, self.loop)
            pose.dx, pose.dy = whole.dx, whole.dy
            # A root track's angle and squash belong to the root PART, so that
            # the whole character leans or squashes together. This is what makes
            # `die` a single line of keyframes instead of one per limb.
            root_part = rig.root
            if root_part is not None and (whole.angle or whole.sx != 1.0 or whole.sy != 1.0):
                # The root's own translation is the WHOLE character's and has
                # already been taken above, so only the rotation and squash
                # compose onto the root part.
                existing = pose.get(root_part.name)
                pose.set(root_part.name, existing.compose(
                    PartPose(whole.angle, 0.0, 0.0, whole.sx, whole.sy,
                             whole.cycle)))
        return pose

    def _shifted(self, t, index, spread):
        """When part `index` of a matched set plays a track that spreads.

        Each part in turn plays the same curve a little later, which is a
        travelling wave when the parts are laid out in a line and
        follow-through when they are a chain.
        """
        if not spread or not index:
            return t
        moment = t - index * spread
        return moment % 1.0 if self.loop else max(0.0, min(1.0, moment))

    def poses(self, rig):
        return [self.pose_at(rig, t) for t in self.times()]

    def drives(self, rig):
        """Whether this clip moves anything at all on this rig.

        A clip addressed at a trait the subject does not have moves nothing, and
        a clip that moves nothing renders as N copies of the rest pose. That is
        not an error -- `sway` on a coin is a reasonable thing to ask for and a
        reasonable thing to be told no about -- but shipping it as a row of
        identical frames would be a silent lie, so the build drops it and says
        which trait was missing.
        """
        if self.root is not None:
            return True
        return any(select(rig, selector) for selector in self.tracks)

    def palette_only(self):
        """Whether this clip changes shading and nothing else.

        A flicker returns to the same shade several times a cycle -- that is
        what a flicker IS -- and a ramp four shades deep cannot offer six
        different pictures however it is authored. So the "only N different
        pictures" warning, which is right about a walk, is wrong about this and
        is told so; what matters here is that no two frames RUNNING are the
        same, which is a stutter in any clip.
        """
        tracks = list(self.tracks.values()) + ([self.root] if self.root else [])
        if not tracks:
            return False
        return all(not any(track.has(channel) for channel in
                           ("angle", "dx", "dy", "sx", "sy"))
                   for track in tracks)

    def missing(self, rig):
        """The selectors this clip addresses that this rig has nothing for."""
        return sorted(selector for selector in self.tracks
                      if not select(rig, selector))

    def resampled(self, frames):
        """The same motion, drawn at a different number of frames.

        Every track here is a continuous curve sampled at `times()`, so this is
        just a different set of samples of the same movement -- not a redraw and
        not an interpolation of finished frames. The duration is held constant
        by moving fps with the frame count: asking for more frames means a
        smoother cycle, not a slower one.
        """
        frames = max(2, int(frames))
        if frames == self.frames:
            return self
        clone = copy.deepcopy(self)
        ratio = float(frames) / float(self.frames)
        clone.fps = self.fps * ratio
        # The loop points name frames, so they have to move with the count or a
        # sixteen-frame version of a four-frame clip loops the wrong quarter.
        for field in ("loop_start", "loop_end"):
            value = getattr(clone, field)
            if value is not None:
                setattr(clone, field, max(0, min(frames - 1, int(round(value * ratio)))))
        clone.frames = frames
        return clone

    def scaled(self, factor):
        """Scale every translation for a character of a different size.

        Angles and squashes are size-independent; pixel offsets are not. A bob
        of 1px on a 32px sprite is 3px on a 96px one, and skipping this is why
        an animation authored on a small character looks frozen on a large one.
        """
        if abs(factor - 1.0) < 1e-6:
            return self
        clone = copy.deepcopy(self)
        for track in list(clone.tracks.values()) + ([clone.root] if clone.root else []):
            for channel in ("dx", "dy"):
                track.adjust(channel, lambda value: value * factor)
        return clone

    def fronted(self, swing=0.3, reach=1.0, lift=1.5):
        """Rewrite a side-on clip for a character drawn face-on.

        Seen from the front, a leg swinging forward is pointing at the camera.
        It foreshortens to almost nothing, and what a viewer actually reads is
        the foot leaving the ground. A rig built for a profile swings it 26
        degrees across the picture instead, which is why a top-down RPG sprite
        animated with a side-on walk looks like it is doing the splits -- the
        complaint two of the corpus's top-down assets drew from the critic,
        both of which measure zero debris and so are invisible to every other
        check here.

        The phase is what makes a walk read as a walk, so the phase is kept and
        only what it DRIVES changes: the swing is damped to a fraction of
        itself, and the part that is lost comes back as motion the camera can
        see. A leg's swing becomes a lift, so the feet alternate off the floor;
        an arm's becomes a sideways reach, so the arms open and close. Both
        follow the sign of the original angle, so limbs that were in
        counter-phase stay in counter-phase without this needing to know which
        side of the body each one is on.

        Nothing else is touched. The root bob, the torso lean, the squashes and
        the frame timing all read the same from any angle.
        """
        clone = copy.deepcopy(self)
        for role, track in clone.tracks.items():
            if not (role.startswith("arm_") or role.startswith("leg_")):
                continue
            peak = max((abs(value) for value in track.values("angle")), default=0.0)
            if peak <= 0.0:
                continue
            channel, amount = (("dy", -float(lift)) if role.startswith("leg_")
                               else ("dx", float(reach)))
            track.foreshorten(float(swing), channel, amount, peak)
        return clone

    def floored(self, min_sx=0.0, min_sy=0.0):
        """Stop a squash from thinning the sprite below one drawable pixel.

        A coin's spin squashes to a sliver at the quarter points, and a sliver
        is the whole trick. But the sliver has to be at least a couple of pixels
        wide: below that, nearest-neighbour sampling keeps some columns and
        drops others, and a 16px potion does not become a thin potion, it
        becomes a scatter of loose pixels.

        Expressed as a floor on the SCALE rather than a redesign of the
        animation, so the keyframes stay readable and a big sprite still gets
        the full squash it was authored with.
        """
        if min_sx <= 0.0 and min_sy <= 0.0:
            return self
        clone = copy.deepcopy(self)
        tracks = list(clone.tracks.values()) + ([clone.root] if clone.root else [])
        for track in tracks:
            for channel, minimum in (("sx", min_sx), ("sy", min_sy)):
                track.adjust(channel, lambda value, floor=minimum:
                             max(value, floor) if value >= 0 else value)
        return clone

    def floored_travel(self, min_pixels=1.0, limbs=False):
        """Stop a scaled-down translation from rounding away to nothing.

        `scaled` multiplies every pixel offset by the character's height over
        the height the library was authored at, which is right, and on a small
        sprite it is fatal: a walk's one-pixel body bob becomes half a pixel on
        a 16px sprite, the renderer cannot draw half a pixel, and the character
        slides along the floor instead of walking. Measured on the corpus's
        16px roguelike, the bob was exactly **zero pixels across all eight
        frames** -- a keyframe authored, scaled, and then silently discarded.

        A squash has the same problem and takes a floor (`floored`); so does a
        translation. Scale the channel up until its peak-to-peak reaches one
        drawable pixel, rather than dropping it: an exaggerated bob is what a
        pixel artist draws on a 16px character anyway.
        """
        if min_pixels <= 0.0:
            return self
        clone = copy.deepcopy(self)
        tracks = ([clone.root] if clone.root else [])
        if limbs:
            tracks += list(clone.tracks.values())
        for track in tracks:
            for channel in ("dx", "dy"):
                values = track.values(channel)
                span = max(values) - min(values)
                if span <= 0.0 or span >= min_pixels:
                    continue
                factor = min_pixels / span
                track.adjust(channel, lambda value, gain=factor: value * gain)
        return clone

    def to_dict(self):
        return {"name": self.name, "frames": self.frames, "fps": self.fps,
                "loop": self.loop, "easing": self.easing, "note": self.note,
                "flip_from": self.flip_from, "planted": self.planted,
                "loop_start": self.loop_start, "loop_end": self.loop_end,
                "root": self.root.to_dict() if self.root else None,
                "tracks": {role: track.to_dict() for role, track in self.tracks.items()}}

    @classmethod
    def from_dict(cls, data):
        return cls(data["name"], data["frames"], data.get("fps", 10),
                   data.get("loop", True), data.get("tracks"), data.get("root"),
                   data.get("easing", "smooth"), data.get("note", ""),
                   data.get("flip_from"), data.get("planted", False),
                   data.get("loop_start"), data.get("loop_end"))


def validate_animation(data):
    """Problems with an animation dictionary, as a list. Empty means usable.

    This runs on anything a model or a user hands us. The failures it catches
    are the ones that would otherwise render a whole sheet of identical frames
    and waste the user's time working out why.
    """
    problems = []
    if not isinstance(data, dict):
        return ["an animation must be a JSON object"]
    if not data.get("name"):
        problems.append("no name")
    frames = data.get("frames")
    if not isinstance(frames, int) or frames < 1:
        problems.append("frames must be an integer >= 1, got %r" % (frames,))
    elif frames > 64:
        problems.append("frames = %d; a sprite animation above 64 frames is "
                        "almost always a mistake" % frames)
    else:
        for field in ("loop_start", "loop_end"):
            value = data.get(field)
            if value is None:
                continue
            if not isinstance(value, int) or not 0 <= value < frames:
                problems.append("%s = %r; it names a frame, so it must be an "
                                "integer from 0 to %d" % (field, value, frames - 1))
        start, end = data.get("loop_start"), data.get("loop_end")
        if (isinstance(start, int) and isinstance(end, int) and end < start):
            problems.append("loop_end (%d) is before loop_start (%d)" % (end, start))
    fps = data.get("fps", 10)
    if not isinstance(fps, (int, float)) or not 0 < fps <= 120:
        problems.append("fps must be between 0 and 120, got %r" % (fps,))

    tracks = data.get("tracks") or {}
    if not tracks and not data.get("root"):
        problems.append("no tracks and no root track: every frame would be identical")

    from .rig import ROLES, TRAITS
    for selector, track in tracks.items():
        if selector.startswith("name:"):
            if not selector[len("name:"):]:
                problems.append("track 'name:' names no part")
        elif selector.startswith("trait:"):
            trait = selector[len("trait:"):]
            if trait not in TRAITS:
                problems.append("track %r is not a trait (%s)"
                                % (selector, ", ".join(TRAITS)))
        elif selector not in ROLES:
            problems.append("track %r is not a rig role (%s) and is not a "
                            "'name:' or 'trait:' selector"
                            % (selector, ", ".join(ROLES)))
        problems.extend(_track_problems("track %r" % selector, track))
    if data.get("root") is not None:
        problems.extend(_track_problems("the root track", data["root"]))
    return problems


def _track_problems(label, track):
    """Both serialised forms of a track: a bare key list, or keys plus lanes."""
    problems = []
    lanes, spread = {}, 0.0
    if isinstance(track, dict):
        lanes = track.get("lanes") or {}
        spread = track.get("spread", 0.0)
        if not isinstance(lanes, dict):
            return ["%s has lanes that are not an object" % label]
        track = track.get("keys") or []
        if not track and not lanes:
            return ["%s has no keyframes" % label]
    elif not isinstance(track, list) or not track:
        return ["%s has no keyframes" % label]

    if isinstance(spread, (int, float)) and not 0.0 <= float(spread) < 1.0:
        problems.append("%s has spread=%r; it is a fraction of the cycle, so it "
                        "must be at least 0 and less than 1" % (label, spread))
    elif not isinstance(spread, (int, float)):
        problems.append("%s has spread=%r, which is not a number" % (label, spread))

    for key in track:
        if not isinstance(key, dict) or "t" not in key:
            problems.append("%s has a keyframe with no t: %r" % (label, key))
            continue
        if not 0.0 <= float(key["t"]) <= 1.0:
            problems.append("%s has t=%s outside 0..1" % (label, key["t"]))
        unknown = set(key) - set(CHANNELS) - {"t", "easing"}
        if unknown:
            problems.append("%s has unknown channels %s"
                            % (label, ", ".join(sorted(unknown))))

    for channel, keys in lanes.items():
        if channel not in CHANNELS:
            problems.append("%s has a lane for %r, which is not a channel (%s)"
                            % (label, channel, ", ".join(CHANNELS)))
        if not isinstance(keys, list) or not keys:
            problems.append("%s has an empty %s lane" % (label, channel))
            continue
        for key in keys:
            if not isinstance(key, dict) or "t" not in key or "v" not in key:
                problems.append("%s has a %s lane keyframe that is not "
                                "{t, v}: %r" % (label, channel, key))
                continue
            if not 0.0 <= float(key["t"]) <= 1.0:
                problems.append("%s has a %s lane key at t=%s outside 0..1"
                                % (label, channel, key["t"]))
    return problems


# --------------------------------------------------------------------------
# the built-in library
#
# Numbers here are tuned for a right-facing humanoid around 32px tall and are
# scaled to the actual character by `scaled()`. They are deliberately readable:
# a walk is legs in counter-phase, arms opposing the legs, and two bobs per
# cycle, and that is exactly what the table says.
# --------------------------------------------------------------------------

def _swing(low, high, phase=0.0):
    """A limb swinging between two angles over one cycle, offset by `phase`."""
    points = [(0.0, low), (0.5, high), (1.0, low)]
    shifted = []
    for t, angle in points:
        moved = (t + phase) % 1.0
        shifted.append({"t": round(moved, 4), "angle": angle})
    shifted.sort(key=lambda key: key["t"])
    # Re-close the cycle: whatever key now sits lowest must reappear at t=1 or
    # the wrap interpolates between the wrong pair.
    if shifted[0]["t"] > 0.0:
        shifted.insert(0, {"t": 0.0, "angle": _lerp_cycle(points, phase, 0.0)})
    return shifted


def _lerp_cycle(points, phase, t):
    target = (t - phase) % 1.0
    for (t0, a0), (t1, a1) in zip(points, points[1:]):
        if t0 <= target <= t1:
            amount = 0.0 if t1 == t0 else (target - t0) / (t1 - t0)
            return round(a0 + (a1 - a0) * smoothstep(amount), 3)
    return points[0][1]


def _library():
    idle = Animation(
        "idle", frames=4, fps=6, loop=True,
        note="breathing; the frame a player sees more than any other. The breath "
             "peaks off-centre because breathing is quick in and slow out -- and "
             "because a peak exactly halfway makes the two off-beats the same "
             "picture, which on a small character is half the cycle wasted",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.4, "dy": 1.0}, {"t": 1.0, "dy": 0.0}],
        tracks={
            "head": [{"t": 0.0, "dy": 0.0}, {"t": 0.55, "dy": 1.0}, {"t": 1.0, "dy": 0.0}],
            "arm_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.4, "angle": 3.0},
                         {"t": 1.0, "angle": 0.0}],
            "arm_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.4, "angle": -3.0},
                        {"t": 1.0, "angle": 0.0}],
            "tail": [{"t": 0.0, "angle": -4.0}, {"t": 0.4, "angle": 4.0},
                     {"t": 1.0, "angle": -4.0}],
            "wing_near": [{"t": 0.0, "angle": -3.0}, {"t": 0.4, "angle": 3.0},
                          {"t": 1.0, "angle": -3.0}],
            "wing_far": [{"t": 0.0, "angle": -3.0}, {"t": 0.4, "angle": 3.0},
                         {"t": 1.0, "angle": -3.0}],
        })

    # The passing poses are what make this a CYCLE rather than a pendulum. A
    # plain out-and-back swing -- one key at each end and one in the middle --
    # is symmetric in time, so frame k and frame N-k are the same picture and an
    # eight-frame walk is really five: measured on a corpus character, the old
    # version drew 5 distinct images and repeated three of them. The character
    # rocks instead of walking, and asking for more frames only adds more
    # repeats.
    #
    # What breaks the symmetry is the knee. At each passing pose one leg is
    # planted and straight while the other is lifted and bent, and which is
    # which swaps between the two halves of the cycle. That is also what a walk
    # actually looks like.
    walk = Animation(
        "walk", frames=8, fps=10, loop=True,
        note="legs in counter-phase, arms opposing them, a bent knee on whichever "
             "leg is passing, and no authored bob: the feet are planted, so the "
             "body's rise and fall comes out of the leg geometry itself and "
             "scales to the character",
        planted=True,
        tracks={
            "leg_near": [{"t": 0.0, "angle": 26.0, "sy": 1.0},
                         {"t": 0.25, "angle": 0.0, "sy": 1.0},     # planted
                         {"t": 0.5, "angle": -26.0, "sy": 1.0},
                         {"t": 0.75, "angle": 0.0, "sy": 0.86},    # lifted, bent
                         {"t": 1.0, "angle": 26.0, "sy": 1.0}],
            "leg_far": [{"t": 0.0, "angle": -26.0, "sy": 1.0},
                        {"t": 0.25, "angle": 0.0, "sy": 0.86},     # lifted, bent
                        {"t": 0.5, "angle": 26.0, "sy": 1.0},
                        {"t": 0.75, "angle": 0.0, "sy": 1.0},      # planted
                        {"t": 1.0, "angle": -26.0, "sy": 1.0}],
            "arm_near": [{"t": 0.0, "angle": -18.0}, {"t": 0.25, "angle": -3.0},
                         {"t": 0.5, "angle": 18.0}, {"t": 0.75, "angle": 3.0},
                         {"t": 1.0, "angle": -18.0}],
            "arm_far": [{"t": 0.0, "angle": 18.0}, {"t": 0.25, "angle": 3.0},
                        {"t": 0.5, "angle": -18.0}, {"t": 0.75, "angle": -3.0},
                        {"t": 1.0, "angle": 18.0}],
            "torso": [{"t": 0.0, "angle": -2.0}, {"t": 0.5, "angle": 2.0},
                      {"t": 1.0, "angle": -2.0}],
            "tail": _swing(-8.0, 8.0, phase=0.15),
            "wing_near": [{"t": 0.0, "angle": -6.0}, {"t": 0.5, "angle": 6.0},
                          {"t": 1.0, "angle": -6.0}],
            "wing_far": [{"t": 0.0, "angle": -6.0}, {"t": 0.5, "angle": 6.0},
                         {"t": 1.0, "angle": -6.0}],
        })

    run = Animation(
        "run", frames=8, fps=14, loop=True,
        note="walk with the amplitudes opened up, a forward lean, and the trailing "
             "leg squashed at the lift so it reads as a bent knee",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.25, "dy": -2.0}, {"t": 0.5, "dy": 0.0},
              {"t": 0.75, "dy": -2.0}, {"t": 1.0, "dy": 0.0}],
        tracks={
            "leg_near": [{"t": 0.0, "angle": 42.0, "sy": 1.0},
                         {"t": 0.25, "angle": 10.0, "sy": 0.86},
                         {"t": 0.5, "angle": -40.0, "sy": 1.0},
                         {"t": 0.75, "angle": 5.0, "sy": 0.9},
                         {"t": 1.0, "angle": 42.0, "sy": 1.0}],
            "leg_far": [{"t": 0.0, "angle": -40.0, "sy": 1.0},
                        {"t": 0.25, "angle": 5.0, "sy": 0.9},
                        {"t": 0.5, "angle": 42.0, "sy": 1.0},
                        {"t": 0.75, "angle": 10.0, "sy": 0.86},
                        {"t": 1.0, "angle": -40.0, "sy": 1.0}],
            "arm_near": _swing(-38.0, 34.0),
            "arm_far": _swing(34.0, -38.0),
            "torso": [{"t": 0.0, "angle": 7.0}, {"t": 0.5, "angle": 9.0},
                      {"t": 1.0, "angle": 7.0}],
            "head": [{"t": 0.0, "angle": -5.0}, {"t": 1.0, "angle": -5.0}],
            "tail": _swing(-16.0, 16.0, phase=0.15),
            "wing_near": [{"t": 0.0, "angle": -14.0}, {"t": 0.5, "angle": 14.0},
                          {"t": 1.0, "angle": -14.0}],
            "wing_far": [{"t": 0.0, "angle": -14.0}, {"t": 0.5, "angle": 14.0},
                         {"t": 1.0, "angle": -14.0}],
        })

    jump = Animation(
        "jump", frames=6, fps=12, loop=False,
        note="crouch, launch, apex, fall, land -- the anticipation frame is what "
             "sells it, so it gets its own key",
        root=[{"t": 0.0, "dy": 2.0}, {"t": 0.2, "dy": -1.0, "easing": "ease_in"},
              {"t": 0.45, "dy": -7.0}, {"t": 0.7, "dy": -8.0},
              {"t": 0.85, "dy": -3.0, "easing": "ease_in"}, {"t": 1.0, "dy": 2.0}],
        tracks={
            "leg_near": [{"t": 0.0, "angle": 8.0, "sy": 0.78}, {"t": 0.2, "angle": 0.0, "sy": 1.05},
                         {"t": 0.45, "angle": -14.0, "sy": 1.0}, {"t": 0.7, "angle": 22.0, "sy": 0.85},
                         {"t": 0.85, "angle": -16.0, "sy": 1.0}, {"t": 1.0, "angle": 6.0, "sy": 0.8}],
            "leg_far": [{"t": 0.0, "angle": -8.0, "sy": 0.78}, {"t": 0.2, "angle": 0.0, "sy": 1.05},
                        {"t": 0.45, "angle": 14.0, "sy": 1.0}, {"t": 0.7, "angle": -20.0, "sy": 0.85},
                        {"t": 0.85, "angle": 16.0, "sy": 1.0}, {"t": 1.0, "angle": -6.0, "sy": 0.8}],
            "arm_near": [{"t": 0.0, "angle": 28.0}, {"t": 0.2, "angle": -55.0},
                         {"t": 0.45, "angle": -78.0}, {"t": 0.7, "angle": -70.0},
                         {"t": 0.85, "angle": -35.0}, {"t": 1.0, "angle": 18.0}],
            "arm_far": [{"t": 0.0, "angle": 24.0}, {"t": 0.2, "angle": -48.0},
                        {"t": 0.45, "angle": -72.0}, {"t": 0.7, "angle": -64.0},
                        {"t": 0.85, "angle": -30.0}, {"t": 1.0, "angle": 14.0}],
            "torso": [{"t": 0.0, "angle": 10.0}, {"t": 0.2, "angle": -4.0},
                      {"t": 0.7, "angle": 2.0}, {"t": 1.0, "angle": 12.0}],
            "wing_near": [{"t": 0.0, "angle": 24.0}, {"t": 0.2, "angle": -34.0},
                          {"t": 0.7, "angle": 30.0}, {"t": 1.0, "angle": 10.0}],
            "wing_far": [{"t": 0.0, "angle": 24.0}, {"t": 0.2, "angle": -34.0},
                         {"t": 0.7, "angle": 30.0}, {"t": 1.0, "angle": 10.0}],
        })

    attack = Animation(
        "attack", frames=6, fps=14, loop=False, planted=True,
        note="wind up away from the target, strike through it, follow through; the "
             "contact frame is held one extra beat because that is where the hit lands",
        root=[{"t": 0.0, "dx": 0.0}, {"t": 0.2, "dx": -2.0}, {"t": 0.45, "dx": 3.0,
              "easing": "ease_in"}, {"t": 0.6, "dx": 3.0}, {"t": 1.0, "dx": 0.0}],
        tracks={
            "arm_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.2, "angle": 58.0},
                         {"t": 0.45, "angle": -78.0, "easing": "ease_in"},
                         {"t": 0.6, "angle": -86.0}, {"t": 0.8, "angle": -38.0},
                         {"t": 1.0, "angle": 0.0}],
            "arm_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.2, "angle": -20.0},
                        {"t": 0.45, "angle": 30.0}, {"t": 0.6, "angle": 34.0},
                        {"t": 1.0, "angle": 0.0}],
            "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.2, "angle": -8.0},
                      {"t": 0.45, "angle": 10.0}, {"t": 0.6, "angle": 11.0},
                      {"t": 1.0, "angle": 0.0}],
            "head": [{"t": 0.0, "angle": 0.0}, {"t": 0.2, "angle": -4.0},
                     {"t": 0.5, "angle": 6.0}, {"t": 1.0, "angle": 0.0}],
            "leg_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.2, "angle": -10.0},
                         {"t": 0.45, "angle": 18.0}, {"t": 1.0, "angle": 0.0}],
            "leg_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.2, "angle": 10.0},
                        {"t": 0.45, "angle": -14.0}, {"t": 1.0, "angle": 0.0}],
        })

    hurt = Animation(
        "hurt", frames=4, fps=12, loop=False, planted=True,
        note="knocked back and off balance, then recovering",
        root=[{"t": 0.0, "dx": 0.0}, {"t": 0.35, "dx": -3.0, "easing": "ease_in"},
              {"t": 1.0, "dx": 0.0}],
        tracks={
            "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.35, "angle": -14.0},
                      {"t": 1.0, "angle": 0.0}],
            "head": [{"t": 0.0, "angle": 0.0}, {"t": 0.35, "angle": -12.0},
                     {"t": 1.0, "angle": 0.0}],
            "arm_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.35, "angle": 36.0},
                         {"t": 1.0, "angle": 0.0}],
            "arm_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.35, "angle": 30.0},
                        {"t": 1.0, "angle": 0.0}],
        })

    die = Animation(
        "die", frames=8, fps=10, loop=False,
        note="the root carries the fall, so every part goes down together; only the "
             "limbs that splay get their own track",
        root=[{"t": 0.0, "angle": 0.0, "dy": 0.0}, {"t": 0.2, "angle": -10.0, "dy": -1.0},
              {"t": 0.55, "angle": -48.0, "dy": 3.0, "easing": "ease_in"},
              {"t": 0.8, "angle": -80.0, "dy": 7.0},
              {"t": 1.0, "angle": -88.0, "dy": 8.0}],
        tracks={
            "arm_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": -30.0},
                         {"t": 1.0, "angle": -14.0}],
            "arm_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": 26.0},
                        {"t": 1.0, "angle": 20.0}],
            "leg_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.6, "angle": 20.0},
                         {"t": 1.0, "angle": 12.0}],
            "leg_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.6, "angle": -16.0},
                        {"t": 1.0, "angle": -10.0}],
            "head": [{"t": 0.0, "angle": 0.0}, {"t": 1.0, "angle": 14.0}],
            "wing_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": -26.0},
                          {"t": 1.0, "angle": 18.0}],
            "wing_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": 26.0},
                         {"t": 1.0, "angle": 22.0}],
        })

    crouch = Animation(
        "crouch", frames=4, fps=6, loop=True, planted=True,
        note="held low, breathing. The sink is in the LEGS folding, not in a "
             "root translation: a rigid leg shortened to 62% takes the hip down "
             "with it, and because the feet are planted the body follows. "
             "Authoring it in the root instead lifted the feet off the floor and "
             "made the clip impossible to plant. The breath peaks off-centre "
             "because breathing is quick in and slow out -- and because a peak "
             "exactly halfway makes the two off-beats the same picture",
        tracks={
            "leg_near": [{"t": 0.0, "angle": 10.0, "sy": 0.80},
                         {"t": 0.4, "angle": 12.0, "sy": 0.45},
                         {"t": 1.0, "angle": 10.0, "sy": 0.80}],
            "leg_far": [{"t": 0.0, "angle": -8.0, "sy": 0.82},
                        {"t": 0.4, "angle": -10.0, "sy": 0.47},
                        {"t": 1.0, "angle": -8.0, "sy": 0.82}],
            "torso": [{"t": 0.0, "angle": 12.0}, {"t": 0.4, "angle": 17.0},
                      {"t": 1.0, "angle": 12.0}],
            "head": [{"t": 0.0, "angle": -8.0}, {"t": 1.0, "angle": -8.0}],
            "arm_near": [{"t": 0.0, "angle": 22.0}, {"t": 1.0, "angle": 22.0}],
            "arm_far": [{"t": 0.0, "angle": 18.0}, {"t": 1.0, "angle": 18.0}],
        })

    land = Animation(
        "land", frames=5, fps=14, loop=False,
        note="the impact frame is the whole animation: one frame of deep squash "
             "with the arms still up from the fall, then two of recovery",
        root=[{"t": 0.0, "dy": -3.0}, {"t": 0.25, "dy": 4.0, "easing": "ease_in"},
              {"t": 0.55, "dy": 2.0}, {"t": 1.0, "dy": 0.0}],
        tracks={
            "leg_near": [{"t": 0.0, "angle": -6.0, "sy": 1.05},
                         {"t": 0.25, "angle": 14.0, "sy": 0.58},
                         {"t": 0.55, "angle": 6.0, "sy": 0.82},
                         {"t": 1.0, "angle": 0.0, "sy": 1.0}],
            "leg_far": [{"t": 0.0, "angle": 6.0, "sy": 1.05},
                        {"t": 0.25, "angle": -12.0, "sy": 0.60},
                        {"t": 0.55, "angle": -5.0, "sy": 0.84},
                        {"t": 1.0, "angle": 0.0, "sy": 1.0}],
            "arm_near": [{"t": 0.0, "angle": -46.0}, {"t": 0.25, "angle": -20.0},
                         {"t": 1.0, "angle": 0.0}],
            "arm_far": [{"t": 0.0, "angle": 40.0}, {"t": 0.25, "angle": 18.0},
                        {"t": 1.0, "angle": 0.0}],
            "torso": [{"t": 0.0, "angle": -4.0}, {"t": 0.25, "angle": 16.0},
                      {"t": 0.55, "angle": 6.0}, {"t": 1.0, "angle": 0.0}],
            "head": [{"t": 0.25, "angle": 10.0}, {"t": 1.0, "angle": 0.0}],
        })

    dash = Animation(
        "dash", frames=6, fps=16, loop=True,
        note="a run with the lean doubled and the stride shortened -- speed reads "
             "as commitment forward, not as a wider gait",
        root=[{"t": 0.0, "dy": -1.0}, {"t": 0.33, "dy": -2.0},
              {"t": 0.66, "dy": -1.0}, {"t": 1.0, "dy": -1.0}],
        tracks={
            "leg_near": [{"t": 0.0, "angle": 34.0, "sy": 1.0},
                         {"t": 0.25, "angle": 4.0, "sy": 0.78},
                         {"t": 0.5, "angle": -30.0, "sy": 1.0},
                         {"t": 0.75, "angle": 8.0, "sy": 0.92},
                         {"t": 1.0, "angle": 34.0, "sy": 1.0}],
            "leg_far": [{"t": 0.0, "angle": -30.0, "sy": 1.0},
                        {"t": 0.25, "angle": 8.0, "sy": 0.92},
                        {"t": 0.5, "angle": 34.0, "sy": 1.0},
                        {"t": 0.75, "angle": 4.0, "sy": 0.78},
                        {"t": 1.0, "angle": -30.0, "sy": 1.0}],
            "arm_near": [{"t": 0.0, "angle": -44.0}, {"t": 0.25, "angle": -8.0},
                         {"t": 0.5, "angle": 30.0}, {"t": 0.75, "angle": -4.0},
                         {"t": 1.0, "angle": -44.0}],
            "arm_far": [{"t": 0.0, "angle": 30.0}, {"t": 0.25, "angle": -4.0},
                        {"t": 0.5, "angle": -44.0}, {"t": 0.75, "angle": -8.0},
                        {"t": 1.0, "angle": 30.0}],
            "torso": [{"t": 0.0, "angle": 16.0}, {"t": 0.5, "angle": 19.0},
                      {"t": 1.0, "angle": 16.0}],
            "head": [{"t": 0.0, "angle": -12.0}, {"t": 1.0, "angle": -12.0}],
            "tail": _swing(-22.0, 22.0, phase=0.15),
        })

    climb = Animation(
        "climb", frames=8, fps=8, loop=True,
        note="hand over hand: the arms alternate reaching up, the legs follow "
             "half a beat behind, and the body rises once per full reach. A "
             "profile drawing has no front view to turn towards a wall, so this "
             "reads as reaching rather than as gripping -- say so to the user",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.25, "dy": -1.0}, {"t": 0.5, "dy": 0.0},
              {"t": 0.75, "dy": -1.0}, {"t": 1.0, "dy": 0.0}],
        tracks={
            # 46 degrees, not the 58 this was first written with. Measured over
            # the corpus, 58 threw a hand clear of the body on a 45px character
            # and took the clip to 9.4% shed; 46 takes it to 0.8% and costs one
            # point of frame-to-frame change. A profile drawing has a narrow
            # silhouette to keep an arm inside.
            "arm_near": [{"t": 0.0, "angle": -46.0, "sy": 1.0},
                         {"t": 0.25, "angle": -16.0, "sy": 0.9},
                         {"t": 0.5, "angle": 5.0, "sy": 1.0},
                         {"t": 0.75, "angle": -21.0, "sy": 1.0},
                         {"t": 1.0, "angle": -46.0, "sy": 1.0}],
            "arm_far": [{"t": 0.0, "angle": 5.0, "sy": 1.0},
                        {"t": 0.25, "angle": -21.0, "sy": 1.0},
                        {"t": 0.5, "angle": -46.0, "sy": 1.0},
                        {"t": 0.75, "angle": -16.0, "sy": 0.9},
                        {"t": 1.0, "angle": 5.0, "sy": 1.0}],
            "leg_near": [{"t": 0.0, "angle": 8.0, "sy": 1.0},
                         {"t": 0.25, "angle": 20.0, "sy": 0.84},
                         {"t": 0.5, "angle": -12.0, "sy": 1.0},
                         {"t": 0.75, "angle": 2.0, "sy": 1.0},
                         {"t": 1.0, "angle": 8.0, "sy": 1.0}],
            "leg_far": [{"t": 0.0, "angle": -12.0, "sy": 1.0},
                        {"t": 0.25, "angle": 2.0, "sy": 1.0},
                        {"t": 0.5, "angle": 8.0, "sy": 1.0},
                        {"t": 0.75, "angle": 20.0, "sy": 0.84},
                        {"t": 1.0, "angle": -12.0, "sy": 1.0}],
            "torso": [{"t": 0.0, "angle": -3.0}, {"t": 0.5, "angle": 3.0},
                      {"t": 1.0, "angle": -3.0}],
        })

    block = Animation(
        "block", frames=4, fps=12, loop=True, loop_start=2, planted=True,
        note="up fast, then held: the guard frame is the one a player sees, so "
             "it arrives on frame two and the loop repeats from there. A game "
             "plays the raise once and holds the guard while the button is down. "
             "The brace is in the legs bending rather than the root dropping, so "
             "the feet stay on the floor",
        tracks={
            "arm_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.33, "angle": -72.0},
                         {"t": 0.66, "angle": -58.0}, {"t": 1.0, "angle": -60.0}],
            "arm_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.33, "angle": -48.0},
                        {"t": 0.66, "angle": -42.0}, {"t": 1.0, "angle": -44.0}],
            "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.33, "angle": -12.0},
                      {"t": 0.66, "angle": -6.0}, {"t": 1.0, "angle": -7.0}],
            "head": [{"t": 0.0, "angle": 0.0}, {"t": 0.33, "angle": 6.0},
                     {"t": 1.0, "angle": 6.0}],
            "leg_near": [{"t": 0.0, "angle": 0.0, "sy": 1.0},
                         {"t": 0.33, "angle": 8.0, "sy": 0.66},
                         {"t": 0.66, "angle": 7.0, "sy": 0.78},
                         {"t": 1.0, "angle": 7.0, "sy": 0.76}],
            "leg_far": [{"t": 0.0, "angle": 0.0, "sy": 1.0},
                        {"t": 0.33, "angle": -10.0, "sy": 0.68},
                        {"t": 0.66, "angle": -9.0, "sy": 0.80},
                        {"t": 1.0, "angle": -9.0, "sy": 0.78}],
        })

    cast = Animation(
        "cast", frames=7, fps=12, loop=False, planted=True,
        note="gather, hold, release: the hold is what makes it read as a spell "
             "rather than a swipe, so it gets two frames of its own",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.3, "dy": 1.0}, {"t": 0.55, "dy": -1.0},
              {"t": 0.75, "dy": -1.0}, {"t": 1.0, "dy": 0.0}],
        tracks={
            "arm_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": 40.0},
                         {"t": 0.55, "angle": -70.0, "easing": "ease_in"},
                         {"t": 0.75, "angle": -76.0}, {"t": 1.0, "angle": -10.0}],
            "arm_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": 30.0},
                        {"t": 0.55, "angle": -52.0}, {"t": 0.75, "angle": -58.0},
                        {"t": 1.0, "angle": -6.0}],
            "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": 10.0},
                      {"t": 0.55, "angle": -12.0}, {"t": 0.75, "angle": -10.0},
                      {"t": 1.0, "angle": 0.0}],
            "head": [{"t": 0.3, "angle": 8.0}, {"t": 0.55, "angle": -8.0},
                     {"t": 1.0, "angle": 0.0}],
            "leg_near": [{"t": 0.3, "angle": 8.0, "sy": 0.92}, {"t": 0.55, "angle": -6.0},
                         {"t": 1.0, "angle": 0.0}],
            "leg_far": [{"t": 0.3, "angle": -6.0, "sy": 0.94}, {"t": 0.55, "angle": 8.0},
                        {"t": 1.0, "angle": 0.0}],
        })

    throw = Animation(
        "throw", frames=6, fps=14, loop=False, planted=True,
        note="the arm goes back further than it comes forward, and the body "
             "steps into it -- an overarm throw is a whole-body move",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.3, "dy": 1.0}, {"t": 0.5, "dy": -1.0},
              {"t": 1.0, "dy": 0.0}],
        tracks={
            "arm_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": 78.0},
                         {"t": 0.5, "angle": -62.0, "easing": "ease_in"},
                         {"t": 0.7, "angle": -40.0}, {"t": 1.0, "angle": -8.0}],
            "arm_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": -34.0},
                        {"t": 0.5, "angle": 30.0}, {"t": 1.0, "angle": 4.0}],
            "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.3, "angle": -14.0},
                      {"t": 0.5, "angle": 16.0}, {"t": 1.0, "angle": 4.0}],
            "head": [{"t": 0.3, "angle": -6.0}, {"t": 0.5, "angle": 8.0},
                     {"t": 1.0, "angle": 0.0}],
            "leg_near": [{"t": 0.3, "angle": -12.0}, {"t": 0.5, "angle": 22.0},
                         {"t": 1.0, "angle": 6.0}],
            "leg_far": [{"t": 0.3, "angle": 14.0}, {"t": 0.5, "angle": -18.0},
                        {"t": 1.0, "angle": -4.0}],
        })

    sleep = Animation(
        "sleep", frames=4, fps=3, loop=True,
        note="lying down and breathing slowly. The root carries the whole "
             "character over, as `die` does, because a standing profile drawing "
             "cannot be folded into a lying pose any other way -- and a slumped "
             "upright figure reads as standing still, not as sleeping",
        root=[{"t": 0.0, "angle": -78.0, "dy": 6.0},
              {"t": 0.4, "angle": -80.0, "dy": 7.0},
              {"t": 1.0, "angle": -78.0, "dy": 6.0}],
        tracks={
            "head": [{"t": 0.0, "angle": 12.0}, {"t": 0.4, "angle": 15.0},
                     {"t": 1.0, "angle": 12.0}],
            "torso": [{"t": 0.0, "angle": 4.0, "sy": 0.97},
                      {"t": 0.4, "angle": 6.0, "sy": 1.0},
                      {"t": 1.0, "angle": 4.0, "sy": 0.97}],
            "arm_near": [{"t": 0.0, "angle": -18.0}, {"t": 1.0, "angle": -18.0}],
            "arm_far": [{"t": 0.0, "angle": 14.0}, {"t": 1.0, "angle": 14.0}],
            "leg_near": [{"t": 0.0, "angle": 14.0}, {"t": 1.0, "angle": 14.0}],
            "leg_far": [{"t": 0.0, "angle": -10.0}, {"t": 1.0, "angle": -10.0}],
        })

    fly = Animation(
        "fly", frames=6, fps=12, loop=True,
        note="a wing beat, and the body riding it. The wings lead and the body "
             "follows a beat behind -- lift arrives after the downstroke, not "
             "during it -- which is the whole difference between a bird flying "
             "and a bird flapping. Legs tuck and trail",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.35, "dy": -3.0},
              {"t": 0.7, "dy": 1.0}, {"t": 1.0, "dy": 0.0}],
        tracks={
            "wing_near": [{"t": 0.0, "angle": -46.0}, {"t": 0.25, "angle": 40.0,
                          "easing": "ease_in"}, {"t": 0.6, "angle": 30.0},
                          {"t": 1.0, "angle": -46.0}],
            "wing_far": [{"t": 0.0, "angle": -46.0}, {"t": 0.25, "angle": 40.0,
                         "easing": "ease_in"}, {"t": 0.6, "angle": 30.0},
                         {"t": 1.0, "angle": -46.0}],
            "torso": [{"t": 0.0, "angle": -4.0}, {"t": 0.35, "angle": 3.0},
                      {"t": 1.0, "angle": -4.0}],
            "head": [{"t": 0.0, "angle": 4.0}, {"t": 0.5, "angle": -2.0},
                     {"t": 1.0, "angle": 4.0}],
            "leg_near": [{"t": 0.0, "angle": -22.0}, {"t": 0.5, "angle": -16.0},
                         {"t": 1.0, "angle": -22.0}],
            "leg_far": [{"t": 0.0, "angle": -26.0}, {"t": 0.5, "angle": -20.0},
                        {"t": 1.0, "angle": -26.0}],
            "arm_near": [{"t": 0.0, "angle": -18.0}, {"t": 0.5, "angle": -12.0},
                         {"t": 1.0, "angle": -18.0}],
            "arm_far": [{"t": 0.0, "angle": -20.0}, {"t": 0.5, "angle": -14.0},
                        {"t": 1.0, "angle": -20.0}],
            "tail": _swing(-14.0, 14.0, phase=0.2),
        })

    return {anim.name: anim for anim in (idle, walk, run, jump, attack, hurt, die, fly,
                                         crouch, land, dash, climb, block, cast,
                                         throw, sleep)}


LIBRARY = _library()
PRESET_SETS = {
    "basic": ["idle", "walk"],
    "platformer": ["idle", "walk", "run", "jump", "land", "crouch", "dash",
                   "attack", "hurt"],
    "topdown": ["idle", "walk", "run", "attack", "hurt", "die"],
    "action": ["idle", "walk", "run", "attack", "block", "cast", "throw",
               "hurt", "die"],
    "full": ["idle", "walk", "run", "jump", "attack", "hurt", "die"],
    "everything": ["idle", "walk", "run", "jump", "land", "crouch", "dash",
                   "climb", "fly", "attack", "block", "cast", "throw", "hurt",
                   "die", "sleep"],
    "winged": ["idle", "fly", "walk", "attack", "hurt", "die"],
}


def get(name):
    if name in LIBRARY:
        return LIBRARY[name]
    raise KeyError("no built-in animation %r; have %s"
                   % (name, ", ".join(sorted(LIBRARY))))


def resolve(names):
    """Expand preset-set names and animation names into a list of Animations.

    Falls through to the subject library in `props` for anything this one does
    not have, because the two are not really separate catalogues any more. A
    `gust` is written against the `stalk` trait, and a hero's cape is a stalk;
    refusing to run it on a character because it was filed under props would be
    an accident of where the table lives. A clip that ends up driving nothing
    is dropped by the build with a reason, so the fallthrough cannot quietly
    ship a row of identical frames.
    """
    from . import props as props_module
    return _resolve(names, PRESET_SETS, LIBRARY, props_module)


def _resolve(names, presets, library, other):
    wanted = []
    for name in names:
        if name in presets:
            wanted.extend(presets[name])
        elif name in other.PRESET_SETS and name not in library:
            wanted.extend(other.PRESET_SETS[name])
        else:
            wanted.append(name)
    seen, out = set(), []
    for name in wanted:
        if name in seen:
            continue
        seen.add(name)
        if name in library:
            out.append(library[name])
        elif name in other.LIBRARY:
            out.append(other.LIBRARY[name])
        else:
            raise KeyError("no animation %r; have %s"
                           % (name, ", ".join(sorted(set(library) | set(other.LIBRARY)))))
    return out


def load_custom(path):
    with open(path) as handle:
        data = json.load(handle)
    entries = data if isinstance(data, list) else [data]
    animations = []
    for entry in entries:
        problems = validate_animation(entry)
        if problems:
            raise ValueError("%s: %s" % (path, "; ".join(problems)))
        animations.append(Animation.from_dict(entry))
    return animations


def scale_motion(animations, reference_height, squash_floor=0.0,
                 authored_height=32.0, travel_floor=1.0):
    """Rescale every animation for this character's size.

    Pixel offsets scale with the character. Squashes do not -- a squash is a
    ratio, already size-independent -- but they take a FLOOR, because the same
    ratio that leaves a 64px coin a nine-pixel sliver leaves a 16px potion a
    scatter of loose pixels. `quality.deepest_squash` measures that floor on the
    actual drawing; pass 0 to skip it.
    """
    factor = max(0.25, float(reference_height) / float(authored_height))
    scaled = [animation.scaled(factor).floored_travel(travel_floor)
              for animation in animations]
    if squash_floor <= 0:
        return scaled
    return [animation.floored(squash_floor, squash_floor) for animation in scaled]
