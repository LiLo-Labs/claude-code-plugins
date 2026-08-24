# Model Paint Plugin

Paints an STL or 3MF for multi-filament printing from one command. Segments the
mesh into real features, names them (eyes, horns, spikes, claws, belly plates —
or panels, trim, and text on a non-creature), plans colors against the filaments
you actually have loaded, and writes an OrcaSlicer-ready 3MF whose geometry is
provably identical to what went in.

## What it does

```
baby_dragon.stl                                    baby_dragon-painted.3mf   ← open in OrcaSlicer
                              /paint …             baby_dragon-paint/
                             ─────────────────►      segments.json
                                                     plan.json
                                                     preview-segments/*.png  ← "are those the horns?"
                                                     preview-plan/*.png      ← "is that the look?"
```

The input file is never written to. The painted 3MF is a project file: paint
data, filament colors, and per-object extruder assignment are all inside it, so
the slicer opens it already painted.

## The geometry guarantee

The models this exists for are interlocking flexi prints — a chain of separate
bodies with clearances measured in tenths of a millimetre. A "helpful" repair,
weld, or decimation fuses the joints and turns a 14-hour print into a solid
lump, and it does it silently: the file still opens, still slices, still looks
right on screen.

So the rule is absolute. **Painting adds `paint_color` attributes and changes
nothing else.** No re-meshing, no vertex merging, no repair, no rescaling, no
recentering, no boolean operations. Three independent mechanisms hold it:

1. **Surgical text edits.** `paintlib/threemf.py` never parses-and-reserializes
   the model XML. It locates each `<triangle …/>` and rewrites only its
   `paint_color` attribute, leaving whitespace, attribute order, float
   formatting, transforms, and every unrelated part of the archive byte-for-byte
   intact. Round-tripping through an XML DOM would be harmless in principle; "in
   principle" is not a claim worth betting a print on. Every mesh load in the
   plugin passes `process=False` for the same reason.
2. **Verification before the file is handed over.** After saving, `apply_plan.py`
   compares output against input with `threemf.geometry_matches` — object count,
   object ids, every vertex, every triangle index, and the build placement — then
   reloads the result and confirms the paint decodes back to exactly the
   triangles the plan implied. If either check fails, the output file is
   **deleted**, because a file that exists is a file someone will eventually
   print. The confirmation line it prints on success is the one the command
   quotes back to you verbatim.
3. **Guardrail hooks.** `hooks/guard_mesh.py` blocks shell commands that would
   re-mesh, weld, decimate, transform, or repair a model you intend to print
   (scratch copies under `/tmp` and the bundled sample are exempt, since mutating
   a throwaway is ordinary work). `hooks/guard_core.py` warns before anything
   edits the paint codec. `hooks/verify_geometry.py` re-derives the
   geometry-unchanged claim after the fact using `zipfile` + `ElementTree` and a
   hand-rolled STL reader — code that shares nothing with `paintlib`, so a bug in
   the painter cannot also write the proof.

## Install

Add the LiLo Labs marketplace, then install the plugin:

```
/plugin marketplace add LiLo-Labs/claude-code-plugins
/plugin install model-paint@lilo-labs-plugins
```

Requires Python 3 with `numpy`, `trimesh`, `pillow` (`preview.py` writes its
PNGs through it) and `scipy` (`verify.py` counts separate bodies with it):
`pip install numpy trimesh pillow scipy`. Nothing beyond that — the previews
are rendered by a small numpy rasterizer, so there is no GPU, display, or GL
context to arrange.

## Commands

| Command | Description |
|---------|-------------|
| `/paint <model.stl\|model.3mf>` | Full run: segment, preview, label, plan, approve, apply. |
| `/paint <model> --colors "black, red, bone, gold"` | Use this filament list, in nozzle order. |
| `/paint <model> --palette mine` | Use the saved inventory at `~/.config/model-paint/filaments.json`. |
| `/paint <model> --style natural\|contrast\|accent` | Lead with this look; the alternatives are still offered. |
| `/paint` | Prompt for a path. |

Styles are the three plan archetypes: **natural** (looks like an animal, not a
toy), **contrast** (every feature reads from across the room), **accent** (one
color does all the work).

