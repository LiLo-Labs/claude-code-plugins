# paintpipe

Implementation of the agentic paint-scheme pipeline, specification v0.2.

Built to the spec's invariants rather than around them:

- **I1 appearance is primary.** Every cue descends from a render buffer. `hit_id` is a
  routing key and never evidence. The mesh is a ray target and an export target.
- **I2 no dimensional constant in source.** `policy.py` holds the only literals and all
  of them are dimensionless. Millimetres enter from the object, the painter's hardware
  or the viewing condition, and nowhere else.
- **I3 scale is a query parameter.** The label field is continuous; consumers state the
  radius they are asking at.
- **I4 zoom belongs to a camera, scale to the object.** They meet only through GSD.
- **I5 every belief carries its evidence.** The evidence layer is append-only.
- **I6 the object defines its own detail bands.** Nothing chooses how many there are.
- **I7 everything has an identity.** Including rejections.

## Measured deviations from the spec

Both are stated here because a silent deviation is worse than a documented one.

**§4.3 band derivation uses the screen-space half only.** The spec forms the cue energy
spectrum from heat-kernel-smoothed mean curvature *and* screen-space cavity response.
Mean curvature is a property of the tessellation as much as of the shape, so including
it puts a tessellation-dependent term into the ladder that every band and every derived
length rests on. That contradicts I1 and would fail the tessellation-independence gate
in §13 -- the gate that proves the appearance-first claim. The screen-space half is the
half that satisfies I1 and it is sufficient.

**§5.3 GSD is derived for an orthographic camera.** The spec's formula
(`depth * pitch / focal`) is written for a perspective camera. Under the orthographic
projection used here the footprint does not vary with depth, so the same quantity is
`footprint / cos(incidence)` -- still per-pixel, because incidence is per-pixel, which
is the part that carries the meaning.

## Known limitation, with evidence

`§4.3 step 4` declares a band at a local maximum of added cue energy. Verified by
rendering the cue maps at each candidate scale on `baby-dragon.stl`:

| scale | what the cue map actually shows |
|-------|---------------------------------|
| 1.02mm | crisp outlines of every individual spike -- the edge scale |
| 3.55mm | each spike filled solid -- the scale at which a spike is one object |
| 9.06mm | mush; spikes blur together and the head saturates |

The method finds 1.02mm and correctly rejects 9.06mm, which is not a band but the scale
at which structure dissolves. It **misses 3.55mm**, which is a real structural scale
lying on a monotone shoulder of the response rather than on a peak. Peak-finding cannot
see a shoulder. This is a limitation of the spec's rule on objects whose detail scales
are adjacent rather than separated, and it is recorded rather than patched: a
shoulder-detector tuned until one model produced the expected number of bands would be
fitting the method to the model.

## Bands found, no per-model tuning

| model | bands |
|-------|-------|
| `scallop-shell-barricade.stl` | 8.26mm, 0.61mm |
| `baby-dragon.stl` | 1.02mm |
| `creature.stl` | 6.72mm |

## Input validation is a stage, not an assumption (§4.1 step 1)

`validate.py` checks and repairs every input before anything reasons about it. It was
promoted to a stage because its absence produced a confidently wrong answer, and the
failure mode is the dangerous kind: **the renders look correct while every quantity
derived from the same mesh is wrong.**

Every model in the sample set failed the orientation check:

| model | bodies | wound inward |
|-------|--------|--------------|
| `scallop-shell-barricade.stl` | 1 | 1 |
| `baby-dragon.stl` | 29 | 26 |
| `creature.stl` | 5 | 5 |

STL stores no winding guarantee and no vertex sharing. The rasteriser flips a normal
toward the camera per pixel, so pictures render correctly regardless -- which is exactly
why this hid. Only surface-space uses of a normal expose it, and they fail hard:

- View planning aims a camera "along the normal" of an unseen point **into the object**.
- A ray cast to ask whether a point can see out hits the model immediately. The shell
  measured as **99.97% occluded from every direction**, contradicting its own renders.
  After repair the same test returns **99.18% reachable, 0.82% genuinely enclosed.**

Orientation is verified by **per-body signed volume**, not by agreement with the outward
radial direction. The radial test is a poor proxy on anything non-convex: the correctly
oriented dragon reads 56.7% agreement, because a spike under the tail really does point
away from the centroid. It must be per body, too -- a print-in-place model has no single
volume whose sign means anything.

The repairs obey one rule: **vertex positions and face order never change.** Welding and
re-winding alter connectivity and orientation, which geodesics and view planning need,
while a face keeps its index so `hit_id` still routes a belief to the original file's
triangle and the exported mesh stays the one the user supplied. Degenerate faces are
therefore reported and never removed -- deleting one renumbers every face after it.

## Coverage: 30 overlaps per area, and visibility measured not assumed

The predicate has two halves and a point must pass both: at least `min_samples` (30)
admitted observations, and at least `incidence_bins` distinct viewing-angle bins. Thirty
looks from one direction are one look repeated -- they share every systematic error that
direction has -- so count and spread are separate requirements.

Direction bins are the six faces of a cube: the signed dominant axis. An earlier version
combined an octant with a dominant axis and took it modulo the bin count, which collided
constantly, so genuinely different views were recorded as the same view and coverage
stalled at a third with no indication why.

## Convergence: two remedies, because the deficit has two causes

