# The agentic process

What the loop has to be for this to come out right. Every rule below was paid for
by a failure recorded elsewhere in these docs; none is a preference.

The short version: **vision drives, tools serve, nothing is believed without
looking, and every failure adds a generic primitive to the library.**

## 1. Vision is the driver, not the checker

The instinct is to compute features deterministically and have a model name what
was produced. That fails outright on real models. Crease segmentation put 625,884
of the shell barricade's 626,766 triangles into one region — a model asked to name
that output can only name a blob.

Invert it. The agent looks first, decides what it is looking at, and *then* reaches
for whichever measurement serves that intent. Thickness, roughness, cavity, relief
and crease are instruments, chosen per feature, not a fixed pipeline.

## 2. Identify the subject before measuring anything

One agent reads the views and states what the object is, then derives the
vocabulary for its parts **from what it sees**. That vocabulary is passed to every
later agent as a prior they are explicitly told to disagree with.

Never borrow a checklist from another kind of model, and never force anatomy onto
an object that has none. On the shell this produced "umbilicus", "limpet", "shell
shard", "faceted inner panel" — none of which any hardcoded list would have held.

The identify pass must also state what it *cannot* make out. Those become the
regions a later pass looks at more closely.

## 3. Lenses are structural, never subject-specific

Survey agents work through lenses that apply to any object: the dominant form,
things standing off it, applied surface detail, negative space, whatever it stands
on, and a sweep for what the others missed. A lens that finds nothing says so.

A workflow whose lenses hunt "barnacle clusters" is a script for one model. It was
written that way once and thrown away.

## 4. Boundaries come from over-segmentation, not thresholds

Do not grow selections from a seed by thresholding a signal. The boundary lands on
a contour of whatever was measured, which is not the edge of the thing: measured
results included smearing across ribs, missed limpets beside selected ones, and a
seed reaching 6.9% of the model at the tightest usable tolerance.

Instead tile the surface into patches whose edges already sit on real
discontinuities (`paintlib/mesh_slic.py`), then treat patches as the atoms.
Selection becomes "which of these belong together", and the boundary is correct
before anything is painted.

Segment the **mesh**, not a render of it. Render-space segmentation produces
beautiful superpixels and then dies fusing back to triangles: 626k triangles at
1600px is five pixels per face, the per-face vote flips between viewpoints, and the
surface shatters. The mesh is in memory. Use it.

## 5. Ensembles vote on evidence, they do not decide by majority

Run the segmentation many times across seeds and scales, because a patch scale is a
zoom level and a real edge survives all of them.

But agreement is evidence, not a rule. Merging pairs that agree produced one patch
covering 89% of the model — disagreements are scattered and never close into
curves, so a merge rule leaks until everything connects. Feed agreement in as an
edge *cost* instead.

And check what the statistic actually measures. "How often were these together" is
dominated by the coarsest runs; with a sweep part-way through, 0.0% of pairs fell
below the blocking threshold and the ensemble changed nothing. The informative
question is inverted: **the coarsest scale at which two faces come apart.** Low
number means a major edge.

## 6. Every selection is verified by looking at it

An agent that selects without reading the highlight render it produced has not
verified anything. This is a hard requirement in the workflow prompts, and the
"verified" field must describe what the image actually showed.

The same applies one level up: after a selection pass, render coverage and look.
A roughness audit once reported 0.23% of the surface unclaimed while two entire
barnacle colonies sat unselected. A metric answers the question it encodes; only
the picture asks whether the question was right.

## 7. The part map must be a partition

Independent selections overlap and leave gaps — measured: 24.61% of the surface in
no part, 26.86% claimed by two or more, one region contested by six. Painting from
that pile means whichever selection was written last wins.

Resolve to one label per triangle (`resolve_parts.py`): specific beats general,
and gaps are filled by the nearest part across the surface. Never by a single
global fallback — that painted 42% of the rock base as shell.

## 8. Identification is confirmed with the human before any colour

The user's own correction, and it reordered the pipeline. Arguing about colour is
wasted if the part list underneath is wrong.

Detect, propose a named part list with evidence, then **iterate with the human until
the list is right** — rename, merge, split, add what was missed, show me part 7 —
answering each with an updated render. Regions that could not be identified are
listed explicitly as "not identified" rather than folded quietly into the body.
Only then does colour begin.

Corrections are by name. Coordinates never appear in anything shown to the user.

## 9. Colour is aesthetic, so it is judged by eyes

A scoring function can tell you a plan is illegible. It cannot tell you it is ugly.
Ranked top by contrast and chroma: an orange shell on a white rocky base — a
traffic cone. Rock wants to look like rock, and no metric in the plugin knows that.

So: generate candidates, render them, and have visual critics judge with distinct
lenses — material plausibility, legibility at a metre under room light, colour
harmony. Hard markers. Every problem must be visible in the image and describable;
every suggested change names the part, the filament and the cut value.

Use depth. Recesses read as shadow, so inside goes darker than outside; a flat
colour per part is the thing this pipeline exists to get past.

## 10. Agents extend the library when they hit a gap

When a selection cannot be made with the tools available, the answer is a new
**generic** primitive committed back to `paintlib/`, with a test, not a one-off
script. That is how the library grew `relief()` (a lone dome that roughness and
creases both miss), `--connect radius` (a clump of separate bumps), `--max-span-mm`
(a stud is not a ridge) and `clean_labels()`.

Each of those exists because something failed and the failure named the missing
tool. The next model gets them for free.

## 11. Report failures with the measurement that found them

State what did not work, with numbers, before stating what did. "F1 went from 42.2%
to 44.3%" is a result; "the ensemble helped" is not. When a comparison flatters the
work — the barnacle "truth" was itself ragged, so precision was understated — say
so rather than lean on it.

Never claim something works because a metric improved. Look at it.

## What "perfect" means here

One command, one model, and the user sees: a correctly identified subject, a part
list they can correct by name, colour options that read as a painted object rather
than a fill, and a 3MF whose geometry is provably byte-identical to the input.

The gap between here and there is one number: **one click currently gives the right
feature about seven times in ten.** See `HANDOFF.md` for what is measured, what is
in flight, and the dead ends already closed.