## Filament inventory

`~/.config/model-paint/filaments.json` — a list of loaded filaments. The command
offers to write it for you the first time you describe your loadout.

```json
[
  {"name": "Slate Grey PLA", "hex": "#4a5058", "nozzle": 1},
  {"name": "Bone White PLA", "hex": "#e8e0cf", "nozzle": 2},
  {"name": "Black PLA",      "hex": "#1a1a1a", "nozzle": 3},
  {"name": "Copper PLA",     "hex": "#b06b2c", "nozzle": 4}
]
```

`nozzle` is the filament index the slicer will use, 1-based, capped at 4 for a
four-nozzle machine. `hex` should be the filament's real color: it drives the
plan preview and the project's filament settings, so a wrong hex means a preview
that lies to you.

## Plan JSON

The plan is the only file that encodes judgment, and it is plain JSON you can
edit by hand.

```json
{
  "filaments": [
    {"index": 1, "name": "Slate Grey PLA", "hex": "#4a5058"},
    {"index": 2, "name": "Bone White PLA", "hex": "#e8e0cf"},
    {"index": 3, "name": "Black PLA", "hex": "#1a1a1a"}
  ],
  "assignments": [
    {"segment_id": "s04", "filament": 2, "reason": "left horn, bone against the dark body"},
    {"segment_id": "s05", "filament": 2, "reason": "right horn, matches its pair"},
    {"segment_id": "s02", "filament": 3, "reason": "left eye, highest contrast on the smallest feature"},
    {"segment_id": "s03", "filament": 3, "reason": "right eye, matches its pair"}
  ],
  "default_filament": 1
}
```

| Field | Meaning |
|---|---|
| `filaments[].index` | 1..4, the nozzle. Every `filament` used in `assignments` must appear here. |
| `filaments[].name` | Shown to you in summaries and previews. Required. |
| `filaments[].hex` | The real filament color. Required; drives the preview and the project config. |
| `assignments[].segment_id` | Must match an `id` in `segments.json` exactly. Unknown ids are an error, not a skipped assignment. |
| `assignments[].filament` | One of the listed indices. |
| `assignments[].reason` | Required, written for a human: the feature and the intent. No ids, no coordinates. |
| `default_filament` | The object's extruder. Unassigned regions print from it, so the base region is normally left unassigned. |

Editing a plan and re-running only the last two steps is the intended way to
iterate — segmentation does not need to be redone.

## Worked example

The bundled sample is a synthetic creature: sphere body, two ball eyes, two cone
horns, 2016 triangles.

```bash
cd plugins/model-paint

python3 scripts/segment.py --input samples/creature.stl --output /tmp/segments.json
```

```
creature.stl
  1 object(s), 2016 triangles, 5 component(s), 5 segment(s)
  extent 40 x 40.5 x 51 mm, 2 symmetry pair(s)
  s01    1280 faces  large rounded ball, center, separate body, central mass
  s02     320 faces  small paired rounded ball, front left, separate body, protruding  (pairs s03)
  s03     320 faces  small paired rounded ball, front right, separate body, protruding  (pairs s02)
  s04      48 faces  medium paired tapering cone, upper left, separate body, protruding  (pairs s05)
  s05      48 faces  medium paired tapering cone, upper right, separate body, protruding  (pairs s04)
```

Two small paired balls at the front of the head are the eyes; two paired
tapering cones on top are the horns. That reading is what the previews confirm:

```bash
python3 scripts/preview.py --input samples/creature.stl --segments /tmp/segments.json --output /tmp/prev-seg
```

Write the plan above to `/tmp/plan.json`, render it, then apply:

```bash
python3 scripts/preview.py   --input samples/creature.stl --segments /tmp/segments.json --plan /tmp/plan.json --output /tmp/prev-plan
python3 scripts/apply_plan.py --input samples/creature.stl --segments /tmp/segments.json --plan /tmp/plan.json --output /tmp/creature-painted.3mf
```

