"""Ask a vision model what is WRONG with the motion, then fix it and re-measure.

Every metric in `quality.py` answers "did the character come apart". None of them
answers "does this read as a walk", and that is the gap that matters most: a
robed figure whose hip line is an admitted guess scores zero debris and still
walks badly. No cheap arithmetic proxy for it has been found.

So stop looking for one. The plugin already ships a vision backend; show it the
contact sheet and ask. What comes back is not pixels -- a model cannot draw a
frame -- but a critique and a set of KEYFRAME ADJUSTMENTS, which is exactly the
shape of thing the motion library is made of and exactly the kind of judgement a
model is good at.

Two rules keep this honest, and both matter:

**The critic proposes; the measurement disposes.** Every adjustment is applied,
re-rendered and re-measured, and a round that makes the character come apart is
thrown away. The model can improve how the motion reads; it is never allowed to
break the character to do it.

The threshold for "comes apart" is deliberately loose, and that is measured
rather than chosen. Sweeping a leg-swing delta from -8 to +60 degrees on the
test character moves shed by at most half a percentage point, in no consistent
direction: -4 makes it slightly WORSE and +60 slightly better. Shed is a
catastrophe detector -- it is what caught an 18% slime and a 16% potion -- and it
has about half a point of noise, so it cannot adjudicate small changes. A
guardrail that rejected any increase would therefore reject good adjustments at
random. Two percentage points is comfortably above the noise and far below
anything a viewer would call broken.

**The critic only moves numbers that already exist.** It returns deltas on the
channels of the tracks the animation already has. It cannot add a limb, invent a
track, or reach past the keyframe table into the renderer.

It is also shown the RIG, and that is not a detail. Run across six characters
without it, the critic advised opening the SLIME's leg swing -- a slime that has
no legs, whose silhouette rig had invented some. Shown only frames, it can only
ever answer "this motion is wrong", so it rationalises whatever rig it is given.
Shown the parts as well, it can say the rig is the problem, which is the more
useful answer and the one a human reviewer would give.
"""

import copy
import json
import os

from . import image as img
from . import motion as motion_module
from . import quality as quality_module
from . import render as render_module

CHANNEL_LIMITS = {
    "angle": 120.0,   # degrees; beyond this a limb is not swinging, it is spinning
    "dx": 12.0,       # pixels, at the authored 32px scale
    "dy": 12.0,
    "sx": 1.6,
    "sy": 1.6,
    # Steps along a ramp. Four is already the whole of most sprite ramps, so a
    # larger number is not a brighter glow, it is the same clamped one.
    "cycle": 4.0,
    # Degrees of lean. Past about 40 a surface is not leaning, it is folding
    # over itself, and nearest-neighbour sampling turns that into a smear.
    "shear": 40.0,
    # Pixels of vertical slide. Past a fifth of a part's height a wave is not a
    # wave, it is the part being torn into columns.
    "wave": 12.0,
    "wave_phase": 2.0,
}
MIN_SCALE = 0.2


REVIEW_PROMPT = """You are looking at one animation from a game sprite sheet, \
laid out left to right, upscaled so you can see individual pixels. The leftmost \
image is the ORIGINAL character for reference; the rest are the animation's \
frames in order.

The animation is "%(name)s" (%(frames)d frames, %(fps)g fps, %(loop)s). It was \
made by cutting the original character into parts and rotating them about their \
joints -- no pixel was drawn or invented. So the ART cannot be wrong; only the \
MOTION, or the RIG the motion is applied to, can be.

The character was cut into these parts. Boxes are fractions of the image, \
[left, top, right, bottom], origin top-left:

%(rig)s

Judge the motion and the rig, not the drawing. Answer with JSON only, no prose, \
no fence.

{
  "verdict": "good" | "loose" | "broken" | "rig",
  "problems": ["one short sentence each, most important first"],
  "rig_problems": ["parts that are wrong for THIS character, if any"],
  "adjustments": {"<role>": {"<channel>": <delta>}}
}

**Check the rig against the picture first.** The parts above were guessed, and \
on some characters the guess is simply wrong -- a legless blob given legs, a \
quadruped given a torso and arms, a head box that stops halfway down the face. \
If the rig does not match what you can see, say verdict "rig", list what is \
wrong in rig_problems, and return NO adjustments: tuning the swing of a limb \
the character does not have is wasted work, and the rig has to be fixed first.

Only when the parts are broadly right, judge the motion:

Roles you may adjust: %(roles)s
Channels: angle (degrees, clockwise positive for a right-facing character), \
dx, dy (pixels), sx, sy (scale). Use "root" for the whole character.

An adjustment is a DELTA applied to every keyframe of that role's track, \
scaled by how far that keyframe already departs from rest -- so a positive \
angle delta opens the swing up and a negative one closes it down. Only include \
roles that need changing, and only channels the track already uses.

What to look for, in order:

- **Does it read as %(name)s at all?** A walk needs the legs to alternate and \
  the body to rise and fall twice per cycle. A run is a walk with a longer \
  stride and a forward lean.
- **Do the feet slide?** In the contact frames a foot should look planted. If \
  both feet move every frame, the stride is too long: close the leg angles down.
- **Is anything frozen?** If several frames look identical the motion is too \
  small for a character this size: open the amplitudes up.
- **Does a limb detach or read as a loose blob?** Close that limb's angle down.
- **Is the body stiff?** A little counter-rotation on the head and torso is what \
  makes a cycle look alive.

You are not obliged to find fault. If the motion already reads well, say \
verdict "good" with no adjustments -- across six characters this critic said \
"loose" every single time, which is a bias to correct for, not a finding.

Be conservative. Deltas above about 15 degrees or 4 pixels are large. If the \
motion already reads well, say verdict "good", give an empty adjustments object, \
and do not invent work."""


