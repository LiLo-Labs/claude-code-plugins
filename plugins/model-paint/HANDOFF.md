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

## Measured: the scale ladder, and why one scale can never work

**Different features need opposite ends of the ladder.** Same tolerance, same model,
one click each, resolved at 400 / 800 / 1600 / 3200 / 6400 / 12800 patches
(`scripts/scale_ladder.py`, one contact sheet per click):

| feature | best rung | what the other end does |
|---|---|---|
| barnacle band, front left flank | **400** (coarsest) | 12800 shatters across the whole model |
| barnacle colony, upper whorl | **12800** (finest) | 400 selects only part of the colony |

That is a complete inversion, and it is the reason the fixed-scale trial gave seven
clicks in ten. There is no single correct patch count: the default 2,500 was about
six times too fine for the flank band, which is exactly why that click ran away to
29.75%. At its own rung the same click gives **0.94%** and covers the band cleanly.

**Area cannot pick the rung.** On the flank ladder 400 gives 0.94%, 1600 gives 0.32%
and 6400 gives 0.30% — all inside the sensible band, and only 400 is the whole
feature; the others are fragments of it. The rung has to be chosen by looking, which
is what the contact sheet is for and what vision is genuinely better at than any
statistic available here.

**Monte Carlo consensus was the wrong instinct for the same reason.** It averaged
over the ladder instead of choosing a rung, so a barnacle field and the rib beside it
came out as something that is neither. It did clear the trial by area — both runaways
gone, 13 of 13 sensible, 0 failures, from a baseline of 2 — but the renders showed
the runaways had become *wrong and small* rather than right. Kept
(`mc_select.py`, `mc_trial.sh`) because small-and-wrong is correctable by a human
where 30% is not, and because its coherence statistic still flags bad selections.

## Depth: absolute bands work, per-contact steps do not

The worst leaks ran from a feature on the shell down onto the rock base. Blocking
contacts with a large height step **did not stop them**: at 6,400 patches the largest
height gap anywhere on the model is 4.07mm and the 99th percentile 2.15mm, so a 5mm
gate blocked nothing and the selection walked down one small step at a time.

This is the ensemble edge wall's failure again — *any* per-edge test is defeated by a
gradual slope — and predicting otherwise was a mistake made twice in this project.
The rule that survives both: **absolute constraints measured from the exemplar hold;
per-edge constraints do not.** No chain of small steps can carry a patch outside a
fixed distance.

`--band-drop-mm 12` took the leaking rung from **9.64% to 1.80%**, removed the base
rock from every rung, and left the already-clean rungs alone (12800: 1.61% → 1.55%).

## Superseded: Monte Carlo consensus, and what it did and did not fix

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
*coherence* — separates what area cannot. Every one of the 13 was scored and 9 were
then inspected, chosen to attack the claim: the highest unverified scores first
(where a false positive would show) and the lowest (where a false negative would).

| coherence | selection | what the render shows |
|---|---|---|
| 0.58 | mid flank rib band | one clean colony, boundary on its edge |
| 0.56 | upper whorl colony | one clean colony, boundary on the rib |
| 0.51 | barnacle boulder | core clean, but real spill onto the rock base |
| 0.25 | crack-line network | one fragment of one plate, not the network |
| 0.21 | front left flank | cracked plate *and* barnacles, ragged |
| 0.20 | lower right of coil | speckle across three different features |
| 0.18 | ribbed limpet caps | **inconclusive** — selection sits over the horizon |
| 0.06 | torn break edges | fragments along crack lines |
| 0.03 | cluster below coil | umbilicus plus speckle over base rock and coral |

**No false negatives.** Nothing scoring low turned out to be a clean feature, which
is the failure that would have sunk it. The separation is not perfectly sharp: 0.51
is usable but spills, so the honest reading is a *ranking* — trust it above ~0.5,
distrust it below ~0.25 — rather than a clean cut with a single correct threshold.
Four were not inspected (0.16, 0.15, 0.07, and the 0.18 whose view was useless), so
this is 9 of 13, not 13 of 13.

So the pipeline can now tell a human *which selections not to trust*, before any
paint — which is what the human-in-the-loop step in `docs/agentic-process.md` needs.
`mc_select.py` prints it and warns below 0.35.

**Two things to be honest about.** The threshold does heavy lifting: the good colony
covers 37.21% of the surface at p>=0.3 and 2.11% at p>=0.5, so the draws disagree a
great deal and 0.5 is load-bearing. It is at least a principled default (a majority)
rather than a tuned one. Coherence is now checked on 9 of the
13 rather than assumed, but 4 were never looked at and one of those nine gave a
useless view, so it is a supported ranking rather than a calibrated threshold.

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

