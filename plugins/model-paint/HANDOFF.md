# model-paint — handoff

Read this first, then **`docs/agentic-process.md`** — the loop this has to run as,
with the failure behind each rule — then `docs/segmentation-findings.md` and
`docs/orca-format.md`.
Everything below was measured on real models, not assumed. Where a number appears,
it came from a run; where something failed, the failure is recorded so it is not
repeated.

## What this plugin is for

A 3D printing hobbyist runs one slash command on an STL or 3MF and gets back a
painted 3MF ready for OrcaSlicer, using four filaments in independent nozzles.
Claude finds the features on the model — eyes, horns, barnacles, coral, cracked
panels, whatever the model actually has — and assigns colours to them. The user
has been doing this by hand-prompting for roughly six hours per model.

The user's setup, read out of their own project file: **Flashforge Creator 5 Pro,
four independent 0.4mm direct-drive nozzles, `single_extruder_multi_material: 0`**.
No tool changes, no purge tower, so exactly four colours are available and the
count is a hardware fact rather than a preference. Their loaded filaments are
white `#FFFFFF`, black `#000000`, orange `#FF8000`, grey `#808080`
(`samples/filaments-example.json`).

## The one rule that cannot be broken

The user prints interlocking flexi models. **Geometry must never change.** No
re-meshing, decimation, vertex merging, repair, rescaling, recentring, or boolean
ops. Painting adds `paint_color` attributes and nothing else. Placement counts as
geometry: a model that comes back rotated is a changed file.

This is enforced mechanically, not by good intentions:

- `paintlib/threemf.py` paints by surgical text edit, never by parse-and-reserialize,
  so vertex coordinates and triangle order survive byte-for-byte.
- `geometry_matches()` compares vertices, triangle indices AND build placement.
- `apply_plan.py` deletes its own output and exits nonzero if that check fails.
- `hooks/` blocks mesh-mutating Bash commands, including `cp`/`mv` over a model.
- Any analysis that needs welded vertices does it on an in-memory copy. Face count
  and order are preserved, so index `i` still means triangle `i`.

Verified end to end on the user's real 43MB Orca project: geometry and placement
identical, all 473,556 triangles outside the edit unchanged, 27 archive entries
preserved with no non-mesh entry modified.

## What works, with evidence

**The paint codec.** Ported from OrcaSlicer's `TriangleSelector::serialize()` before
any real file was available; the user's genuine painted project then decoded
exactly — `4` → filament 1, `8` → filament 2, `1C` → filament 4. No changes needed.
See `docs/orca-format.md`.

**3MF I/O**, including the production extension (`3D/Objects/*.model`), which is how
Bambu Studio and OrcaSlicer write real projects. Object ids are unique only within
a part, so everything resolves on `(part, object_id)`.

**Orca project settings.** `project_settings.config` holds 672 keys. The plugin
understands about eight, so it patches and writes the rest back. Two facts learned
from the real file and easy to get wrong: the default filament is an **object
property** (`extruder` in `model_settings.config`), not paint — unpainted triangles
print in it, so painting all four colours explicitly is wasted work; and
`filament_multi_colour` mirrors `filament_colour` and is what the slicer draws the
plate from, so out of step it shows old colours over correct paint.

**Surface over-segmentation** (`paintlib/mesh_slic.py`). SLIC's formulation run on
the face graph: seed evenly, grow by a cost trading distance against how much the
surface turns, iterate, re-seed at centroids. On the 626,766-triangle shell:
**2,500 patches, median 240 faces, largest 0.07% of area, zero single-face patches,
65 seconds.** Visual check shows each barnacle cone as its own patch with the
boundary on its rim.

**One-click local selection** (`patch_select.py --grow local`). Click one patch,
spread to touching patches that resemble it. One click selected an entire barnacle
colony — 49 patches, 2.08% of surface, stopping at the rib — and it is the first
selection in this project whose boundary needed no cleanup afterwards.

## Measured: Monte Carlo consensus, and what it did and did not fix

