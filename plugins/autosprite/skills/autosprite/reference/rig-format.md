# The rig format

`<name>.rig.json` is the only artefact in this pipeline that anyone has an
opinion about, and it is deliberately small enough to correct by hand.

```json
{
  "version": 1,
  "class": "humanoid",
  "facing": "right",
  "size": [13, 26],
  "anchor": [6, 26],
  "actor": "llm:claude-opus-5@headless",
  "notes": ["shoulders at row 7, neck at row 5, hips at row 15"],
  "parts": [
    {"name": "torso", "role": "torso", "box": [3, 6, 10, 15],
     "parent": null, "pivot": [6, 15], "z": 1, "confidence": 1.0},
    {"name": "head", "role": "head", "box": [4, 0, 9, 6],
     "parent": "torso", "pivot": [6, 5], "z": 3, "confidence": 1.0}
  ]
}
```

## Fields

| Field | Meaning |
|---|---|
| `size` | `[width, height]` of the WORKING image, which is the trimmed, background-removed, native-resolution art. Not the file on disk. A rig whose size does not match is refused rather than stretched |
| `anchor` | The point every frame is positioned by, in working pixels. Bottom-centre unless set. This is the sprite's pivot in every engine file |
| `actor` | Who built it. `deterministic:template@...` means the silhouette; `llm:...@headless` means a model looked at the art. Nothing downstream may confuse the two |
| `notes` | What the rigger measured and what it had to guess. Read these before trusting a box |
| `box` | `[x0, y0, x1, y1]`, **half-open**, integer pixels, origin top-left. `x1` and `y1` are one past the last pixel |
| `parent` | The part this one hangs off. Exactly one part has `null` |
| `pivot` | `[x, y]` in working pixels: the point that stays still when the part rotates. May sit outside its own box, and usually does |
| `z` | Draw order, ascending. Negative is behind the body |
| `confidence` | The vision backend's own certainty. Below 0.5 means "I think this is here" |

## Roles

The motion library dispatches on `role` and ignores `name`, so a part named
`sword_arm` with role `arm_near` animates as an arm. Anything not in this list
is refused by validation.

`body` `torso` `head` `arm_near` `arm_far` `leg_near` `leg_far` `tail`
`wing_near` `wing_far` `prop` `accessory`

`body` means "ride the parent and never swing independently". It is the correct
role for anything that is not a limb, and for every part of a prop.

**near** is the camera side, drawn in front of the body; **far** is drawn behind
it. Paired roles must both exist: a rig with `arm_near` and no `arm_far`
produces a one-armed walk cycle, and validation refuses it.

## Pixel ownership

Boxes may overlap, and on any real rig they do -- a head box inside a torso box,
an arm box crossing the shoulder. The rule is:

> **The smallest box containing a pixel owns it.** Ties go to the part drawn in
> front.

So a small head box inside a large torso box takes the head's pixels, which is
what makes overlapping boxes safe to draw. A pixel no box covers falls to the
root rather than disappearing.

The consequence worth knowing when hand-editing: **making a box bigger can take
pixels away from it**, because a bigger box loses ties to smaller ones. If a
limb is dropping pixels, shrink its neighbours rather than growing it.

## Editing by hand

1. Open the overlay (`rig.py --preview` writes `rig-overlay.png`): every box is
   outlined in its own colour and every pivot is a white dot.
2. Edit the boxes in the JSON.
3. Re-run `rig.py --input A --out W --rig W/<name>.rig.json --preview` and look
   again. It re-validates, re-cuts, and re-checks that the parts still
   reassemble into the source exactly.
4. Build with the corrected rig: `build.py` writes its own rig, so pass the
   edited one to `animate.py` while iterating and re-run `rig.py --rig` to
   confirm before the final build.

## What validation refuses

These are the failures that would crash the renderer or silently drop pixels,
not the ones a picture would show you:

- no root, or more than one root
- a `parent` that is not a part, or a parent cycle
- a box outside the reference, or an empty box
- a missing pivot
- a role outside the vocabulary
- a paired limb with no partner

A rig that calls the head a leg passes every one of them. That is what the
overlay and the GIFs are for.