## The abstract method

**`docs/labelling-method.md`** now states the labelling loop independently of any
model: which steps are mechanical, which three judgements a human must make by
looking, how a child level's rung is derived from the region's own scale profile
rather than passed in, how the partition stays total and disjoint including the
10.72% of shell faces no camera can see, and how a label gets a coordinate that is
valid in the view that sees most of it.

What changed: three independent implementations of level 0 were written and
adversarially cross-checked, all three beat the recorded confetti failure on the
shell (smooth-panel dominance 0.38 → 0.68 at k=6, touching-pair disagreement
0.77 → 0.48, confirmed by looking), and subdividing a coherent parent at its own
computed rung produced the best result in the project — the barnacle apertures
isolated across the whole model at rung 12,800, chosen by the region rather than by
a person.

What is still open: nothing produces the same partition twice (reseed ARI 0.130 on
the dragon, 0.193 on the shell, landmark grouping at chance), unifying the panel
costs the ribs (panel/rib cluster overlap 0.54 → 0.88), region count is unsolved and
dominates every comparison (on the repeated-part falsifier the *unmodified baseline*
scores 3/4 at k=4 and 0/4 at k=10), and one new hard rule was paid for: a stability
metric is not evidence until a deliberately worthless control has lost to it — the
reseed-ARI falsifier used to defend the best feature space is won by clustering
patch-centroid XYZ, 0.487 to 0.293.

## The scale-space index — a coordinate that is not the tessellation's

Every descriptor this project clustered on was a statistic of the SLIC patch a face
landed in, which is why nothing reproduced: patch elongation correlates 0.26 with
itself under a mere reseed. `scripts/scale_space.py` replaces that with a quantity of
the *surface*, measured in millimetres.

Difference-of-Gaussians on the mesh. Diffusing the face-normal field is a random walk
on the face graph, so t rounds of neighbour averaging reach a geodesic radius of about
sqrt(t) x mean edge; dispersion of the smoothed normal says how much the surface turns
inside that radius. Dispersion only ever rises with r, so it cannot state a size — its
derivative across log-radius can, peaking at the radius where the ball first contains
the whole feature. That is Lindeberg's characteristic scale, and the same reason SIFT
seeks extrema across scale rather than within one.

**It is reproducible by construction.** No seed, no patches, no rung anywhere in it —
only vertices, faces, adjacency and normals. Two runs are bitwise identical, and two
models are comparable because the radii are millimetres rather than patches. This is
the property three separate level-0 designs failed to obtain by clustering.

Measured on the shell (626,766 faces, mean edge 0.259mm, 14 radii from 0.39 to 22.04mm,
about four minutes):

- The characteristic-scale render separates what k-means could not. The smooth whorl
  bands and ridges — the exact surface that shattered into confetti across nine
  clusters — come out as **one coherent band**, with barnacle cups, coral whips and
  rosette pleats each at their own scale. Looked at it; it is not subtle.
- Asking for one size surfaces that size everywhere at once. `--peaks 1.0` selects
  9.82% of the area and is, visually, every barnacle throat on the model — on the shell
  and on the reef both — plus the crack network, the crust-break facet edges and the
  rosette's pleat grooves. Nothing was clicked.

**This is what makes rounds overlayable.** A face's characteristic scale is a number in
millimetres attached to that face, not to a run, so passes at different rungs, with
different clicks, in different sessions can be laid on top of each other and compared.
A patch label can never do that: patch 40 of one run has nothing to do with patch 40 of
the next.

### The coverage failure this exposes is structural, not perceptual

In the see-label-paint run the seeing agent DID name the umbilical rosette, with
coordinates, and all three labelling crews still walked past it — it was recovered only
by the residue sweep, which then needed three attempts to select it. The crews were
split by scale with nothing forcing every named feature to be labelled or explicitly
abandoned. The lesson is that the residue render must be the DRIVER, not a cleanup
phase: begin at 100% unlabelled and carve, and finishing while a coherent residue
component remains must be impossible rather than merely discouraged.

### Scored honestly, and a correction

Dominant-class share of each class's area, on the 66 visually-verified ground-truth
patches. Every row below is from a run that actually wrote its label file:

| class | k=10 baseline | scale index (size) | size x form |
|---|---|---|---|
| smooth panel | 19% | **33%** | 25% |
| rib | **80%** | 38% | 27% |
| barnacle | 52% | **56%** | 25% |
| coral | 43% | 48% | 30% |

**The size axis is a real but partial gain.** It roughly doubles the panel — the
surface that shattered across nine clusters with no k that could hold it — and costs
more than half the ribs, because a whorl ridge and the flat band beside it are the
same size and size alone cannot separate them.

