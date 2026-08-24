---
name: model-paint
description: Use when the user wants to paint, color, or assign filaments to a 3D model (STL or 3MF) for multi-material printing - naming the real features on the model (eyes, horns, spikes, claws, belly plates, or panels and trim on non-creatures), planning colors against the filaments they have loaded, and writing the plan.json that produces an OrcaSlicer/Bambu-ready painted 3MF. Triggers on "paint this model", "color my dragon", "multicolor STL", "assign filaments", "4-color 3MF".
---

# Model Paint

`segment.py` turns a mesh into thirty described regions. `apply_plan.py` turns a
plan into a painted 3MF and proves the geometry survived. Everything between
those two is judgment, and this skill is that judgment: which region is an eye,
which filament it should be, and how to show the user the answer so they can
approve it in ten seconds instead of prompting for six hours.

Two rules that never bend:

- **Geometry never changes.** This skill only ever reads the mesh. Nothing here
  repairs, re-orients, re-scales, or re-meshes anything. If a model looks broken,
  say so and stop.
- **Symmetric partners always get the same filament.** A dragon with one gold eye
  is a bug, not a style.

## Pipeline position

| Stage | Command | This skill's part |
|---|---|---|
| detect | `segment.py --input M --output segments.json` | none, deterministic |
| render | `preview.py --input M --segments segments.json --output prev/` | look at the pictures |
| propose | - | **name the parts and show the list with its evidence** |
| iterate | - | **fix the list until the user says it is right** |
| color | - | **2-3 plans, ask at most once, write plan.json** |
| render | `preview.py --input M --segments segments.json --plan plan.json --output prev/` | look again, then show the user |
| apply | `apply_plan.py --input M --segments segments.json --plan plan.json --output painted.3mf` | none, deterministic |

Scripts run as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" ...`.

The order is not negotiable: **the part list is confirmed before any color is
proposed.** Color argued in the abstract is wasted work if the parts underneath
it are wrong, and a wrong part list is exactly what cost the user six hours.
`${CLAUDE_PLUGIN_ROOT}/docs/interaction-model.md` has the full loop.

## Before naming anything

1. **Render the segmentation and read the contact sheet.** Numbers alone produce
   confident wrong answers; the render is what makes a wrong answer obvious. Do
   this before writing a single label.
2. **Read `summary.segments` in segments.json, not the whole file.** The summary
   is the id / face_count / shape_hint / partner table. Pull the full record for
   a segment only when you are testing a specific claim about it. Never read
   `face_indices` - it is hundreds of thousands of integers and you never need
   them; `apply_plan.py` resolves ids to faces for you.
3. **Fix the orientation once, in one written sentence**, before any position
   reading (below).
4. **Know the filament inventory.** Up to 4, in independent nozzles. If the user
   has not said what is loaded, roll that into the single color question later -
   do not ask before the part list is settled.

## Orientation

`position` is `[x, y, z]` normalized 0..1 inside the model's bounding box, and
`axes` says what those mean **in the file**: `+Z` up, `-Y` front, `+X` right.
That is the print bed, not the creature. Models are routinely exported lying
down - the user's baby dragon is a flexi chain lying flat, head at the *low Y*
end, so "upper front third" in creature terms is low-Y, mid-Z in file terms.

Before labeling, decide from the preview and the bbox extents:

- which axis runs head-to-tail, and which end is the head;
- which axis is the creature's up.