```
  input      samples/creature.stl (converted to 3MF)
  output     /tmp/creature-painted.3mf
  model      2016 triangle(s) in 1 object(s)

  filament  name            color    triangles
  1         Slate Grey PLA  #4A5058          0
  2         Bone White PLA  #E8E0CF         96
  3         Black PLA       #1A1A1A        640
  -         unpainted                     1280

  unpainted triangles print from filament 1 (Slate Grey PLA)
  wrote a minimal Metadata/project_settings.config (the input had none)
  geometry unchanged: 1 object(s), 2016 triangles, geometry and placement identical
```

The same check can be run at any time against any pair of files:

```bash
python3 scripts/verify.py --a samples/creature.stl --b /tmp/creature-painted.3mf
```

## How it works

Four stages, two of them deterministic and two of them judgment. The split is
deliberate: the parts a machine can be exact about are scripted, and the parts
that need a model's judgment are wrapped in pictures you approve.

1. **Segment** (`segment.py`, deterministic) — cuts the mesh into ~5-60 described
   regions. Two cuts, in order: connected components (on a flexi chain, each link
   is its own body and is never merged with another), then concave creases inside
   a component, because anatomy attaches at valleys — the groove where a horn
   meets the skull, the socket around an eye. Convex ridges are usually *inside*
   a feature, so the convex threshold is deliberately high. Output is a JSON
   record per region: face count, area, position, taper, protrusion, elongation,
   symmetry partner, and an English `shape_hint` like "medium paired tapering
   cone, upper left, protruding".
2. **Label** (the `model-paint` skill) — turns regions into feature names. Each
   label is a hypothesis with a kill condition, checked against the render: on a
   flexi model, ball-joint sockets are small, paired, and concave, and mimic eyes
   perfectly, so "paired and small" is not enough to call something an eye. On a
   model with no symmetry and no tapering protrusions, the vocabulary falls back
   to structural naming — base, panel, trim, text, mechanism — rather than
   hallucinating anatomy onto a bracket.
3. **Plan** (the skill, again) — assigns filaments. Largest region takes the base
   color and becomes `default_filament`; the highest-contrast filament is
   reserved for the smallest high-salience features, because a 3 mm eye needs the
   biggest luminance jump to read at all; symmetric partners always match. You
   get 2-3 plans that differ in character, presented by feature name, and a
   render of the one you pick.
4. **Apply** (`apply_plan.py`, deterministic) — resolves segment ids to triangle
   indices, encodes `paint_color` strings with a verified port of OrcaSlicer's
   own `TriangleSelector::serialize()`, writes the project config, and proves the
   geometry survived before letting the file exist.

`preview.py` sits between the stages. It is an orthographic z-buffer rasterizer
in numpy — per-pixel hidden-surface resolution, because triangle-sorted rendering
visibly tears interlocking flexi joints apart — and it renders six views plus a
contact sheet in either segment colors or plan colors.

## Limitations

Honest list, because a wrong paint job costs a print.

- **Segmentation quality depends on the model.** Creases are the main signal, so
  a crisply modelled creature segments beautifully and a smooth organic sculpt
  segments coarsely. Smoothly-blended horns commonly come out as tips only,
  since no crease exists at the base — a dipped tip is a legitimate look, but it
  is not the same as painting the whole horn, and the plan will say which you are
  getting.
- **Anatomy inference is heuristic.** The rules are good, not certain: they are
  measurements plus kill conditions, and they can be confidently wrong on an
  unusual model. That is exactly why both previews are mandatory rather than
  optional, and why nothing is applied without your approval.
- **Support and seam painting are not handled.** The plugin writes multi-filament
  paint only. Support-blocker/enforcer painting, seam painting, and modifier
  meshes stay in the slicer's hands.
- **Four filaments, no swaps.** The plan assumes independent nozzles: the color
  count is capped at 4 and there is no purge-tower or filament-change modelling.
- **No geometry edits, ever** — including the ones you might want. Splitting a
  part to paint half of it, or thickening a feature so a light filament covers
  properly, are things this plugin will refuse to do. Use CAD, then come back.
- **The synthetic sample is easy.** `samples/creature.stl` has cones stuck onto a
  sphere with sharp creases at the base. Real sculpted models are harder; see
  `docs/segmentation-findings.md` for what a 475k-triangle flexi dragon actually
  produced.

## License

MIT.