**The form axis, done correctly, makes everything worse.** Signed relief was first
computed as a raw offset, which on a globally convex shell reads every face as a
ridge: it labelled 89% of the panel a ridge, 58% of the ribs flat, and found no
grooves at all. Band-passing it — the face's offset minus the offset two radii
coarser — removes the global bulge and is the semantically right quantity, and it
turns out to carry almost no class information at all: area-weighted mean by class is
-0.025 panel, -0.027 rib, -0.015 barnacle, -0.019 coral, four numbers that are the
same number. A clean ablation at fixed bands and floor gives 32/33/41/48 with the axis
off and 25/27/25/30 with it on.

**A correction, and the method error behind it.** An earlier version of this section
claimed the panel reached 75% and that the failure was fixed. It was not. Those scores
were read from a stale `scale_labels.npy`: the label build had been piped through
`head`, which killed it with SIGPIPE before it wrote its output, so the scorer read the
previous run's file. Two published numbers, both wrong, both flattering. Never pipe a
script that writes files through `head`, and when a changed input produces byte-identical
scores, that is the bug, not a robustness result.

**Where this leaves the index.** The scale-space index is still the only quantity here
that is reproducible by construction, and the characteristic-scale render still
separates barnacle cups, coral whips and rosette pleats from the smooth body by eye.
But as a basis for an automatic partition it is, measured, a trade rather than a fix:
panel and rib remain in tension exactly as three earlier designs found, now from the
other direction. What it is genuinely good for is `--peaks`: asking for one size and
getting every instance of it on the model at once.

## The foundation rework: boundaries from the index, not the tessellation

Every selection this project made snapped to SLIC patches, and that is the defect under
all the rest. SLIC seeds evenly and grows compactly, so on a sculpted surface its cell
walls land wherever the seeding put them rather than on the edge of anything. Two
consequences, both measured: cell-shape statistics reproduce at r=0.26 under a reseed
so nothing built on them survives re-tessellation, and a selection can only be as clean
as the cells it is assembled from -- which is why the painted renders show sawtooth
colour edges running across the middle of a smooth surface.

`scripts/index_regions.py` stops snapping to cells and segments the scale-space index
itself. Edge weight between two touching faces is how differently the surface behaves
at each: the gap in characteristic scale (in log-radius, since scale is
multiplicative), the gap in band-passed relief, and the dihedral turn between them.
All three are geometry in millimetres, so the graph is identical every time.

The merge is Felzenszwalb-Huttenlocher, chosen for the reason it was invented: it
adapts its threshold per region rather than applying one everywhere, so a smooth panel
can be one large region while a barnacle field a millimetre away stays many small ones.
That is precisely the panel-versus-rib tension that defeated every fixed-threshold
attempt in this project. It is also seedless -- sorting edges is the only ordering it
needs.

**Measured on the shell, k=40.** 368 regions over 626,766 faces, median 698 faces,
largest 8.91% of area, and 21 regions holding half the surface. Contrast SLIC, which
forces near-equal areas (max/min 1.95) and so structurally forbids a large region -- the
reason the smooth body was the thing that always shattered.

**Bitwise deterministic, verified rather than argued**: two runs produce identical
label arrays, 368 regions both times. The reseed test that killed three level-0 designs
does not apply, because there is nothing to reseed.

**What the render shows**, which is the part that matters: each whorl ridge is ONE
continuous region along its whole sweep; every barnacle cup is individually bounded on
its rim; each coral whip is one region along its full length; the faceted plates inside
the crust breaks follow the actual facet edges; the rosette's pleats group as a fan.
The boundaries are on the features. Inter-rib bands come out as separate regions
divided along the ridges, which is correct rather than fragmentation.

This is a substrate, not a part list. Naming, grouping into classes, and the hierarchy
still sit on top -- but they now sit on boundaries that are the surface's own.

### Classes on top of the substrate

`index_classes.py` groups the deterministic regions into classes so a plan can address
"the barnacles" rather than 43 individual cups. Three numbers per region and only
three: its size in millimetres, its band-passed relief, and its area share. Shape
descriptors are deliberately absent -- they were the measured noise last time (patch
elongation r=0.26 under reseed, 22.3% of the force that shattered the panel), and the
region boundaries already carry the shape that mattered.

Shell, 6 classes over 368 regions, looked at rather than tabulated:

| class | area | what it is |
|---|---|---|
| teal | 17.0% | every barnacle cup on the model, shell and reef both |
| green | 5.0% | the faceted plates inside the crust breaks, and the rosette pleats |
| red | 5.1% | the torn crust-break lips |
| magenta | 4.0% | fine detail and cup throats |
| orange | 1.8% | every coral whip |
| blue | 67.1% | all the smooth large surface |

