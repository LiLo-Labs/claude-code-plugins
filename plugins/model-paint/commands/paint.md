---
description: Paint an STL or 3MF for multi-filament printing - segment it, name its features, plan colors against your loaded filaments, and write an OrcaSlicer-ready 3MF with the geometry unchanged
---

## Your task

The user wants a painted 3MF. The arguments they passed are: `$ARGUMENTS`

Accepted form:

```
/paint <model.stl|model.3mf> [--colors "black, red, bone, gold"] [--palette mine] [--style natural|contrast|accent]
```

If `$ARGUMENTS` is empty, ask for the path to the model and stop. Do not guess a
path and do not go looking for STLs on the machine.

Working paths, used by every step below:

- `<MODEL>` — the path they gave, resolved to an absolute path
- `<WORK>` — `<model-directory>/<model-stem>-paint/`, created if missing
- `<OUT>` — `<model-directory>/<model-stem>-painted.3mf`

Everything intermediate (segments, plan, previews) lives in `<WORK>` so a re-run
is cheap and the user can delete one folder to clean up.

## Step 1 — Validate the input

Check that `<MODEL>` exists and ends in `.stl` or `.3mf`. If it does not exist,
say so with the path you tried and stop. If it is some other format (OBJ, STEP,
Blender file), say the plugin paints STL and 3MF only and stop — do not convert
it, since converting is a geometry change.

Never modify `<MODEL>`. Every script below reads it; nothing writes to it.

## Step 2 — Resolve the filament palette

The user prints with up to 4 filaments in independent nozzles. Resolve the list
before any color reasoning, in this order:

- `--colors "black, red, bone, gold"` — an explicit list, in nozzle order. Turn
  each name into a `{index, name, hex}` entry: index is its position in the list
  (1-based), `hex` is a sensible real filament color for that name. Say which
  hex you chose for each so the user can correct you.
- `--palette mine` — read `~/.config/model-paint/filaments.json`. It is a list of
  `{"name": "Bone White PLA", "hex": "#e8e0cf", "nozzle": 2}` objects; `nozzle`
  becomes the filament index. If the file is missing, say so and fall back to
  asking.
- Neither — ask, once: which filaments are loaded, in nozzle order. Then offer to
  save them: "Want me to save these as your inventory so `--palette mine` picks
  them up next time?" On yes, write `~/.config/model-paint/filaments.json` in the
  shape above, creating the directory if needed.

Cap the palette at 4 entries, since that is the nozzle count. If the user hands
you more, say you are using the first four and ask them to reorder if that is
wrong — unless they explicitly say their machine has more nozzles, in which case
use what they gave.

`--style natural|contrast|accent` is a preference for which plan to lead with in
step 5, not a filter. Still show the alternatives.

## Step 3 — Segment the model

`segment.py` writes into `<WORK>` but does not create it, so make it first:

```bash
mkdir -p "<WORK>"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/segment.py" --input "<MODEL>" --output "<WORK>/segments.json"
```

Show the user the summary the script prints — object and triangle counts, the
component count, and the per-segment lines. That output is already written for a
person; do not restate it as numbers of your own.

## Step 4 — Show the segmentation before reasoning about color

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/preview.py" --input "<MODEL>" --segments "<WORK>/segments.json" --output "<WORK>/preview-segments"
```

Read `<WORK>/preview-segments/segments-contact-sheet.png` yourself, then show it
to the user and ask whether the segmentation found the real features. This
confirmation happens *before* any labelling: a color plan built on a
segmentation that split the tail into nine pieces is wasted work, and the user
can see that in one glance.

If the segmentation plainly missed features, re-run step 3 with a lower
`--concave-angle` (25, then 20) or a smaller `--min-faces`, and show the new
contact sheet. Say what you changed and why.

## Step 5 — Label the anatomy and offer plans

Use the **model-paint** skill for this step. It carries the feature-naming rules,
the flexi traps (joint sockets score exactly like eyes), the contrast math, and
the plan JSON contract.

Produce **2-3 plans** that differ in character, not in detail. Present them by
feature name with a one-line reason each:

> **Natural** — body slate, horns copper, eyes black. The horns read by shape,
> so the color stays quiet.

Rules for what the user sees:

- Feature names only. Never show segment ids, triangle indices, face counts,
  coordinates, or field names from segments.json. They approve "the horns", not
  "s04".
- Say when a feature you expected is not there ("I do not see separate claws on
  this one") rather than inventing a segment to hold it.
- Ask at most one question, and only if a real choice is open. If the user said
  "just pick", pick, name the plan you picked, and say why in one line.

## Step 6 — Write the plan and render it

Write the chosen plan to `<WORK>/plan.json` in the shape the skill specifies
(`filaments`, `assignments` with a `reason` on each, `default_filament`), then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/preview.py" --input "<MODEL>" --segments "<WORK>/segments.json" --plan "<WORK>/plan.json" --output "<WORK>/preview-plan"
```

Look at `<WORK>/preview-plan/plan-contact-sheet.png` before the user does. If
paint landed somewhere you did not intend, fix `plan.json` and re-render — do not
narrate the discrepancy and carry on. Then show the contact sheet and get final
confirmation.

## Step 7 — Apply

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/apply_plan.py" --input "<MODEL>" --segments "<WORK>/segments.json" --plan "<WORK>/plan.json" --output "<OUT>"
```

Add `--force` only when overwriting an output from an earlier run in this same
conversation.

Then report to the user:

- The script's final confirmation line, **verbatim**, e.g.
  `geometry unchanged: 1 object(s), 2016 triangles, geometry and placement identical`.
  It is the guarantee they care about; quote it, do not paraphrase it into "all
  good".
- The per-filament triangle counts the script printed.
- Where the file is: the absolute path of `<OUT>`.
- What to do with it: open it in OrcaSlicer (File > Open Project, or drag it onto
  the plate), check the filament assignment per nozzle, and slice. The paint is
  in the project; no re-painting in the slicer is needed.

## Step 8 — Changes after the fact

If the user asks for a change — "make the spikes filament 3", "swap the eyes to
black", "leave the belly body-colored" — edit `<WORK>/plan.json` and re-run from
step 6.

Do **not** re-run `segment.py`. Segmentation is deterministic and depends only on
the mesh, so re-running it produces byte-identical output and costs the user
minutes on a large model. The segment ids in `plan.json` stay valid for as long
as `<MODEL>` is unchanged.

## Failure handling

- If any script exits nonzero, **stop** and show the user its error output. The
  scripts are written to print actionable messages; the message is the answer.
- Never hand-edit the 3MF XML, the paint strings, or `Metadata/project_settings.config`
  to work around a failure. A file that opens in the slicer but carries paint you
  wrote by hand is exactly the failure this plugin exists to prevent.
- Never re-mesh, repair, simplify, weld, rescale, re-center, or convert the model
  to make a step succeed. If the model cannot be segmented or painted as it is,
  say so and stop. A guardrail hook blocks these operations anyway; treat a block
  as correct, not as an obstacle to route around.
- If `apply_plan.py` reports a geometry mismatch it deletes its own output. Report
  that as-is and stop.

## Notes

- `${CLAUDE_PLUGIN_ROOT}` is set by Claude Code to this plugin's root directory.
- Steps 3 and 4 are deterministic: same model, same segments, same PNGs. Only
  steps 5 and 6 involve judgment, which is why the previews exist.
- The output is a 3MF project, not a mesh export. The original STL or 3MF is
  untouched and stays printable on its own.
