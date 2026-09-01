---
name: autosprite
description: Use when the user wants animated sprite sheets from character art - turning one character image into idle/walk/run/jump/attack cycles, 8-direction movement, prop animations, or outfit and skin variants, and exporting them for Unity, Godot, Phaser, GameMaker, RPG Maker or Unreal. Triggers on "make a sprite sheet", "animate this character", "walk cycle from this image", "8-direction sprites", "spritesheet for Godot/Unity", "recolour this sprite".
---

# AutoSprite

`build.py` turns a character image into a verified sprite sheet in one command.
Everything between the image and the sheet is deterministic. The judgement is
which pixels are which part of the character, and this skill is that judgement:
whether the rig is right, whether the motion reads, and how to show the user in
ten seconds instead of forty frames.

Two rules that never bend:

- **Every output pixel came out of the user's art.** Nothing here generates,
  redraws, repaints or infers a pixel. Rotation and scaling are nearest-
  neighbour, compositing is an alpha test, and `verify.py` proves the sheet's
  palette is a subset of the source's. If a request needs a pixel that is not in
  the reference -- a back view, a new weapon, a redrawn frame -- say so and stop.
  This plugin will not invent it and must not pretend to.
- **The rig is confirmed before any sheet is built.** A wrong rig produces 44
  wrong frames that all look plausible in a grid. Confirming it costs one image.

## Pipeline position

| Stage | Command | This skill's part |
|---|---|---|
| ingest | inside `build.py` / `rig.py` | none, deterministic |
| rig | `rig.py --input A --out W --backend claude --preview` | **look at the overlay, fix the boxes, get the user's yes** |
| animate | `build.py --input A --out W ...` | choose the animations, directions and layout |
| review | `preview/*.gif` | **watch them; a bad rig is obvious in one second and invisible in JSON** |
| iterate | `animate.py --animation walk ...` | **change keyframes, re-watch, repeat** |
| verify | inside `build.py`, or `verify.py --dir W` | none, deterministic; report the checks |