Barnacles as one class everywhere and coral whips as one class everywhere is the thing
every previous attempt failed at.

**The honest flaw is blue.** It merges the shell body with the reef rock, and no
geometric index can separate them: at this scale they are the same size and the same
flatness, and they differ by material, which geometry does not measure. Splitting that
class by height gives 39.14% reef and 27.98% shell body, so the separation is trivially
available -- but height is a property of THIS model sitting this way up, not a general
rule, and hardcoding it would be exactly the subject-specific shortcut the process doc
forbids. The general answer is the one the pipeline was already built around: a class
splits into connected instances, and a human names them. Geometry proposes; a person
says which lump is rock.

### Many angles, many scales, voting on the mesh

`view_evidence.py` renders the model from every direction in the atlas and, for each
pair of faces that touch on the MESH, accumulates how strong a visible edge runs
between them in the image. `index_regions.py` adds that to its geometric edge weight.

**This is not the recorded render-space dead end.** That failure segmented images and
fused the result back to triangles, which shatters at five pixels per face. Nothing here
segments an image. Each view only contributes evidence about a 3D quantity that already
exists, and the decision is taken on the mesh. One view answers badly -- the pair may be
edge-on, shadowed, occluded, or three pixels wide -- which is exactly why one view was
never enough. Thirty-two answer well, because those failures are per-viewpoint and
independent while a real crease is visible from most directions that can see it at all.

Scale enters the same way: gradients at full resolution find the creases between
barnacle cups, and the same gradients after blurring find the broad edge where a ridge
meets a panel while ignoring the texture inside both. Three blurs are kept separate and
combined by maximum, so a pair counts as an edge if it is visible at SOME scale rather
than at the one that happened to be chosen.

Measured on the shell, 32 directions at 900px:
- Evidence is normalised per observation, so a pair seen from twenty angles is not
  ranked above an equally sharp one seen from three merely for being easier to look at.
- **19.82% of pairs are never observed from any direction.** They contribute nothing
  rather than a zero -- scoring them edge-free would quietly merge every enclosed cavity
  into whatever surrounds it. This is the pair-level counterpart of the 10.72% of faces
  no camera can see.
- Adding it: 368 regions to 402, and the largest region falls from **8.91% to 4.93%** of
  area. The oversized merged region was being held together by geometry blurring across
  an edge that is plainly visible from most angles.

Geometry and the camera fail in different places -- geometry measures surfaces no camera
can see, the camera notices edges geometry blurs across -- which is the only good reason
to combine two signals rather than pick one.

### More angles do not fix a boundary that emits no signal

The claim worth testing was that enough rotations, scales and zooms would leave no
segmentation error. Tested by tripling the camera directions, 32 to 96, at 1200px:

| | regions | area in regions straddling rock and shell | largest such |
|---|---|---|---|
| 32 views | 402 | 11.51% | 3.23% |
| 96 views | 454 | **16.14%** | **5.26%** |

Detection improved exactly as predicted -- faces seen from no direction fell 10.72% to
2.66%, pairs never observed 19.82% to 5.47%, median 28 views per pair. And the material
merge got **worse**. Sharper evidence on the visible edges let the adaptive threshold
tolerate more internal variation elsewhere, so regions merged more freely across the one
junction that shows nothing. More angles photograph the same absence of an edge more
times. Detection was never the problem.

Two limits, and neither is fixed by looking harder:
- **A boundary with no edge.** Shell meets reef tangent, same brightness, no crease.
  Nothing to find at any resolution from any direction.
- **An edge with no boundary.** Every wrinkle on the rock is a real edge and more views
  confirm it harder, pushing toward over-segmentation. Which real edges are PART
  boundaries is a question of meaning, not of evidence.

### The design cut: draw the boundary, leave the mesh alone

`design_cuts.py` invents the boundary instead of hunting for it. Two points picked on a
rendered view define a plane swept along that view's axis -- the slice every 3D tool
offers -- and a person or an agent looking at the render places it in one gesture, along
the waterline where rock becomes shell, where no measurement can.

**Nothing touches the mesh.** A cut only reassigns which named part a triangle belongs
to; vertices, triangle indices and build placement are untouched, and the paint codec
then preserves them byte-for-byte. That is what makes an invented boundary safe on
interlocking flexi models: the design lives in the label, and a label is only ever a
colour.

Demonstrated on the case that motivated it. One line drawn on the front view split the
67% merged class into **reef rock 30.61%** and **shell body 36.52%**, verified by
looking: blue covers the reef and every coral runner on it, orange the shell above.