Write it down in one sentence ("the chain runs along Y, head at low Y; the
creature's up is +Z"), then read every `position` through it. If the preview and
the numbers disagree about which end is the head, the preview wins.

## Naming features

Each claim below is a hypothesis with a kill condition. A label survives only if
the supporting evidence holds **and** the kill condition does not **and** the
preview shows it where you say it is. If a label fails, drop it and describe the
region structurally instead ("the raised band around the muzzle") - a plain
description is always better than a wrong body part.

| Feature | Claim it when | Kill it when |
|---|---|---|
| **Eyes** | `symmetry: paired`; `bbox_diagonal` under ~0.12 of the model diagonal; hint says `rounded ball`/`shallow dome`/`recessed`; sits in the forward, upper part of the head component; exactly one such pair on that component | No partner; three or more matching candidates; the pair sits on a component that is not the head; both candidates sit at the seam where two components interlock - flexi ball-joint sockets are small, paired, concave and thin-walled, and mimic eyes exactly |
| **Horns** | `taper <= 0.35` or hint says `tapering cone`/`long tapering spike`; `protrusion >= 0.8`; paired; upper or rear of the head component | Three or more evenly spaced along a line - those are spikes; unpaired on the midline front of the head - that is a nose horn, paint it with the horns; the region is an entire separate component in a chain - that is a link |
| **Spikes / ridge** | Three or more tapering protrusions, face counts within about 2x of each other, centroids marching monotonically along one axis | Face counts vary more than ~4x; the instances are scattered rather than in a line; they are on the underside - those are toes or a keel |
| **Claws / toes** | Small tapering protrusions in clusters of 3-5, mirrored left/right, at the low end of the creature's up-axis | Only one instance - call it a spur; the cluster is at the far end of the long axis instead - that is a tail tip |
| **Teeth** | Tiny tapering regions in a row, inside the head component's mouth opening; often `open_edges > 0` nearby | Not in a row; larger than the eyes - teeth are almost always the smallest named feature on the model |
| **Belly plates / scutes** | Hint says `flat plate`/`flat blade`; three or more with areas within ~2x; centroids marching along the long axis; all on one side | Areas vary wildly; only one plate; the plate has zero extent on an axis - that is a degenerate planar artifact, exclude it entirely |
| **Body / base** | `covers_component: true` on the largest-area region, or hint says `central mass` with `protrusion <= 0.3` | Nothing kills this one; if several components tie, the whole chain is body and every link takes the base color |

Known traps, all seen on real files:

- **Flexi joint sockets** score like eyes and like horn tips. They are interior
  surfaces nobody will ever see printed. If a candidate sits at the contact
  between two components of a chain, it is a joint.
- **Smooth-sculpted horns segment as tips only.** The base blends into the skull
  with no crease, so the region you get is the top 30% of the horn. Look at the
  preview: if the highlighted region is a tip, either accept it (a dipped tip is
  a legitimate and popular look) and say so in the reason, or paint the whole
  head component if that reads better. Do not pretend the whole horn is covered.
- **Degenerate planar patches** (an extent of 0 on some axis) are export
  artifacts. Never assign them.

Full field semantics, the shape-hint vocabulary, and the non-creature
vocabulary: `reference/reading-segments.md`.

## When the model is not a creature

The user prints brackets, boxes, terrain, signs, and mechanisms as well as
dragons. Fall back to structural naming when the model has no symmetric pairs
and no tapering protrusions, or when the preview plainly shows a manufactured
object, or when the user says what it is.

Structural vocabulary: **base/plinth**, **panel** (large flat face), **trim**
(narrow band along an edge), **text/emboss** (thin flat region raised off a
larger flat parent), **fastener/boss**, **mechanism** (interlocking separate
components), **inlay/logo**. Plans are then built on part separation and
contrast: text and inlays get the highest-contrast filament, trim separates
panels, the base takes the base color.

**Never hallucinate anatomy onto a bracket.** No eyes on a mounting plate.

## Confirm the part list

Before color, show the parts you named as a short indented list - names,
evidence, and how sure you are. Evidence is what makes the claim checkable:
paired, protruding, thin, where it sits, how big. Never ids, never coordinates.

```
  head
    L eye / R eye        paired, small, recessed          confident
    horns L / R          paired, tapering, top            confident
    nose horn            on the midline, front            likely
  body
    links 1-14           one per chain segment            confident
    two ribbed patches near the hips                      not identified
```

Regions you could not name are listed as "not identified" rather than folded
into the body. An unlisted region is the one the user notices missing.

Then iterate. The user corrects by name in plain language - "those aren't ears,
they're fins", "you missed the spikes down the tail", "merge the jaw into the
head". Answer every correction with an updated render, because a list read as
text is not the same as a list seen on the model. The loop ends when the user
says the list is right.

If the user says "just go", stop iterating and proceed with the list as it
stands, saying which parts you were unsure about.

## Color planning

The user has up to 4 filaments in **independent nozzles**. There are no swaps
and no purge tower, so using a fourth color costs nothing but travel - do not
minimize color count to "save" anything. Exactly the loaded set is available;
never propose a color that is not loaded.

Rules:

1. Largest-area region gets the base color, and that color is `default_filament`.
2. Reserve the highest-contrast filament for the smallest high-salience features
   - eyes, teeth, claw tips, text. Small regions need the biggest luminance jump
   to read at all.
3. Symmetric partners are identical. Always. Check every pair before emitting.
4. Two adjacent regions may share a color only when their shared boundary is a
   segmentation artifact. If it is a real feature boundary, sharing a color
   erases the feature - pick different filaments.
5. Thin geometry shifts color: a light filament over 1-2 perimeters reads
   translucent and picks up whatever is under it; dark filaments read darker and
   flatter on tips. Prefer saturated or dark filaments on tiny features, and
   avoid white or pale yellow on anything under about 2 mm thick.

Offer **2-3 distinct plans**, not one. They must differ in character, not in
detail - "natural", "high contrast", "single accent" are three different
answers to the same model. Contrast math, thin-wall behavior, and worked
examples: `reference/color-planning.md`.

## Asking about color

Once the parts are settled, ask about color **once**, or not at all. One message,
at most three named choices, each with a concrete option list. Then commit.

> The horns can go bone-white or gold, and the belly plates can match the horns
> or stay body color. Which do you want? If you have no preference I will use
> bone horns and body-color belly.

Never:

- ask a follow-up to an answer, or reopen the part list to fix a color;
- put coordinates, face indices, segment ids, or field names in anything the
  user reads - they approve by feature name;
- ask when the user has already told you the answer or said "just pick" - decide,
  state which plan you chose, and say why in one line.

## Output contract

Write plan JSON in exactly this shape:

```json
{
  "filaments": [
    {"index": 1, "name": "Black PLA", "hex": "#1a1a1a"},
    {"index": 2, "name": "Bone White PLA", "hex": "#e8e0cf"}
  ],
  "assignments": [
    {"segment_id": "s04", "filament": 2, "reason": "left horn, bone against the dark body"},
    {"segment_id": "s05", "filament": 2, "reason": "right horn, matches its pair"}
  ],
  "default_filament": 1
}
```

- `filaments`: index 1..4 in the user's loaded nozzle order; `name` and `hex` are
  both required and `hex` is the real filament color, since it drives the preview
  and the OrcaSlicer project config.
- `assignments`: `segment_id` must match an id in segments.json exactly.
  `filament` must be one of the listed indices.
- `reason` is required on every assignment and is written for the user, not for
  you: name the feature and the intent ("smallest feature, highest contrast").
  No segment ids, no coordinates.
- Segments with no assignment fall back to `default_filament`, so leave the base
  region unassigned. That keeps the painted-triangle counts in the summary
  meaningful.

Field rules, the validation checklist, and what each `apply_plan` error means:
`reference/plan-format.md`. A complete worked plan for the sample creature:
`reference/example-plan.json`.

## After writing the plan

Write each offered plan to its own file and render it (`preview.py ...
--plan plan-natural.json`). Read the contact sheets yourself first - they are how
you catch a segment that covers more than you thought - then show the user the
renders next to a one-line feature summary of each: "horns and claws bone, eyes
black, body slate". Rendering all the options is cheap and is what makes the
choice real; at the absolute minimum, render the one the user picks before
applying it.

Then run `apply_plan.py` on the chosen plan. If a render shows paint where you
did not intend it, fix the plan; do not explain the discrepancy away.

Later adjustments ("make the spikes filament 3") edit the plan and re-render.
Never re-run `segment.py` for a color change - the answer would be identical.
Re-run it only when the part list itself was wrong, and re-read the ids
afterwards if you changed any segmentation flag: ids are stable for the same
input and parameters, and only for those.