The coverage predicate needs at least `min_samples` observations EVERYWHERE. Each round
therefore does two things, and measurements showed either alone fails in its own
direction:

| strategy | result on `scallop-shell-barricade.stl` |
|----------|------------------------------------------|
| wide views only | stalls at 0.59 of visible area; ~8% never admitted at all |
| zoomed views only | median samples runs to 116 while coverage **falls** to 0.36 |
| both | 0.34 → 0.60 → 0.72 → 0.76, p10 samples 8 → 16 → 30 → 46, unseen 16.7% → 4.7% |

Wide views are what lift everyone's sample count; only a view that sees everything can.
Zoomed views fix the tail wide views cannot: surface reachable only at a grazing angle,
whose GSD from across the object exceeds the band and is correctly refused by §7. The
fix is the one a person uses -- move in -- so the gate is never relaxed, the camera is
just brought close enough that the surface clears it on its own merits.

Aimed cameras are localised by facing **and by place**. Grouping by direction alone does
not localise anything: a cluster like "faces -Y" is one whole side of the object, so
framing it frames the object. Measured, every aimed camera kept the full 57.7mm radius
and the overview's 0.222 mm/px footprint -- which is why zooming appeared to do nothing.
With spatial sub-clustering the same cameras frame at ~21mm and 0.08 mm/px.

## A full run

`python3 -m paintpipe.cli --input samples/creature.stl --size-mm 60 --out run/`

```
frame: [60.0, 55.1, 55.0] mm, size declared
  validate vertex_sharing  repaired  {'vertices_before': 6048, 'vertices_after': 1018}
bands: ['6.72mm']
round 0: 12 views, 0.928 of visible area at >=30 samples; p10=8181  median=11841
round 1: 40 views, 0.995 of visible area at >=30 samples; p10=28317 median=36129
converge: coverage after 40 views, 28826709 observations
```

Exits on **coverage**, at 0.9954 against the 0.995 target. The run writes `scheme.json`
(regions, roles, paint sequence, gates) and `manifest.json` -- 494 entities including
**124 rejections with reasons**, so every dropped pixel and merged region is answerable.

Two honest notes on that run. The scheme has one region because the critic dropped the
other two for never reaching `posterior_floor` anywhere, which is the critic doing its
job on a nearly featureless test sphere with three overlapping proposals. And every
region reports `realizable: false` because no palette or brush was declared -- §3.2's
unconstrained mode, which produces a design rather than a plan and says which it is.

## The Region agent (§10), backed by a vision model

A vision model cannot paint a pixel mask, and asking it to is the usual way this goes
wrong. The work splits:

- **the model** names parts and points at them — a label and a few pixel coordinates
- **`vision.synthesise_mask`** grows each point into a fuzzy mask through the cue maps,
  a flood whose cost to cross between pixels is the local boundary strength

Masks are approximate on purpose. §7 weights every pixel by how well that view resolved
it and §8 fuses across every camera, rig and band, so a seed that lands badly in one view
is outvoted rather than believed.

**Label consistency is what makes fusion possible.** Two views calling the same feature
"barnacle cluster" and "barnacles" produce two regions that never reinforce each other.
So the vocabulary is fixed once by the identity agent on overview renders, and every
per-view proposal must choose from it. A label outside it is rejected with a reason.

### Backends

| backend | needs | use |
|---------|-------|-----|
| `HeadlessBackend` | nothing — `claude -p` with the session's own auth | default in Claude Code |
| `AnthropicBackend` | `ANTHROPIC_API_KEY` | unattended runs; structured outputs |
| `CueBackend` | nothing | the null floor every other backend must beat |

### Two things that are not optional, both learned by getting them wrong

**Name the model.** The headless default is Sonnet, and on a grey shaded render of the
shell it confidently returned `tattered cloak/fringe edge`, `main robe/drapery folds` and
`face/mask area` — a robed figure that is not there. Opus 5 on the same image returns
`ribbed shell wall`, `barnacle clusters`, `rock base`.

**Pass the painter's intent.** An untextured grey render is genuinely ambiguous, and the
brief is the cheapest disambiguation available.

### Exposure is not cosmetic

Rig weights now sum to 1.0. The first version summed to 1.28 on the zenithal rig, and
those renders — **which are what the vision agent looks at** — came back with blown
highlights and crushed blacks. Detail destroyed by exposure is detail the agent cannot
name, and it is destroyed identically in every view, so no amount of fusion recovers it.
Measured after the fix: 0.00% clipped, 0.00% black.

### First fused result

Vocabulary learned from 4 overviews: `shell ribs`, `shell rim`, `barnacle colonies`,
`seaweed fronds`, `rock base`, `cracked shell breaks` — with a parent hierarchy and a
painter's rationale for each.

Seeds verified by overlaying them on the render and looking: blue lands on all three
barnacle clusters, green on the strappy fronds, red on the ribbed bands. Where the agent
was guessing it said so — `shell rim` 0.45, `cracked shell breaks` 0.35 — and those are
the placements that are genuinely ambiguous. That honest confidence is carried into §7's
weight as `mask_confidence` and never rounded up to a decision.

One call per CAMERA, not per bundle: §5.2 makes zenithal the reference rig, and asking
the same question about the same geometry under three lights triples the cost to gather
three correlated answers. Calls within a round run concurrently — they are independent by
construction, since §10 forbids telling the region agent about other views.