### The barnacle defect was a missing parent, and the fix is nesting

Painted, the colonies came out looking damaged: rims one filament, the throats inside
them another. Measured, **120 of the 254 regions touching the barnacle class were split
between classes and only 53 sat wholly inside one** -- 47.2%.

The boundaries were not the problem. A cup is genuinely a rim, a wall and a throat at
different characteristic scales, and the region step is right to separate them. The
defect was that classing assigned every region INDEPENDENTLY, so one cup's own parts
scattered, with nothing in the data saying they were the same cup.

`index_hierarchy.py` merges twice. The first pass groups faces into regions. The second
runs the same adaptive agglomeration again over those regions, weighted by the strength
of the border between them, and a cup falls out as one object -- because the border
between a rim and its own throat is weak next to the border between the cup and the
shell it sits on. A third pass groups objects into fields.

Two details that were wrong before they were right:
- `felzenszwalb` divides k by node size, so a node standing for hundreds of faces needs
  k scaled by the mean node size at that level. Unscaled, k=60 against a 900-face region
  is a threshold of 0.067 and NOTHING merged: level 1 came out with the same 1797 nodes
  as level 0.
- Border strength is the MEAN of the mesh edges crossing it, not the minimum. One weak
  edge along a rim is not evidence the rim is not a boundary, and the minimum lets a
  single soft pixel dissolve a clean edge.

Shell, levels k=15/21/60: 1797 sub-features, 121 objects, 47 groups. **Nesting verified
rather than assumed: 0 of 1797 children straddle a parent, at both steps.**

**The repair, measured.** Class the OBJECTS instead of the regions and sub-features split
across classes falls from 120 to **0** -- and by construction, not by tuning: a child is
wholly inside its parent, so it inherits its parent's class and cannot be voted on
separately. Looked at level 1: each barnacle colony is one solid object, rims and
throats together, the shell body one object, the reef one, the rosette one, each coral
whip its own.

This is also what makes "all barnacles orange" and "their throats black" two statements
about different levels of one tree rather than two claims competing for the same
triangles.

**Still broken at this level:** clustering 121 objects on three numbers puts 94.71% of
the area in one class. The hierarchy is sound; the classing that sits on it is not, and
was tuned for 368 regions rather than 121 objects. Do not paint from it until that is
redone.

### Objects choose their own scale: persistence over the merge tree

Levels handed in by hand (k=15, 21, 60) are the same defect as a chosen segmentation
rung, one level up. A cup, the colony it belongs to and the shell they sit on are
objects at three different sizes; no single level holds all three, and a level tuned on
one model means nothing on the next.

`index_persist.py` chooses nothing. It merges every region from the weakest border to
the strongest, keeps the whole tree, and asks of each node how long it SURVIVES: a cup
forms when its rim joins its throat and lasts until the colony absorbs it, because
nothing nearby is as similar to it as its own parts are, while a meaningless
intermediate is born and absorbed almost at once. Persistence is measured in log of
border strength, because these strengths are multiplicative exactly as the radii of the
scale index are.

Selection is the antichain problem -- a set with no ancestor among its members, so the
result is a partition -- solved exactly, bottom up: take a node whole, or take the best
selection among its children, whichever scores higher, scored by persistence times area.

**Three assumptions had to be removed before it worked, each caught by the run.**
- The root was given a hardcoded lifetime and beat every real object: **1 object, 100%
  of the surface**. The root survives to the top by definition, so any persistence it
  has is an artefact of the tree ending. It is now never selectable.
- The floor was a percentile. It is now the weakest border actually present, and the
  ceiling the strongest, both read off this model -- so persistence is measured against
  the range of borders this surface has rather than a number meaning something else on
  the next model.
- Leaves were treated as born at zero, which made every leaf look immortal and returned
  **1,776 objects of one leaf each**. A leaf is not born at zero: it was built by
  merging faces, and its birth is its own internal variation, the strongest border
  already inside it. That is FH's Int(C), read off the same weights.

Shell: 1,797 leaves, 3,593 tree nodes, **963 objects at mixed scales**, up to 35 leaves
each, 26 objects holding half the surface. Looked at it: whole whorl ridges are single
objects in the same partition as individual barnacle cups, each cup whole with its rim
and throat, the rosette one object, every coral whip its own.

**Still hand-set, and named as such:** `--base-k` and `--min-faces` for the leaf regions.
Everything above them is derived. And the classing that turns objects into named classes
is still the layer that does not work -- 94.71% of area in one class at the previous
level -- so this is not paintable yet.

### The naming agent corrected the class names, and most of them were wrong