Run on the shell, 13 clicks, against the baseline below. Both runaways are gone —
**29.75% → 2.76%** and **16.12% → 2.25%** — and by area the trial is **13 of 13
sensible, 0 failures**. `experiments/mc_trial.sh`, `scripts/mc_select.py`.

**The area metric is not sufficient, and looking says so.** Of the five selections
inspected, the two former runaways are now *wrong and small* rather than wrong and
huge: one is a mixture of cracked plate and barnacles, the other speckle scattered
across the umbilicus, the coral and the rock base. Both sit in the sensible band.
A small wrong selection is correctable by a human and a 30% one is not, so this is
real progress — but it is not "one click gives the right feature".

**The useful finding is a second statistic.** Area at p>=0.7 over area at p>=0.5 —
*coherence* — separates what area cannot. Verified against the renders, n=5:

| coherence | selection | looks like |
|---|---|---|
| 0.58 | mid flank rib band | one clean colony, boundary on its edge |
| 0.56 | upper whorl colony | one clean colony, boundary on the rib |
| 0.21 | front left flank | cracked plate *and* barnacles, ragged |
| 0.20 | lower right of coil | speckle across three different features |
| 0.06 | torn break edges | fragments along crack lines |

So the pipeline can now tell a human *which selections not to trust*, before any
paint — which is what the human-in-the-loop step in `docs/agentic-process.md` needs.
`mc_select.py` prints it and warns below 0.35.

**Two things to be honest about.** The threshold does heavy lifting: the good colony
covers 37.21% of the surface at p>=0.3 and 2.11% at p>=0.5, so the draws disagree a
great deal and 0.5 is load-bearing. It is at least a principled default (a majority)
rather than a tuned one. And n=5 renders is a hypothesis about coherence, not a
result; the other 8 were scored but not inspected.

## The earlier open problem, and the wall that did not fix it

**A fixed tolerance does not generalise across feature types.** The trial:
13 features, one click each, tolerance 0.30 (`experiments/click_trial.sh`).

| outcome | count | examples |
|---|---|---|
| sensible (0.4–3.3% of surface) | 9 | colonies, cracks, limpet caps, apertures |
| runaway | 2 | "front left flank rib band" → **28.06%**; "barnacle boulder" → 8.48% |
| collapsed | 1 | "shell-to-base undercut" → 1 patch, 259 triangles |

So roughly seven clicks in ten give the right thing. That is the number to beat.

**The diagnosis is scale, not threshold.** A patch scale is a zoom level: at 400
patches a whole rib is one object, at 13,000 a single cone is several. A feature is
only cleanly separable near its own scale, so segmenting at one scale and hoping
one tolerance covers everything is the mistake.

## Two experiments were in flight when this paused

Both were running as background jobs and **their outputs live in an ephemeral
scratchpad that is now gone**. The scripts are preserved; re-run them.

1. `experiments/ensemble10x.py` — 60 runs across 10 scales (400 → 13,000), six
   repeats each, accumulating per-adjacent-pair agreement. Reached run 35/60.
   Writes `support10x.npy` incrementally. **Superseded — see the statistic below.**
2. `experiments/edgestrength.py` — 8 coarse scales (250 → 4,600), three repeats,
   recording **the coarsest scale at which each pair comes apart**. Reached 18/24.
   Writes `edge_strength.npy`. Now takes `--session`, so it no longer points at the
   dead scratchpad path it was written against; it could not be re-run until that
   was fixed.

The second exists because the first's statistic is flawed, and this is the most
important thing to understand before continuing:

> "How often did these two faces land in the same patch" is dominated by whichever
> scales are coarsest. Cut a model into 400 pieces and nearly every adjacent pair
> lands together, so agreement sits near 1.0 whether or not there is an edge
> between them. Measured: with the sweep part-way through, **0.0% of pairs scored
> below the 0.5 blocking threshold**, so `--respect-support` blocked nothing and
> all 13 selections came out byte-identical.
>
> The informative question is inverted: **at what coarsest scale do they separate?**
> A crease between a barnacle field and its rib splits them even at 400 patches,
> because no sensible coarse cut spans it. A boundary appearing only at 13,000 is
> the segmentation running out of things to divide. **Low number = major edge.**