Scripts run as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...`.

The order is not negotiable: **the rig is confirmed before the sheet is built.**
A sheet built on a rig that called the cloak a leg is forty frames of wasted
review, and the user cannot tell you which frame is wrong because all of them
are.

## Before rigging anything

1. **Run `rig.py --preview` and look at `rig-overlay.png`.** It draws every part
   box and pivot over the art at 6x. Numbers alone produce confident wrong
   answers; the overlay is what makes a wrong answer obvious.
2. **Read the notes the rigger wrote.** They say what it measured and what it
   had to guess: "the arms never separate from the body in the silhouette" means
   the arm boxes are a proportion, not a measurement, and are the first thing to
   check. A large **stray count** means many opaque pixels fell outside every
   box; they are safely carried by the root and will not move independently, but
   a big number says the rig missed something the user can see.
3. **Check `rest pose reconstructs the source exactly: True`.** False means the
   cut lost or duplicated pixels, which is a bug in this plugin rather than in
   the rig -- stop, say so, and report it. True does NOT mean the rig is right:
   a rig that calls the head a leg reassembles perfectly. Only the overlay and
   the GIFs answer that.
4. **Ask what the character is, once, if it is not obvious**, and pass it as
   `--intent`. "A knight with a shield on his left arm" changes what the vision
   backend calls the shield.

## Which backend

`--backend template` reads the silhouette. No model, no network, no credentials.
It finds the neck at the last narrow row before the shoulders and the hips where
the silhouette parts and stays parted, and on a standing character it is right
far more often than it is wrong.

`--backend claude` runs `claude -p` on the art with the session's own
credentials -- no API key. Use it when the silhouette will lie, which is
specifically:

| Reach for the vision backend when | Because the silhouette says |
|---|---|
| The character holds something across their body (staff, bow, shield) | The prop is part of the torso |
| There is a cape, cloak, coat tail or long hair | It reads as a third leg or a tail |
| The character is mounted, or riding anything | The mount's legs are the rider's |
| The character is a robot, mech, or has non-human proportions | The head is wherever the narrow part is |
| The art is a 3/4 or front view rather than a clean profile | Near and far are guesses |
| The template's notes admit a fallback | It already told you it guessed |

The template backend is not a fallback for a failed vision call -- it is a
different, cheaper answer to the same question. If `claude -p` is unavailable,
say the rig came from the silhouette and let the user judge the overlay.

## Reading the rig

Every part is a box, a role, a parent and a pivot. Judge them in that order.

| Part | Right when | Wrong when |
|---|---|---|
| **head** | The box's bottom edge sits at the neck, and its top edge is the top of the art. Height is roughly a quarter to a third of the character | The box stops halfway down the face -- the neck was found at the top of the head, not the bottom. The box includes the shoulders |
| **torso** | Spans neck to hips and no further; its width is the body without the arms | It is the full width of the art, which means the arms were never separated and both arm boxes are guesses |
| **arm_near / arm_far** | Each is a narrow column beside the torso, from the shoulder to about the hip; near is on the side the character faces | One of them overlaps the torso by more than a couple of pixels -- it will carry body pixels when it swings. Only one exists -- a one-armed walk cycle is a bug |
| **leg_near / leg_far** | Each runs from the hip line to the feet, split at the gap between the legs | They start at chest height -- the hip line was taken from the armpit. They are one box -- the character is robed, and that is fine, but say so |
| **tail / wing** | Only when there really is one | Anything invented. A character with no tail gets no tail |
| **pivot** | On the joint: the shoulder, the neck, the hip. Usually just inside the PARENT | In the middle of the part. The limb then orbits its own centre and detaches from the body every frame |

The single most common failure is **the hip line taken from the armpit**. Its
signature: the leg boxes start above the halfway point and the torso box is
short. The character then walks on its elbows. Check the hip row against the
overlay before anything else.

To fix a box, edit `<name>.rig.json` and re-run with `--rig`. Boxes are integer
pixels in the working image, `[x0, y0, x1, y1]`, half-open, origin top-left.
Overlap is fine: the smallest box containing a pixel owns it.
`reference/rig-format.md` has the full contract.

## Choosing animations

Ask for the game, not for a list of animations. The answer picks the set:

| The user says | Give them |
|---|---|
| A platformer, a metroidvania, "jumping" | `--animations platformer` (idle, walk, run, jump, land, crouch, dash, attack, hurt) |
| Top-down, an RPG, roguelike, "moving in 8 directions" | `--animations topdown --directions 8` |
| RPG Maker | `--animations walk --directions 4` -- MV/MZ needs exactly the four cardinals |
| "Just a walk cycle" | `--animations basic` |
| A brawler, an action RPG, "combat" | `--animations action` (adds block, cast, throw) |
| Nothing in particular | `--animations full` and let them cut it down |
| "Everything you have" | `--animations everything` -- all fifteen |
| A coin, a potion, a chest, a pickup | `--kind prop --animations pickup` |

The character library is idle, walk, run, dash, climb, crouch, jump, land,
attack, block, cast, throw, hurt, die, sleep. Two of them come with a caveat to
pass on: **climb** reads as reaching rather than gripping, because a profile
drawing has no front view to turn towards a wall; **sleep** lays the character
over with a root rotation, the same trick `die` uses, because a standing
drawing cannot be folded into a lying pose any other way.

Frame counts and rates are already tuned per animation and are visible in the
build output. Change them only when the user asks or when the build warns that
frames repeat -- which means the motion is too small for a character that size.

When the user does ask, two flags cover it:

- **`--frames N`** (2-64) redraws every clip at N frames. The motion is a
  continuous curve, so this samples it more finely rather than interpolating
  finished pictures, and fps moves with the count so the timing is unchanged.
  Useful when an engine or a jam wants a fixed frame count.
- **`--frame-size N`** (8-512) puts every frame in a square N-pixel cell with
  the character standing at the bottom centre, so every clip of every character
  shares one floor and one origin. This is what a tile-based importer and a
  fixed collision box want. It refuses rather than crops if the art does not
  fit, and the error says the size that would.

## Directions, and what not to claim

A profile drawing does not contain the back of the head. The build labels every
direction with how it was made and you must repeat that label honestly:

- **drawn** -- a reference exists for this view.
- **mirrored** -- the opposite side, flipped. Exact for a symmetric character.
- **foreshortened** -- a neighbouring view squashed. The standard approximation
  for a 3/4 sprite, and the diagonals are always this unless the user draws
  them. No extra reference fixes a diagonal; only a drawing at that angle does.
- **substituted** -- nothing was near enough, so the side view is reused as-is.
  This is the one worth flagging out loud. `--reference-front` and
  `--reference-back` turn N and S from substituted into drawn.

Never describe an 8-direction sheet built from one side view as eight views of
the character. Say which are drawn and which are approximated, and offer the two
extra references that would fix the cardinals.

## Reviewing

**Watch the GIFs.** `preview/<clip>.gif` plays at the clip's real frame rate.
That is the deliverable of the review step, not a nicety: a walk whose hips are
at chest height is unmistakable in one second of motion and invisible in a grid
of stills. Read them yourself before showing the user.

What to look for, in order:

1. **Does the character come apart?** A limb detaching means its pivot is not on
   its joint. The build repairs this by itself where it can: a clip measured to
   be shedding has the responsible swing -- and only that one -- reduced until
   it holds together, and the build report's `repairs` says which part, on which
   frame, and by how much. When it says damping did NOT put the character back
   together, believe it: that is a rig problem, and re-rigging is the fix.
   `--no-repair` turns it off.
2. **Does the ground line stay put?** A sprite with a baked contact shadow gets
   a `shadow` part that never moves, so the floor stays where the artist drew
   it while the character jumps off it. If a sprite's shadow still rides the
   character, the rigger did not recognise it -- check the rig notes.
3. **Do the feet slide?** The walk's contact frames should have a foot planted.
   If both feet move every frame the leg amplitudes are too large for the stride.
4. **Does anything freeze?** The build warns when frames repeat. Vertical
   travel is floored at one pixel so a small character's bob cannot round away,
   but the limb amplitudes still can; scale the motion up with a custom
   animation rather than upscaling the art.
5. **Does the near limb read as in front?** If the far arm is drawn over the
   torso, near and far are swapped -- pass the other `--facing`.
6. **Is the character looking at you?** If it is drawn face-on, `--facing front`
   (or `back`) is not cosmetic. It draws both limbs of each pair in front of the
   torso, names them left and right instead of near and far, and trades every
   clip's sideways limb swing for a lift, because a leg walking towards the
   camera foreshortens rather than sweeping across the picture. Built as a
   profile, a top-down RPG sprite splays its legs and reads as doing the splits
   -- and it will still measure zero debris, so only your eyes will catch it.

Show the user the contact sheet and one or two GIFs, name what you checked, and
ask about the specific thing you are unsure of. Do not ask them to review 44
frames.

## Iterating on motion

When the user says a cycle is wrong, do not rebuild the sheet. Change the
keyframes and re-render that one clip.

**Try the critic first.** `--critic claude` shows the rendered clip to a vision
model and asks what is wrong with the MOTION, then folds its answer back into
the keyframes as deltas. It is the only thing here that judges whether a cycle
*reads*, which is exactly what the debris measurement cannot do:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/animate.py" \
  --input A --rig W/<name>.rig.json --animation walk --critic claude --out look/
```