A naming agent read the class renders and overturned three of the four descriptions
that had been carried forward on this page, plus found a fourth thing nobody had:

| class | called | actually is |
|---|---|---|
| class-2 | "every barnacle cup" | **flat pocket faces** — break plates, the mouth fan, cup bowls AND smooth panels. At least four materials in one class. |
| class-3 | "plates and the rosette" | **crease slivers** — thin strips down coral-whip flanks and along crack edges |
| class-4 | "every coral whip" | **cup throats** — the open mouth inside each barnacle ring |
| class-1 | "shell body + reef rock" | **three things**: shell 30.0%, reef 19.2%, and the flat underside 17.9% |

**17.90% of this model is the flat, never-visible face it stands on** — verified
independently here: normals below -0.9 in z, sitting at the minimum z. More than a sixth
of the surface, which no render can ever show and which should never be painted at all.
A hand-built part map called 100% of it "reef rock".

**So the four colour schemes rendered earlier were painted on wrong labels.** What was
coloured as "barnacle colonies, 17.01%" was flat pocket faces; the barnacles that looked
broken in those renders were not a segmentation artefact in the colonies at all -- they
were a class that was never the colonies. Those renders are not evidence of anything and
the areas quoted with them are wrong.

**A process failure caused a second problem.** `index_regions.npy` was rewritten from
368 to 402 regions while the naming agent was reading it, so every region id in its
split lists refers to the old file. The agent caught this itself, by noticing an area
recomputation contradicted its own earlier table, and said so rather than reporting
ids that no longer mean anything. Region 340 was 8.91% of the model before the rewrite
and 0.065% after. Do not act on those ids without regenerating the classes against the
current regions file. Shared session state must be treated as immutable while any agent
is reading it.

The lesson is the same one this page keeps recording: the class layer proposes geometry,
and only looking says what a class contains. Three of four descriptions survived several
rounds of being repeated here because nobody had opened the renders and checked them
one class at a time.

## End to end: three printable 3MFs, geometry verified

The pipeline ran start to finish on the shell without a human choosing a name, a level,
or a colour. `scale_space` -> `index_regions` -> `index_persist` (963 objects at mixed
scales) -> classes -> an agent naming every class by opening its render alone -> a
verified 12-part map -> three colour schemes -> `apply_plan` -> 3MF.

**12 parts, exact partition**: 626,766 faces, 626,766 written, 0 claimed twice, 0
missing, areas summing to 1.000000000000. The underside is its own part and takes the
default filament: 17.89% of the surface that is never painted because no camera can
ever see it.

**Three files, each verified against the source STL by `verify.py`:**
`shell-reef.3mf`, `shell-ink.3mf`, `shell-bone.3mf`, ~13.75 MB each, all reporting
*IDENTICAL: same triangles, same bodies, same placement* -- 626,766 triangles,
1,880,298 vertices, 1 body, bbox [75.6, 58.4, 55.0] mm.

**The naming agent earned its place again.** It found that classes 0 and 1 are the same
feature -- barnacle cones -- split by a hard height cut near z=22mm, and likewise 7 and
2 (throats), and that the same cut divides the shell itself between class 4 and class 3,
so no class equalled "the shell". None of that is visible in any metric in classes.json;
it only appears when each class is isolated and looked at. It also refused a
`design_cuts` plane on class 3, because rock, weed stalks and the shell's lower band
interleave in height on every side, so no plane separates them.

**The height cut is the next defect.** Clustering included normalised height as a
feature, which splits every repeated feature into an upper and a lower copy. Removing
it is the obvious next change, and the reason it was there -- to isolate the underside --
is better served by the measured underside test that already exists.

### Classing by what a thing IS: height out, parent-relative elevation in

Giving every feature type one colour and looking at all six views exposed three
identification defects, all of them classification errors sitting on correct
boundaries.

**Height split every repeated feature in two.** It was a clustering feature, so the
barnacle cones above z=22mm and the identical cones below became two classes, as did
their throats, as did the shell itself -- no class equalled "the shell". Height is not a
property of what a thing IS; a cup is a cup on the crown or at the foot. Removed. The
one job it did, isolating the underside, is now done by measurement: downward normals at
the model's lowest extent, invisible from every direction.

**The underlayer exposed inside a break could not be separated from the outer shell.**
Same material, same size, same flatness -- nothing measured at its own scale
distinguishes them. What does is that one is a step BELOW its surroundings and the other
IS the surroundings. `object_classes.py` adds **parent-relative elevation**: an object's
offset measured at the scale of the thing it sits on (default 4x its own), normalised by
its own size. Positive stands proud (a barnacle on a shell), negative is recessed (an
underlayer revealed by a break, a groove floor), zero is the surface. That is the
generic three-way split between applied, revealed and base, and no earlier feature set
could express it. It required keeping the whole offset ladder in `scale_space.npz`
rather than only the value at each face's own scale.

