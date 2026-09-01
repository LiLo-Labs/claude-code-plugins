---
description: Turn one character image into an animated, engine-ready sprite sheet - rig it with vision, animate idle/walk/run/jump/attack and 8-direction movement from the character's own pixels, and export for Unity, Godot, Phaser, GameMaker, RPG Maker and Unreal
---

## Your task

The user wants a sprite sheet. The arguments they passed are: `$ARGUMENTS`

Accepted form:

```
/autosprite <character.png> [--game platformer|topdown|rpgmaker]
            [--animations idle,walk,run] [--directions 1|2|4|8]
            [--intent "a knight with a shield"] [--engines godot,phaser]
```

If `$ARGUMENTS` is empty, ask for the path to the character image and stop. Do
not guess a path and do not go looking for PNGs on the machine.

Working paths, used by every step:

- `<ART>` — the path they gave, resolved to an absolute path
- `<WORK>` — `<art-directory>/<art-stem>-sprites/`, created if missing. Every
  output goes there, so a re-run is cheap and the user can delete one folder to
  clean up

Read `${CLAUDE_PLUGIN_ROOT}/skills/autosprite/SKILL.md` before step 2. It has
the rig-reading table, the direction honesty rules, and the review checklist,
and this command is only the order of operations.

## Step 1 — Validate the input

Check that `<ART>` exists and is a `.png`, `.jpg`, `.gif` or `.bmp`. If it does
not exist, say so with the path you tried and stop. If it is a `.psd`, `.aseprite`
or `.svg`, say it needs exporting to PNG first and stop — do not try to convert it.

## Step 2 — Rig, and confirm the rig before anything else

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rig.py" \
  --input "<ART>" --out "<WORK>" --backend claude --preview \
  [--intent "..."] [--facing left]
```

Use `--backend claude` by default: it looks at the art with the session's own
credentials and no API key. If `claude` is not on PATH the script says so —
fall back to `--backend template`, which rigs from the silhouette, and tell the
user the rig came from the outline rather than from looking.

Then:

1. **Read `<WORK>/rig-overlay.png`.** Every part box and pivot is drawn over the
   art at 6x. Judge it against the table in SKILL.md — the head box reaching the
   neck, the hip line at the hips and not the armpit, each arm clear of the
   torso, every pivot on a joint.
2. If `rest pose reconstructs the source exactly` is `False`, stop and say so.
3. If a box is wrong, edit `<WORK>/<stem>.rig.json` and re-run with
   `--rig "<WORK>/<stem>.rig.json" --preview` until it is right.
4. **Show the user the overlay and ask them to confirm the parts**, naming the
   one thing you are least sure about. Do not build a sheet before they answer:
   a wrong rig is forty wrong frames that all look plausible.

## Step 3 — Choose the animations and directions

If they said what kind of game it is, that decides it (SKILL.md has the table).
If they did not, ask once, in the same message as the rig confirmation, and
offer `full` as the default.

## Step 4 — Build

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build.py" \
  --input "<ART>" --out "<WORK>" \
  --animations <set> --directions <n> --backend claude \
  [--engines godot,phaser] [--layout packed] [--scale 2]
```

`build.py` re-rigs with the same backend. If the user hand-edited the rig in
step 2, keep that file: copy it aside, let the build write its own, then compare
— if the build's rig differs from the confirmed one, restore the confirmed one
and re-run `animate.py` per clip rather than accepting a rig the user did not see.

The build prints the source report, the rig, every clip, everything written, any
warnings, and the verification table. It exits non-zero if verification fails.

## Step 5 — Review the motion, then report

**Read the GIFs in `<WORK>/preview/` before you say anything.** They play at the
clip's real frame rate; a still sheet cannot show timing, and every motion bug
worth catching is a timing bug. Check for limbs detaching, feet sliding, frozen
frames, and near/far limbs drawn on the wrong side (SKILL.md, "Reviewing").

Then report, in this order:

1. What was built: the sheet size, the clips and their frame rates, and where it
   all is.
2. The verification table verbatim. All checks must pass; if any failed, say
   which and stop rather than handing over a sheet you cannot vouch for.
3. **Any direction that is not `drawn` or `mirrored`**, using the build's own
   word for it. Never describe an 8-direction sheet built from one side view as
   eight views of the character. Offer `--reference-front` and
   `--reference-back` if the cardinals were substituted.
4. Any warning the build printed, especially repeated frames.
5. Show the contact sheet and one GIF.

## Step 6 — Iterate, if they want changes

- **Motion is wrong** → write keyframes and re-render that one clip with
  `scripts/animate.py --custom`. Do not rebuild the sheet to look at a walk.
  `reference/animation-format.md` maps plain-language requests to numbers.
- **A part is wrong** → edit the rig, re-run step 2, then step 4.
- **They want a recolour** → `scripts/variants.py --describe`, look at the ramp
  images, name the ramps, apply, and feed the recoloured PNG back into step 4.
- **They want another engine** → re-run step 4 with `--engines`; it is cheap.

## What this will not do

It never generates a pixel. Every output pixel came out of the image the user
supplied, which is exactly why the palette check can pass. If they ask for a
back view, a redrawn frame, a new weapon or a pose no reference contains, say
that no pixel for it exists and ask for the drawing. Do not offer to approximate
it and do not imply the plugin could.
