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

CHANNELS = ("angle", "dx", "dy", "sx", "sy")
REST = {"angle": 0.0, "dx": 0.0, "dy": 0.0, "sx": 1.0, "sy": 1.0}


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


class Track:
    """Keyframes for one role, as a list of {"t": float, <channel>: value}."""

    def __init__(self, keys, easing="smooth"):
        self.keys = sorted((dict(key) for key in keys), key=lambda key: float(key["t"]))
        self.easing = easing
        if not self.keys:
            raise ValueError("a track needs at least one keyframe")

    def sample(self, t, loop):
        """The PartPose at time t. Wraps for a loop, clamps for a one-shot."""
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


def _key_pose(key):
    return PartPose(*(float(key.get(name, REST[name])) for name in CHANNELS))


class Animation:
    def __init__(self, name, frames, fps=10, loop=True, tracks=None, root=None,
                 easing="smooth", note="", flip_from=None):
        self.name = name
        # A 2D spin has no back face to draw: the object squashes to nothing and
        # comes back mirrored. `flip_from` is the instant it passes edge-on.
        self.flip_from = flip_from
        self.frames = int(frames)
        self.fps = float(fps)
        self.loop = bool(loop)
        self.easing = easing
        self.note = note
        self.tracks = {role: track if isinstance(track, Track) else Track(track, easing)
                       for role, track in (tracks or {}).items()}
        self.root = Track(root, easing) if root and not isinstance(root, Track) else root

    def times(self):
        """Where each frame samples. See the loop note in the module docstring."""
        if self.frames <= 1:
            return [0.0]
        divisor = float(self.frames) if self.loop else float(self.frames - 1)
        return [index / divisor for index in range(self.frames)]

    def pose_at(self, rig, t):
        """Resolve every role track onto the rig's actual parts."""
        pose = Pose()
        if self.flip_from is not None:
            pose.flip = t >= float(self.flip_from)
        for part in rig.parts:
            track = self.tracks.get(part.role)
            if track is not None:
                pose.set(part.name, track.sample(t, self.loop))
        if self.root is not None:
            whole = self.root.sample(t, self.loop)
            pose.dx, pose.dy = whole.dx, whole.dy
            # A root track's angle and squash belong to the root PART, so that
            # the whole character leans or squashes together. This is what makes
            # `die` a single line of keyframes instead of one per limb.
            root_part = rig.root
            if root_part is not None and (whole.angle or whole.sx != 1.0 or whole.sy != 1.0):
                existing = pose.get(root_part.name)
                pose.set(root_part.name,
                         PartPose(existing.angle + whole.angle,
                                  existing.dx, existing.dy,
                                  existing.sx * whole.sx, existing.sy * whole.sy))
        return pose

    def poses(self, rig):
        return [self.pose_at(rig, t) for t in self.times()]

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
        clone.fps = self.fps * (float(frames) / float(self.frames))
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
            for key in track.keys:
                for channel in ("dx", "dy"):
                    if channel in key:
                        key[channel] = float(key[channel]) * factor
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
            peak = max((abs(float(key.get("angle", 0.0))) for key in track.keys),
                       default=0.0)
            if peak <= 0.0:
                continue
            channel, amount = (("dy", -float(lift)) if role.startswith("leg_")
                               else ("dx", float(reach)))
            for key in track.keys:
                angle = float(key.get("angle", 0.0))
                key["angle"] = angle * float(swing)
                key[channel] = float(key.get(channel, REST[channel])) + amount * (angle / peak)
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
            for key in track.keys:
                if "sx" in key:
                    key["sx"] = max(float(key["sx"]), min_sx) if key["sx"] >= 0 else key["sx"]
                if "sy" in key:
                    key["sy"] = max(float(key["sy"]), min_sy) if key["sy"] >= 0 else key["sy"]
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
                values = [float(key.get(channel, 0.0)) for key in track.keys]
                span = max(values) - min(values)
                if span <= 0.0 or span >= min_pixels:
                    continue
                factor = min_pixels / span
                for key in track.keys:
                    if channel in key:
                        key[channel] = float(key[channel]) * factor
        return clone

    def to_dict(self):
        return {"name": self.name, "frames": self.frames, "fps": self.fps,
                "loop": self.loop, "easing": self.easing, "note": self.note,
                "flip_from": self.flip_from,
                "root": self.root.to_list() if self.root else None,
                "tracks": {role: track.to_list() for role, track in self.tracks.items()}}

    @classmethod
    def from_dict(cls, data):
        return cls(data["name"], data["frames"], data.get("fps", 10),
                   data.get("loop", True), data.get("tracks"), data.get("root"),
                   data.get("easing", "smooth"), data.get("note", ""),
                   data.get("flip_from"))


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
    fps = data.get("fps", 10)
    if not isinstance(fps, (int, float)) or not 0 < fps <= 120:
        problems.append("fps must be between 0 and 120, got %r" % (fps,))

    tracks = data.get("tracks") or {}
    if not tracks and not data.get("root"):
        problems.append("no tracks and no root track: every frame would be identical")

    from .rig import ROLES
    for role, keys in tracks.items():
        if role not in ROLES:
            problems.append("track %r is not a rig role (%s)" % (role, ", ".join(ROLES)))
        if not isinstance(keys, list) or not keys:
            problems.append("track %r has no keyframes" % role)
            continue
        for key in keys:
            if not isinstance(key, dict) or "t" not in key:
                problems.append("track %r has a keyframe with no t: %r" % (role, key))
                continue
            if not 0.0 <= float(key["t"]) <= 1.0:
                problems.append("track %r has t=%s outside 0..1" % (role, key["t"]))
            unknown = set(key) - set(CHANNELS) - {"t", "easing"}
            if unknown:
                problems.append("track %r has unknown channels %s"
                                % (role, ", ".join(sorted(unknown))))
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
        note="breathing; the frame a player sees more than any other",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.5, "dy": 1.0}, {"t": 1.0, "dy": 0.0}],
        tracks={
            "head": [{"t": 0.0, "dy": 0.0}, {"t": 0.6, "dy": 1.0}, {"t": 1.0, "dy": 0.0}],
            "arm_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 3.0},
                         {"t": 1.0, "angle": 0.0}],
            "arm_far": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": -3.0},
                        {"t": 1.0, "angle": 0.0}],
            "tail": [{"t": 0.0, "angle": -4.0}, {"t": 0.5, "angle": 4.0},
                     {"t": 1.0, "angle": -4.0}],
        })

    walk = Animation(
        "walk", frames=8, fps=10, loop=True,
        note="legs in counter-phase, arms opposing the legs, two body bobs per cycle",
        root=[{"t": 0.0, "dy": 0.0}, {"t": 0.25, "dy": -1.0}, {"t": 0.5, "dy": 0.0},
              {"t": 0.75, "dy": -1.0}, {"t": 1.0, "dy": 0.0}],
        tracks={
            "leg_near": _swing(26.0, -26.0),
            "leg_far": _swing(-26.0, 26.0),
            "arm_near": _swing(-18.0, 18.0),
            "arm_far": _swing(18.0, -18.0),
            "torso": [{"t": 0.0, "angle": -2.0}, {"t": 0.5, "angle": 2.0},
                      {"t": 1.0, "angle": -2.0}],
            "tail": _swing(-8.0, 8.0, phase=0.15),
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
        })

    attack = Animation(
        "attack", frames=6, fps=14, loop=False,
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
        "hurt", frames=4, fps=12, loop=False,
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
        })

    return {anim.name: anim for anim in (idle, walk, run, jump, attack, hurt, die)}


LIBRARY = _library()
PRESET_SETS = {
    "basic": ["idle", "walk"],
    "platformer": ["idle", "walk", "run", "jump", "attack", "hurt"],
    "topdown": ["idle", "walk", "run", "attack", "hurt", "die"],
    "full": ["idle", "walk", "run", "jump", "attack", "hurt", "die"],
}


def get(name):
    if name in LIBRARY:
        return LIBRARY[name]
    raise KeyError("no built-in animation %r; have %s"
                   % (name, ", ".join(sorted(LIBRARY))))


def resolve(names):
    """Expand preset-set names and animation names into a list of Animations."""
    wanted = []
    for name in names:
        if name in PRESET_SETS:
            wanted.extend(PRESET_SETS[name])
        else:
            wanted.append(name)
    seen, out = set(), []
    for name in wanted:
        if name not in seen:
            seen.add(name)
            out.append(get(name))
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