**An over-reaching class cannot be fixed by choosing k**, since raising it re-cuts every
good class too. `--split <class>` re-clusters within one class only.

Measured on the shell, 963 objects into 8 classes plus the hidden underside:
- **The height duplication is gone.** Barnacle cones are one class across the whole
  model, crown and reef alike, in all six views. Same for their throats.
- **The revealed underlayer separates**, as a class the algorithm itself labels
  *recessed*.
- **Shell and rock merged into one 53.30% class, exactly as predicted.** Height was the
  only thing separating them. This is honest rather than broken: they differ by
  material, which geometry does not measure, and `design_cuts.py` is the tool for it.
  An honest merge plus a drawn boundary beats a fake separation that duplicates every
  other feature.
- **New defect: "recessed" over-merges.** One class holds both the break interiors and
  the valleys between ribs. Both are genuinely recessed; they are not the same thing.
  That is what `--split` is for.

The remaining errors are now concentrated in two named classes instead of smeared
across all of them.

### Two opposing invariants, because one of them certifies nothing

Eight agents each rendered one class alone across six views and found a defect no class
map shows: **identical adjacent instances were landing in different classes.** Two
barnacle cones in the same chain, one class 0 and the next class 2. Four neighbouring
rosettes across three classes. Adjacent identical rib grooves alternating stripe by
stripe. One continuous crack running through four classes. One agent's verdict: the
class was "a fragment skimmed off five different feature populations".

That is not a class holding two things, and no amount of splitting repairs it. It is a
fixed-k cut passing through the middle of a dense population.

**The obvious fix was measured and was worse.** Replacing k-means with adaptive
merging in feature space took twin agreement from 92.6% to 100% -- and the render showed
one class swallowing 51% of the model, barnacles and rock and coral together. A single
all-consuming class scores 100% on a twin test. That is the same trap an earlier agent
caught in this project when a worthless geographic-wedge space beat a real one on a
stability metric: **a test a worthless answer passes cannot certify a good one.**

So two invariants, always measured together, over pairs of objects that touch on the
mesh:
- **twins** -- near-identical in feature space -- MUST share a class (54 pairs)
- **distinct neighbours** -- far apart in feature space -- MUST NOT (1,021 pairs)

| | classes | twins | distinct | balance | largest |
|---|---|---|---|---|---|
| graph merge, s=4.0 | 27 | 100.0% | 63.9% | 0.779 | 51.0% |
| graph merge, s=3.2 | 30 | 100.0% | 84.4% | 0.916 | 36.5% |
| k-means k=12 | 12 | 92.6% | 99.6% | 0.960 | 38.4% |
| **k-means + twin repair** | **12** | **100.0%** | **99.6%** | **0.998** | **38.7%** |

Merging fixed four twin pairs and broke about a hundred and fifty distinct ones. The
repair keeps the cut that separates well and fixes only where it violates the other
invariant: a disagreeing twin pair is pulled onto whichever class carries more surface,
until nothing moves. **Four objects of 962 moved.** Nothing else changed.

`enforce_twins()` in `object_classes.py`, on by default.

### Stop partitioning. Point at one thing and find the rest.

The colours in a class render are class ids from a palette and mean nothing else, which
is why "some barnacle colonies are a different colour from others" was the right thing
to notice. The cause, measured: the proud classes sit at 1.83, 2.14, 2.50, 3.42 and
6.36mm, and real barnacle cones run about 1.5-4mm. **One population is cut across four
classes by size.** It is the height defect again on a different axis.

Every repair made it worse or moved it:
- twin repair only compares TOUCHING objects, so identical cones in different colonies
  are never compared and never fixed
- adaptive merging reached 100% on the twin test by swallowing 51% of the model
- dropping a feature traded the defect for another: same-kind-elsewhere agreement
  97.4% -> 94.8%, largest class 38.7% -> 26.0%

The pattern is not a bad algorithm. It is the wrong question. "How many kinds of thing
are on this model and where are the boundaries between them" is not answerable from
geometry, because it is semantic. A partition must put a boundary somewhere, and a real
population is a continuum with nowhere good to put one.

`object_select.py` asks a different question. Point at one barnacle; it returns every
object like it, anywhere on the model, and renders the answer so the radius can be
adjusted by looking. Nothing is partitioned. Objects nobody claims stay unclaimed and
appear in the residue instead of being swept into a nearest class, and it reports the
distance to the next unselected object so the next step is visible rather than guessed.

