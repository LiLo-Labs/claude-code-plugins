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
