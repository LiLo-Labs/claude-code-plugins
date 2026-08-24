# Reading the segment table

`segment.py` writes `{source, units, axes, parameters, objects[], summary}`.
Read `summary.segments` first - it is the whole table in one screen. Open a full
record from `objects[].segments[]` only to test a specific claim.

## Fields

| Field | Means | Use it for |
|---|---|---|
| `id` | `s01`, `s02`, ... stable within one segments.json | the only thing `plan.json` may name |
| `object_id` | which mesh object the face indices belong to | multi-object 3MFs; ignore for STL |
| `component` | connected component number | telling links of a flexi chain apart |
| `shape_hint` | one generated sentence describing the region | first-pass reading; decoded below |
| `face_count`, `area` | triangles, mm^2 | ranking regions by visual weight - `area` is the honest one, `face_count` follows mesh density |
| `centroid`, `bbox`, `extent` | mm, model space | rarely needed directly |
| `position` | centroid as 0..1 inside the model bbox, `[x, y, z]` | where the region sits, once orientation is fixed |
| `bbox_diagonal` | region size in mm | compare against `summary.extent` diagonal for relative size |
| `principal_extent` | region extents along its own principal axes, longest first | the shape, independent of how the model is rotated |
| `elongation` | longest / middle principal extent | 1.0 round, >=2.5 a shaft |
| `flatness` | middle / shortest | >=4.0 a plate |
| `taper` | narrow end width / wide end width along the long axis | <=0.35 comes to a point: horns, spikes, claws, teeth |
| `protrusion` | `surface_reach x center_offset`, 0 buried, 1 a tip | >=0.8 sticks out; <=0.3 is central mass |
| `surface_reach` | 1.0 = reaches the parent's silhouette | separates "sticks out" from "sunk in" |
| `center_offset` | 1.0 = a body radius off the parent center | high offset + low reach = recessed, e.g. an eye socket |
| `curvature` | mean signed dihedral across interior edges, degrees | positive convex, negative concave |
| `convexity` | share of interior edges that are not concave | >=0.9 a smooth bulge; <=0.6 creased or hollow |
| `open_edges` | edges on the region boundary | large near mouths, gaps and cut surfaces |
| `covers_component` | the region is a whole connected body | a whole horn, link, or eyeball modelled separately |
| `symmetry` | `paired`, `on_midplane`, `unique` | `paired` is the strongest feature signal there is |
| `symmetry_partner` | the other id, or null | partners must get the same filament |
| `face_indices` | the triangles | never read these; `apply_plan.py` resolves ids for you |

`summary` also carries `mirror_plane_x`, `symmetry_pairs`, `component_count` and
the model `bbox`/`extent`. A model with several symmetry pairs and many
components is a creature or a chain; one pair and one component is usually a
part.

## Decoding `shape_hint`

The hint is generated from the numbers, so it never disagrees with them - it
just saves you a lookup. Format:

`<size> [paired] <form>, <position words>[, separate body], <depth>`

- size: `tiny` (<7% of the model diagonal), `small` (7-20%), `medium` (20-50%),
  `large` (>=50%)
- form: `flat plate`, `flat blade`, `tapering cone`, `long tapering spike`,
  `long shaft`, `elongated lobe`, `tapering lobe`, `rounded ball`,
  `shallow dome`, `rounded lump`, `creased or hollow patch`, `irregular patch`
- position words: `upper`/`lower` (Z), `front`/`back` (Y), `left`/`right` (X), or
  `center` - **file axes, not creature axes**
- depth: `protruding`, `recessed`, `central mass`, or `flush`

`small paired rounded ball, front left, separate body, protruding` is an eye on a
model that stands up, and could be a toe pad on a model lying down. That is why
orientation gets fixed first.

## Fixing orientation

1. Render the segmentation and look at the contact sheet - `front`, `top` and
   `iso` are usually enough to see which way the model faces.
2. Compare with `summary.extent`. A creature standing up has its largest extent
   on Z; a flexi chain lying on the bed has it on X or Y.
3. Locate the head: it is the end where small paired protrusions cluster.
4. State the mapping in one sentence and reuse it. All later position readings
   are interpreted through that sentence, never through the raw axis names.

## Structural vocabulary for non-creatures

Use when there are no symmetry pairs and no tapering protrusions, when the
preview shows a manufactured object, or when the user says what the model is.

| Name | Reads as |
|---|---|
| base / plinth | large flat-bottomed region at the low end of the up axis, `flat plate`, high area |
| panel | large `flat plate` or `shallow dome`, `flush`, low protrusion |
| trim / edge band | narrow elongated region following a panel boundary, high `elongation`, small area |
| text / emboss | thin flat regions, small area, several of them, all at the same height off one panel, `protruding` |
| fastener / boss | small round `protruding` region, often repeated at regular spacing |
| mechanism | separate components that interlock; `covers_component: true`, several of them |
| inlay / recess | `recessed`, flat, inside a larger panel |

Describe what you see. If a region has no obvious function, say "the raised band
around the rim" rather than inventing one. Never name anatomy on a part.