Demonstrated on the shell from one click: radius 0.5 gives 30 objects (0.75%), 0.9 gives
97 (2.88%), 1.4 gives 234 (7.48%). At 1.4 every colony on the shell and the reef is
covered -- and it has begun leaking into crack lines on the rock, which is a judgement
from the picture and not from any number in the table.

This is the same shape as the rest of the pipeline: geometry proposes, vision decides.
k-means is retained only as a proposal to look at, never as the answer.

### "Some colonies are white, not red" — traced two levels down

Correct observation, and the cause was not where I kept looking.

**Level one: the size feature did not measure size.** `log size` was the median
`characteristic_mm` of an object's faces and it was the dominant feature. Measured on
four barnacle cups whose physical extents are 1.6, 1.1, 1.0 and 3.7mm, it returned
0.99, 3.42, 2.50 and 1.83mm -- not merely noisy, in the WRONG ORDER. Characteristic
scale measures how fast the surface turns nearby, which depends on how tightly cups are
packed and how deep each throat is, not on how big the thing is. Two identical cups in
different colonies were therefore far apart in feature space, which is why whole
colonies came back unselected while their neighbours matched. Now measured directly as
the object's own extent in millimetres. Cheap, robust, and it means what its name says.

**Level two, and the deeper one: objects are not consistently whole features.** The
exemplar click landed on a 2mm object that is not a cone but a fragment between cones,
so the selection returned the matrix BETWEEN the cups rather than the cups. Measured
across all 963 objects, extent spans **0.87mm to 94.95mm, a factor of 109**, with 66
objects holding 65.3% of the area and 358 objects in the 2-4mm band. Persistence picks
each object at the scale where it is most stable, which is right in principle and means
in practice that one cup can be one object while its neighbour is three -- a rim, a
wall, a throat.

No similarity search fixes that. Pointing at a cone and asking for things like it cannot
match a cone that was never assembled into a single object. The hierarchy built by
`index_hierarchy.py` does assemble them -- 0 of 1797 children straddle a parent -- so the
selection should run at the level of that tree where a click's object is a whole
feature, choosing the ancestor whose extent matches what was pointed at, rather than on
the flat antichain `index_persist.py` emits.

That is the next change, and it is stated here rather than attempted so the reasoning is
not lost: **selection must be able to walk up the hierarchy from a click, not just
outward through a flat list.**

### Selection walks up the tree, and matches on shape alone

Three failures in a row, each fixed by removing an assumption rather than tuning one.

**A flat object list cannot answer "select all the barnacles".** Persistence picks each
object where it is most stable, so one cup is one object while its neighbour is three --
a rim, a wall, a throat. Extent across the 963 objects runs 0.87mm to 94.95mm, a factor
of 109. A click lands on whatever fragment happens to be under it: pointing at a colony
returned the matrix BETWEEN the cups, because the object under the cursor was a 2mm
sliver and not a cone at all. No similarity search repairs that -- a cone that was never
assembled into one node cannot be matched at any radius.

`hierarchy_select.py` searches the whole merge tree instead of one antichain through it.
Every grouping the border strengths support is a node somewhere: the rim, the cup, the
colony, the whorl. A click prints its ancestor chain with each step's extent and area
share, so the step that is the WHOLE thing is chosen by reading rather than guessed.
Matches are kept maximal, so a cup and its own rim are never both returned.

**Size must not be in the signature.** A barnacle is a barnacle at 1mm or 5mm, so
matching on absolute size guarantees one population splits by size -- which is exactly
what the cones did across 1.83, 2.14, 2.50 and 3.42mm. Building a scale-invariant index
and then matching on absolute scale throws the invariance away. The signature is now
aspect ratios, relief already divided by the object's own scale, and the shape of the
scale-space response sampled at FRACTIONS of the object's own extent. Absolute extent is
used for one thing only, and never for matching: lining exemplars up with each other.

**"up N" is not comparable between clicks.** The tree is deeper under a crowded bed than
under an isolated bump, so one --up 4 gave a 5.81mm cup at one exemplar and a 19.57mm
shell band at another, and that single bad exemplar dragged the whole selection onto
rock. The first click now sets the size of the thing being pointed at and every other
click walks to whichever of its OWN ancestors is closest to it.

**And the failure that mattered most was mine, not the code's.** Every attempt above was
run on pixel coordinates I picked without opening the image; one landed on smooth shell
rather than a cup and poisoned the match. Selection quality is bounded by whether the
exemplars are actually on the feature, which is a thing only looking establishes. The
agent instructions now require verifying each coordinate against the render and
reporting which were replaced.