## Next steps, in order

Steps 1 and 2 below are **built but unmeasured**: the code is written and unit
tested, and neither has been run on the shell, because the model is not in the repo.
Nothing here is evidence the approach works — that is step 3, and it is blocked on
the user's file.

**Superseded by the Monte Carlo result above.** Steps 1 and 2 were built and are
kept because the measurement they produced is what ruled the approach out: the edge
wall blocked 339 of 7,281 contacts (4.66%) at its default against a patch graph of
mean degree 5.8, and growth routed around it. Cutting a scattered subset of edges
never closes a curve, so it cannot bound a region. Do not revisit it. Step 3 is
done; the live question is now the coherence statistic and the threshold.

1. ~~Re-run `experiments/edgestrength.py` to completion.~~ **Runnable now.** It took
   a `--session` argument and lost the hardcoded scratchpad path. Not yet run on the
   shell:

   ```bash
   python3 experiments/edgestrength.py --session work/
   ```

   It prints, and logs to `<session>/edgestrength.log`, what share of pairs separate
   at each scale. **Read that before trusting anything downstream**: if nearly every
   pair separates at 250, the sweep is too fine to be discriminating, which is the
   same failure `support10x` had in the other direction.

2. ~~Feed `edge_strength.npy` into `patch_select.py --respect-support`.~~ **Done.**
   `--respect-support` (a 0..1 agreement fraction) is replaced by `--respect-edges`
   (a patch count, default 1000), and the comparison is inverted: growth is blocked
   across a contact whose strength is **at or below** the threshold, i.e. one a
   coarse segmentation already draws. Low number = major edge.

   The per-contact statistic is the **median** over that contact's face-pairs, not
   the mean: pairs that never separate carry infinity and a mean would return
   infinity for any contact with one. `support10x.npy` is no longer read at all.

   The growth logic came out of `main()` into `patch_contacts()` and `grow_local()`
   so it can be tested — `tests/test_select.py`, 12 tests, including one that pins
   the direction of the comparison. That test exists because getting the direction
   backwards fails silently: growth still works, selections still look plausible,
   and the wall is simply never there.

3. **Re-run `experiments/click_trial.sh`** and count failures. Success is fewer than
   2 of 13, ideally 0. Report the number honestly either way. **This is the step
   that decides whether any of the above helped, and it needs the shell model.**
   Nothing above has been measured on it.
4. If that works, **re-run the visual agent workflow** (`workflows/visual-paint.js`)
   on this substrate. Every previous agent run was fighting ragged threshold blobs;
   agents can now click features by name with correct boundaries. This is also where
   the coral finally gets separated properly — see below.
5. Then paint plans, critique, and the HIL loop, which are already designed
   (`docs/interaction-model.md`).

## Known dead ends — do not repeat these

- **Threshold-grown selections on raw faces.** `--grow rough` floods: an encrusted
  field is continuous in roughness even where a person sees separate clumps. A seed
  in one clump reached 6.9% of the model at the tightest usable tolerance.
- **Crease-bounded detection on sculpted models.** Returned *zero* candidates on the
  shell. Nothing sculpted has a crease ring; that is what sculpted means.
- **Render-space segmentation.** Superpixels on rendered images do snap to visible
  edges beautifully, but fusing back to triangles hits a wall: 626k triangles at
  1600px is ~5 pixels per face, the per-face vote flips between viewpoints, and the
  surface shatters (60% in one patch, 77% single triangles). Do not "fix" this by
  rendering bigger. The mesh is in memory; segment it directly.
- **Merging on ensemble agreement.** Produced 280 patches with one covering 89% of
  the model. Disagreements are scattered and never close into curves, so a merge
  rule leaks until everything connects. Use agreement as an edge *cost*, not a rule.
- **Global class matching** (`--grow class`). One click on a cone scored F1 35.0%,
  worse than unsupervised k-means at 44.3%. Six shape descriptors are noisy at the
  scale of one patch and a global threshold scatters false positives. Kept and
  documented; not the default.
