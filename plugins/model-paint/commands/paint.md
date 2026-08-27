---
description: Paint an STL or 3MF for multi-filament printing - segment it in 3D, have vision agents name and color its features, limit the scheme to your loaded filaments, and write an OrcaSlicer-ready 3MF with the geometry unchanged
---

## Your task

The user wants a painted 3MF. The arguments they passed are: `$ARGUMENTS`

Accepted form:

```
/paint <model.stl|model.3mf> [--intent "a baby dragon"] [--size-mm 187]
       [--colors "black, orange, bone, grey"] [--palette mine]
```

If `$ARGUMENTS` is empty, ask for the path to the model and stop. Do not guess a
path and do not go looking for STLs on the machine.

Working paths, used by every step below:

- `<MODEL>` — the path they gave, resolved to an absolute path
- `<WORK>` — `<model-directory>/<model-stem>-paint/`, created if missing; the
  pipeline writes everything there (renders, the painted 3MF, `scheme.json`,
  `parts.npz`, cached vision answers), so a re-run is cheap and the user can
  delete one folder to clean up

## Step 1 — Validate the input

Check that `<MODEL>` exists and ends in `.stl` or `.3mf`. If it does not exist,
say so with the path you tried and stop. If it is some other format (OBJ, STEP,
Blender file), say the plugin paints STL and 3MF only and stop — do not convert
it, since converting is a geometry change.

Never modify `<MODEL>`. The pipeline reads it; nothing writes to it.

## Step 2 — Resolve intent, size and filaments

**Intent.** If the user did not say what the piece is, ask once — and ask for
a few SENTENCES, not a phrase: what the piece is, its notable features and
where they are, and anything easy to get wrong ("a one-eyed ogre bust — a
single central eye under the brow; the folds under the chin are jowls, not a
face"). Every sentence they give travels inside every judgement the agents
make, and the pipeline also studies the model itself and folds its own
identity dossier in — but the user's knowledge of their own model is the
cheapest, highest-value signal available. Pass it verbatim as `--intent`.
Never invent features they did not mention (asserting "tusks" on a model
without tusks sends the agents hunting for them).

**Size.** If they gave a printed size, pass it as `--size-mm` (the largest
dimension). If not, omit it — the pipeline infers from the file and flags the
guess; mention the flagged size when you report.

**Filaments.** The user prints with up to 4 filaments in independent nozzles.
Resolve the list before running, in this order:

- `--colors "black, orange, bone, grey"` — an explicit list, in nozzle order.
  Turn each name into `name:#RRGGBB` with a sensible real filament hex, and say
  which hex you chose for each so the user can correct you.
- `--palette mine` — read `~/.config/model-paint/filaments.json`, a list of
  `{"name": "Bone White PLA", "hex": "#e8e0cf", "nozzle": 2}` objects ordered by
  nozzle. If the file is missing, say so and fall back to asking.
- Neither — ask, once: which filaments are loaded, in nozzle order. Then offer
  to save them: "Want me to save these as your inventory so `--palette mine`
  picks them up next time?" On yes, write the file in the shape above.

Order matters twice: position is the nozzle index, and the **last** filament is
the default body filament. Put the user's most neutral/base color last unless
they say otherwise, and tell them you did. Cap at 4 entries unless the user
explicitly says their machine has more nozzles.

## Step 3 — Run the pipeline

One command does everything — 3D segmentation, agentic feature naming from many
rendered views, recovery of features the naming missed, an unconstrained color
design, limiting to the loaded filaments, a critic pass over the finished
renders, and the verified 3MF export:

```bash
python3 -m paintpipe.cli \
    --input "<MODEL>" --out "<WORK>" \
    --intent "<their words>" --size-mm <N> \
    --colors "<name:#RRGGBB, name:#RRGGBB, ...>"
```

Run it from `${CLAUDE_PLUGIN_ROOT}` (the `paintpipe` package lives there), in
the background, and tell the user what to expect: minutes to tens of minutes
depending on triangle count, because real vision calls are looking at real
renders. Relay progress from the log occasionally — the parts the vocabulary
found, the isolation table, the critic's verdict — rather than going silent.

## Step 4 — Show the result in the order the pipeline reasons

When it finishes, show renders from `<WORK>` in this order and say what each
one answers:

1. `continuous-hero.png` / `continuous-turnaround.png` — the unconstrained
   design: the honest test of whether segmentation and naming found real parts.
2. `final-hero.png` / `final-turnaround.png` — the same design limited to the
   loaded filaments, after the critic's overrides.

Also give the isolation table from the log in one or two sentences ("every part
came back as one or a few pieces" or naming the parts that scattered). Feature
names only — never atom ids, face counts, or file-internal keys. They approve
"the horns", not "atom 141".

## Step 5 — Report the export

From the log and `<WORK>/scheme.json`, report:

- The geometry line, **verbatim** — the pipeline prints
  `3MF IDENTICAL -- ...` after verifying base against painted. It is the
  guarantee the user cares about; quote it, do not paraphrase it into "all
  good". If it says DIFFERS, stop and show the detail — do not hand over the
  file.
- The part → filament mapping, with the critic's overrides called out.
- Where the file is: `<WORK>/painted.3mf`, absolute path.
- What to do with it: open in OrcaSlicer (File > Open Project, or drag onto the
  plate), check the filament assignment per nozzle, slice. The paint is in the
  project; no re-painting in the slicer is needed.

## Step 6 — Changes after the fact

"Make the eyes black", "swap the horns to orange" — re-map without re-running
any vision:

```bash
python3 -m paintpipe.cli --input "<MODEL>" --out "<WORK>" \
    --colors "<same list>" --repaint "eyes:black, horns:orange"
```

Seconds, not minutes: it reloads the run's saved parts, re-renders the final
views and re-exports the verified 3MF. Part names are the ones in
`scheme.json`; filament names are the ones from `--colors`. If the user asks
for a change to a part the run never found, say so instead of repainting a
different part.

## Failure handling

- If the pipeline exits nonzero, **stop** and show its error output.
- If a run finds no parts or the isolation table shows a part smeared into
  hundreds of pieces, say so plainly and show the atlas — do not present a bad
  segmentation as a good paint job.
- Never hand-edit the 3MF XML, the paint strings, or
  `Metadata/project_settings.config` to work around a failure. A file that
  opens in the slicer but carries paint you wrote by hand is exactly the
  failure this plugin exists to prevent.
- Never re-mesh, repair, simplify, weld, rescale, re-center, or convert the
  model to make a step succeed. The pipeline's own validation repairs
  (winding, shared vertices) never move a vertex; anything beyond that is out
  of scope. A guardrail hook blocks these operations anyway; treat a block as
  correct, not as an obstacle to route around.

## Notes

- `${CLAUDE_PLUGIN_ROOT}` is set by Claude Code to this plugin's root.
- `--no-vision` runs segmentation only and writes an atom atlas — useful to
  sanity-check a model quickly; no painting happens, because naming is an act
  of looking and has no honest deterministic stand-in.
- Vision answers are cached in `<WORK>/vision/`, so an interrupted run resumes
  cheaply with the same command.
- The output is a 3MF project, not a mesh export. The original STL or 3MF is
  untouched and stays printable on its own.