Every round is re-rendered and re-measured, and one that makes the character
come apart is thrown away, so the critic can only change how the motion reads.
Two rounds is the default and usually enough; it stops early when it has nothing
left to say. Read what it says out loud to the user -- its problems list is
specific ("the staff arm reads as a detached blob", "the legs barely alternate")
and is often the fastest route to the real complaint.

If the critic is satisfied and the user is not, edit the keyframes by hand:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/animate.py" \
  --input A --rig W/<name>.rig.json --animation walk --custom my-walk.json --out look/
```

An animation is a table of angles over normalised time, keyed by rig ROLE, and
it is meant to be edited. "Stiffer" is smaller leg angles; "bouncier" is a
larger root `dy`; "heavier" is a lower fps and a bigger bob.
`reference/animation-format.md` has the contract, the channel list, and a worked
example of turning a plain-language request into keyframes.

Custom animations are also how a text prompt becomes motion: write the
keyframes, validate them, render, watch, adjust. There is no separate path for
it and no model in the render loop.

## Variants

Recolouring one colour at a time destroys a sprite's shading. The unit is the
**ramp** -- the shades of one material, ordered dark to light -- and moving a
whole ramp's hue keeps every value where it was.

1. `variants.py --describe` writes `ramps/ramp-N.png`: the character with one
   ramp lit and the rest dimmed, plus each ramp's share and position.
2. **Look at those images and name the ramps.** Share and position decide it: a
   ramp that is 30% of the sprite and centred low is the boots; one that is 2%
   and at the top is an eye highlight, and changing it changes nothing.
3. Apply with `--name 0=skin,1=cloak --variant '{"cloak": {"hue": 0}}'`. The
   output is an ordinary character image; feed it back into `build.py`.

Two materials that share a hue *and* touch each other stay in one ramp. That is
ambiguous from colour alone -- say so and offer explicit `colours` replacement
rather than pretending a threshold would have known.

## When it will not work

Say so plainly rather than producing something worse:

- **A back view, a new weapon, a different pose than any reference.** No pixel
  for it exists. Ask for the drawing.
- **Anti-aliased or painted art.** It still runs, and the palette guarantee
  still holds, but nearest-neighbour rotation leaves ragged edges on soft art.
  The ingest report says `continuous` when this is the case -- tell the user
  before building forty frames they will not like.
- **Articulated motion on a prop.** A gem has no elbow. Props animate as one
  piece, which is never wrong, only plain.
- **A character whose limbs are drawn merged into the body.** The rigger says so
  in its notes. A vision rig does better; hand-edited boxes do best.

## Reference

- `reference/rig-format.md` -- the rig contract and how to hand-edit it
- `reference/animation-format.md` -- keyframe authoring, channels, worked example
- `reference/engine-import.md` -- what each exported file is and how to import it
- `reference/example-animation.json` -- a complete custom animation