- **A single global fallback for unassigned faces.** Sent 42.4% of the base to
  "shell body". Use `--fill nearest` (already the default in `resolve_parts.py`).

## Reproducing the working state

First check the ray backend, because getting this wrong wastes an afternoon:

```bash
python3 -c "import trimesh; print(type(trimesh.creation.icosphere().ray).__module__)"
```

`trimesh.ray.ray_pyembree` is right. `trimesh.ray.ray_triangle` is the pure-numpy
fallback trimesh drops to when `embreex` is missing, and it is silent — everything
still works, just far slower. Views are ray-traced one ray per pixel, so on a fresh
container without `embreex` a seven-view session on the 2,016-triangle fixture went
from seconds to minutes, and `test_paint.TestProjection` ate 16 GB and was
OOM-killed. `pip install embreex` fixes both. `rtree` is also needed, or the
thickness tests error out.

```bash
cd plugins/model-paint
python3 -m unittest discover -s tests -p "test_*.py"     # 79 tests, all passing

# Build a session for a model (renders 7 views, caches every signal, ~15s):
python3 scripts/inspect_model.py --input <model.stl> --output work/

# Over-segment the surface (~65s on 626k triangles):
python3 scripts/oversegment.py --session work/ --patches 2500

# Measure edge strengths, so growth can stop at major edges (slow -- 24 runs):
python3 experiments/edgestrength.py --session work/

# Click a feature:
python3 scripts/patch_select.py --session work/ --at iso:562,247 \
    --grow local --tolerance 0.30 --name "barnacle colony"
# then LOOK at work/selections/*.png before trusting it
```

`oversegment.py` reports the patch count, median faces per patch and largest patch
share it actually produced. A largest-patch share of more than a percent or two
means the segmentation failed to divide something, and every selection built on it
inherits that.

The only end-to-end run of this chain so far was on `samples/creature.stl`, and it
is worth being precise about what it did and did not show. Same click, same
tolerance 0.50: with `--respect-edges 240` the selection was 5.09% of the surface;
with `--respect-edges 0` it ran away to 48.4% and tripped the `--max-share` guard.
So the wall is real and load-bearing, which is more than the old `support10x`
statistic ever managed — it measurably blocked nothing.

**That is a wiring check and nothing more.** The click landed on the fixture's bare
sphere flank, where there is no feature to bound, so the boundary it stopped at is
arbitrary rather than correct. Looking at `selections/t1-iso.png` shows a ragged
blob on smooth surface, which is exactly what the fixture is expected to give and
exactly why the fixture is not evidence. The method is unmeasured until the click
trial runs on the shell.

## Test models

**They are in the repo** under `samples/`, at the owner's direction — see
`samples/TEST-MODELS.md` for attribution, per-file provenance, and the reference
measurements to check a run against.

- `samples/creature.stl` is generated by `tests/make_fixture.py`. **It is too easy.**
  Its horns are cones stuck on a sphere, so they have crease boundaries the free
  signal finds. It hid a real failure once already; never treat passing on it as
  evidence a method works.
- `samples/baby-dragon.stl` — 475k triangles, 29 separate bodies, sharp eye creases.
  The easy real case.
- `samples/scallop-shell-barricade.stl` — 626k triangles, **one single connected
  body**, sculpted, nothing crease-bounded. The hard case. Any new method must be
  checked on this one.
- `samples/baby-dragon-painted-v3.3mf` — a real OrcaSlicer project, ground truth for
  the file format and the user's printer profile.
- `samples/baby-dragon-repaired.stl` — the dragon after a third-party repair, kept
  as a counter-example: not the same geometry as the original.

## How the user works

They are technical, they look closely at renders, and they will spot a missed
feature before any metric does. Several of the biggest corrections in this project
came from them: that colour choice is aesthetic rather than a scoring problem, that
identification needs a human-in-the-loop step before colouring, that agents must be
generic rather than written around one model, and that segmenting the mesh directly
beats segmenting a picture of it.

Show renders, not just numbers. State failures plainly with the measurement that
revealed them. Do not claim something works because a metric improved — look at it.