class Critique:
    def __init__(self, verdict="good", problems=None, adjustments=None,
                 rig_problems=None, actor="unknown"):
        self.verdict = verdict
        self.problems = list(problems or [])
        self.rig_problems = list(rig_problems or [])
        self.adjustments = dict(adjustments or {})
        self.actor = actor

    @property
    def wants_change(self):
        return bool(self.adjustments)

    @property
    def blames_the_rig(self):
        """No amount of keyframe tuning fixes a limb the character does not have."""
        return self.verdict == "rig" or bool(self.rig_problems)

    def to_dict(self):
        return {"verdict": self.verdict, "problems": self.problems,
                "rig_problems": self.rig_problems,
                "adjustments": self.adjustments, "actor": self.actor}


class NullCritic:
    """The honest floor: looks at nothing, asks for nothing.

    Not a mock. It is what the refinement loop does with no model attached, and
    it is why every test in this plugin runs without one.
    """

    actor = "deterministic:null-critic@0.1.0"

    def review(self, contact_sheet_path, animation, rig=None):
        return Critique(actor=self.actor)


class HeadlessCritic:
    """`claude -p` looking at the contact sheet. No API key; the session's own auth."""

    def __init__(self, workdir, model="claude-opus-5", timeout=300, executable="claude"):
        self.workdir = workdir
        self.model = model
        self.timeout = timeout
        self.executable = executable
        self.actor = "llm:%s@critic" % model

    def review(self, contact_sheet_path, animation, rig=None):
        from .vision import _extract_json
        import subprocess

        prompt = REVIEW_PROMPT % {
            "name": animation.name,
            "frames": animation.frames,
            "fps": animation.fps,
            "loop": "looping" if animation.loop else "one-shot",
            "roles": ", ".join(sorted(set(animation.tracks) | {"root"})),
            "rig": describe_rig(rig),
        }
        prompt += "\n\nRead this file: %s\n" % contact_sheet_path

        command = [self.executable, "-p", prompt, "--allowed-tools", "Read",
                   "--model", self.model, "--output-format", "json"]
        try:
            finished = subprocess.run(command, capture_output=True, timeout=self.timeout)
        except FileNotFoundError:
            raise RuntimeError("no %r on PATH; the critic needs the Claude CLI"
                               % self.executable)
        except subprocess.TimeoutExpired:
            raise RuntimeError("the critic did not answer within %ds" % self.timeout)
        if finished.returncode != 0:
            raise RuntimeError("the critic failed (%d): %s"
                               % (finished.returncode, finished.stderr.decode()[:300]))

        payload = json.loads(finished.stdout.decode())
        answer = payload.get("result", "") if isinstance(payload, dict) else str(payload)
        data = _extract_json(answer)
        return Critique(data.get("verdict", "good"), data.get("problems"),
                        data.get("adjustments"), data.get("rig_problems"),
                        self.actor)


def describe_rig(rig):
    """The parts, as fractions, in the order they are drawn. Small on purpose.

    A model reads a short table far better than a wall of pixel coordinates, and
    fractions travel between the sheet it is looking at and the rig underneath
    without either of them having to agree on a scale.
    """
    if rig is None:
        return "  (not supplied)"
    width, height = rig.size
    lines = ["  the character is drawn facing %s" % rig.facing]
    if rig.facing in ("front", "back"):
        # Otherwise a model reads "arm_far" as a claim about depth and objects,
        # correctly, that a character looking at you has no far side. The roles
        # are a PAIRING, not a depth: they are what makes the two halves swing
        # in counter-phase, and on a face-on rig they simply mean left and
        # right. Say so, rather than letting it find a bug that is not there.
        lines.append("  (drawn face-on: the *_near and *_far roles are only how "
                     "a pair is named, and mean the character's two sides; "
                     "neither is behind the other)")
    for part in rig.draw_order():
        x0, y0, x1, y1 = part.box
        lines.append("  %-12s role=%-10s box=[%.2f, %.2f, %.2f, %.2f]"
                     % (part.name, part.role, x0 / float(width), y0 / float(height),
                        x1 / float(width), y1 / float(height)))
    return "\n".join(lines) or "  (no parts)"


