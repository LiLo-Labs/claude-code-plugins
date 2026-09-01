# Writing an animation

An animation is a table of numbers over normalised time. Every built-in one has
the same shape as the ones you write, and both go through the same validator and
the same renderer -- there is no privileged path.

```json
{
  "name": "taunt",
  "frames": 6,
  "fps": 10,
  "loop": false,
  "easing": "smooth",
  "note": "why this animation is shaped the way it is",
  "flip_from": null,
  "root": [{"t": 0.0, "dy": 0.0}, {"t": 0.5, "dy": -2.0}, {"t": 1.0, "dy": 0.0}],
  "tracks": {
    "arm_near": [{"t": 0.0, "angle": 0.0},
                 {"t": 0.4, "angle": -95.0, "easing": "ease_in"},
                 {"t": 1.0, "angle": 0.0}]
  }
}
```

## Conventions

- **`t` runs 0..1** over the animation, whatever the frame count is.
- **Angles are degrees, clockwise positive, for a character facing RIGHT.**
  Screen y points down, so a positive arm angle swings the hand BACKWARDS and a
  negative one swings it forwards. A left-facing character is produced by
  mirroring the finished frame; never negate these numbers to get one.
- **Translations are pixels at a 32px-tall character** and are scaled to the
  real character automatically. Angles and squashes are size-independent and are
  not scaled.
- **Tracks are keyed by rig ROLE**, so one animation works on every rig. A rig
  with no `tail` ignores a tail track.
- **A looping animation's last frame is not its first.** Frame `i` samples at
  `i/frames`, so an 8-frame loop samples 0, 0.125 … 0.875 and the engine's wrap
  is one more step. Sampling `i/(frames-1)` instead puts a duplicate frame in
  every cycle, which reads as a stutter once per loop.

## Channels

| Channel | Effect | Rest |
|---|---|---|
| `angle` | Rotate about the part's pivot | `0` |
| `dx`, `dy` | Translate, in pixels | `0` |
| `sx`, `sy` | Scale about the pivot | `1` |
| `easing` | How to arrive at THIS key: `smooth`, `linear`, `ease_in`, `ease_out`, `hold` | the animation's `easing` |

`hold` steps instead of sliding: the previous key is held until this one, which
is how you get a frame that snaps rather than eases.

## The root track

`root` moves the whole character. Its `dx`/`dy` translate everything; its
`angle`, `sx` and `sy` are applied to the root PART, so the entire body leans or
squashes together. That is why `die` is one line of keyframes rather than one
per limb, and why a prop's `spin` needs no rig at all.

`flip_from` mirrors the frames from that `t` onward. It exists for one case: a
2D object turning about its vertical axis has no back face to draw, so it
narrows to nothing at the quarter point and comes back mirrored.

## From a request to keyframes

The vocabulary users actually use, and what it means:

| They say | Change |
|---|---|
| stiffer / more robotic | smaller limb angles; `easing: "linear"` |
| looser / more relaxed | larger limb angles; add a small counter-rotation on `head` |
| bouncier | larger `root` `dy`, and keep two bobs per walk cycle |
| heavier / more weight | lower `fps`, larger `dy`, add `sy` squash on the contact frames |
| faster | raise `fps` first. Adding frames makes it smoother, not faster |
| snappier attack | move the strike key earlier and give it `easing: "ease_in"`; hold the contact for one key |
| more anticipation | add a key BEFORE the action that moves the opposite way |
| the feet slide | reduce the leg angles: the stride is longer than the character's travel |

A worked example. *"Make the walk look tired."*

Tired is a smaller stride, a slower rate, a forward lean, and a head that hangs:

```json
{"name": "walk-tired", "frames": 8, "fps": 6, "loop": true,
 "root": [{"t": 0.0, "dy": 0.0}, {"t": 0.25, "dy": -0.5},
          {"t": 0.5, "dy": 0.0}, {"t": 0.75, "dy": -0.5}, {"t": 1.0, "dy": 0.0}],
 "tracks": {
   "leg_near": [{"t": 0.0, "angle": 14}, {"t": 0.5, "angle": -14}, {"t": 1.0, "angle": 14}],
   "leg_far":  [{"t": 0.0, "angle": -14}, {"t": 0.5, "angle": 14}, {"t": 1.0, "angle": -14}],
   "arm_near": [{"t": 0.0, "angle": -7}, {"t": 0.5, "angle": 7}, {"t": 1.0, "angle": -7}],
   "arm_far":  [{"t": 0.0, "angle": 7}, {"t": 0.5, "angle": -7}, {"t": 1.0, "angle": 7}],
   "torso":    [{"t": 0.0, "angle": 6}, {"t": 1.0, "angle": 6}],
   "head":     [{"t": 0.0, "angle": 8}, {"t": 1.0, "angle": 8}]}}
```

Every number in it is a decision you can defend: half the built-in leg swing,
`fps` from 10 to 6, a constant lean, and a head tipped forward and left there.

## Validation

`motion.validate_animation` runs on everything, and refuses:

- no name, or `frames` outside 1..64
- `fps` outside 0..120
- no tracks and no root -- every frame would be identical
- a track on a role that is not in the rig vocabulary
- a keyframe with no `t`, or `t` outside 0..1
- an unknown channel

Render it, watch the GIF, then adjust. Reading keyframes is not a substitute for
watching them move.