def apply_adjustments(animation, adjustments):
    """A new animation with the deltas folded in, clamped to sane bounds.

    A delta scales with how far the keyframe already departs from rest, so
    opening a swing up widens the extremes and leaves the neutral frames alone.
    A track sitting entirely at rest is nudged by the raw delta instead, which is
    the only way to start motion that is not there at all.
    """
    clone = copy.deepcopy(animation)
    changed = 0
    for role, channels in (adjustments or {}).items():
        tracks = []
        if role == "root" and clone.root is not None:
            tracks.append(clone.root)
        if role in clone.tracks:
            tracks.append(clone.tracks[role])
        if not tracks:
            continue
        for track in tracks:
            for channel, delta in channels.items():
                if channel not in motion_module.CHANNELS:
                    continue
                try:
                    delta = float(delta)
                except (TypeError, ValueError):
                    continue
                rest = motion_module.REST[channel]
                widest = max((abs(value - rest) for value in track.values(channel)),
                             default=0.0)
                limit = CHANNEL_LIMITS[channel]

                def move(value, rest=rest, delta=delta, widest=widest, limit=limit,
                         channel=channel):
                    if widest > 1e-6:
                        value = value + delta * ((value - rest) / widest)
                    else:
                        value = value + delta
                    if channel in ("sx", "sy"):
                        return round(max(MIN_SCALE, min(limit, value)), 3)
                    return round(max(-limit, min(limit, value)), 3)

                changed += track.adjust(channel, move)
    return clone, changed


def contact_sheet(frames, reference_pixels, path, target_height=110):
    """The picture the critic looks at: the source, then every frame, upscaled."""
    from . import preview as preview_module

    tall = 1
    for frame in frames:
        box = img.content_box(frame)
        if box:
            tall = max(tall, box[3] - box[1])
    scale = max(1, int(round(target_height / float(tall))))

    shown = [img.scale_nearest(reference_pixels, scale)] + [
        img.scale_nearest(frame, scale) for frame in frames]
    cell_w = max(piece.shape[1] for piece in shown)
    cell_h = max(piece.shape[0] for piece in shown)
    gap = 6
    canvas = img.blank(cell_h + 2 * gap, len(shown) * (cell_w + gap) + gap)
    canvas[:, :] = (18, 18, 24, 255)
    for index, piece in enumerate(shown):
        img.paste(canvas, piece,
                  gap + index * (cell_w + gap) + (cell_w - piece.shape[1]) // 2,
                  gap + (cell_h - piece.shape[0]))
    img.save(canvas, path)
    return path, preview_module


# How much more of the character a round may shed before it is thrown away.
# See the module docstring: shed carries about half a point of noise, so a
# tighter gate rejects good adjustments at random.
SHED_TOLERANCE = 0.02


def refine(cutout, rig, animation, reference_pixels, critic, workdir, rounds=2,
           margin=None, tolerance=SHED_TOLERANCE):
    """Critique, adjust, re-measure; keep a round only if it did not shed more.

    The loop is deliberately short. A critic that is allowed to keep going will
    keep finding something to say, and the point is not to satisfy it -- it is to
    take the one or two adjustments that clearly help and stop.

    Returns (animation, history). The animation is the best one found, which may
    be the one that came in.
    """
    os.makedirs(workdir, exist_ok=True)
    if margin is None:
        margin = render_module.suggest_margin(rig)

    def frames_of(candidate):
        scaled = motion_module.scale_motion([candidate], rig.size[1])[0]
        return [render_module.render_pose(cutout, pose, margin=margin)
                for pose in scaled.poses(rig)]

    best = animation
    best_frames = frames_of(best)
    best_shed = quality_module.shed(best_frames, reference_pixels)[0]
    history = []

    for index in range(max(0, int(rounds))):
        path = os.path.join(workdir, "%s-round%d.png" % (best.name, index))
        contact_sheet(best_frames, reference_pixels, path)
        critique = critic.review(path, best, rig)
        entry = {"round": index, "sheet": path, "critique": critique.to_dict(),
                 "shed_before": round(best_shed, 4)}

        if critique.blames_the_rig:
            entry["outcome"] = ("the rig is the problem, not the motion: %s"
                                % "; ".join(critique.rig_problems[:2]))
            history.append(entry)
            break

        if not critique.wants_change:
            entry["outcome"] = "no change asked for"
            history.append(entry)
            break

        candidate, touched = apply_adjustments(best, critique.adjustments)
        if not touched:
            entry["outcome"] = "adjustments matched no track this rig has"
            history.append(entry)
            break

        frames = frames_of(candidate)
        shed = quality_module.shed(frames, reference_pixels)[0]
        entry["shed_after"] = round(shed, 4)
        if shed > best_shed + tolerance:
            entry["outcome"] = ("rejected: it would shed %.1f%% against %.1f%%"
                                % (shed * 100, best_shed * 100))
            history.append(entry)
            break

        entry["outcome"] = "accepted (%d keyframe values moved)" % touched
        history.append(entry)
        best, best_frames, best_shed = candidate, frames, shed

    return best, history


def make_critic(name, workdir, model="claude-opus-5"):
    if name in ("none", "null", "off", "template", "deterministic"):
        return NullCritic()
    if name in ("claude", "headless", "vision"):
        return HeadlessCritic(workdir, model=model)
    raise ValueError("unknown critic %r (none | claude)" % name)
