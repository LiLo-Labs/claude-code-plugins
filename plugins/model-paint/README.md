# Model Paint Plugin

> **Picking this work up?** Start with [HANDOFF.md](HANDOFF.md): current state,
> what is measured to work, the open problem, and the dead ends not worth
> repeating. Then [docs/agentic-process.md](docs/agentic-process.md): the loop
> this has to run as, and the failure that paid for each rule.


Paints an STL or 3MF for multi-filament printing from one command. Segments the
mesh into real features **in 3D**, has vision agents name them (eyes, horns,
spikes, claws, belly plates — or panels, trim, and text on a non-creature),
designs an unconstrained color scheme first, limits it to the filaments you
actually have loaded, has a critic review the finished renders, and writes an
OrcaSlicer-ready 3MF whose geometry is provably identical to what went in.

## What it does

```
baby_dragon.stl                                    baby_dragon-paint/
                              /paint …               painted.3mf             ← open in OrcaSlicer
                             ─────────────────►      continuous-hero.png     ← the design, unconstrained
                                                     final-hero.png          ← limited to your filaments
                                                     *-turnaround.png        ← 8 views each
                                                     atlas.png               ← which faces belong to which part
                                                     scheme.json, parts.npz  ← the record; drives --repaint
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

1. **Surgical text edits.** `scripts/paintlib/threemf.py` never
   parses-and-reserializes the model XML. It locates each `<triangle …/>` and
   rewrites only its `paint_color` attribute, leaving whitespace, attribute
   order, float formatting, transforms, and every unrelated part of the archive
   byte-for-byte intact. Round-tripping through an XML DOM would be harmless in
   principle; "in principle" is not a claim worth betting a print on. Every mesh
   load in the plugin passes `process=False` for the same reason. The pipeline's
   own validation repairs (inward winding, duplicated shared vertices) happen on
   an in-memory working copy used for rendering and labelling — they never touch
   the file and never move a vertex.
2. **Verification before the file is handed over.** After saving, the export
   compares output against input with `threemf.geometry_matches` — object count,
   object ids, every vertex, every triangle index, and the build placement — and
   prints `3MF IDENTICAL` or `3MF DIFFERS` with the first difference. The
   command quotes that line back to you verbatim.
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

Requires Python 3 with `numpy`, `trimesh`, `pillow`, `scipy`, `rtree`,
`networkx` (trimesh needs it for meshes with open boundaries),
`colour-science` (Lab↔sRGB and CIEDE2000) and `embreex`:

```bash
pip install numpy trimesh pillow scipy rtree networkx colour-science embreex
```

The naming, painter and critic agents run as headless `claude -p` calls, so the
Claude Code CLI must be on PATH and authenticated. Vision answers are cached
per render digest in the output directory, so re-runs and interrupted runs are
cheap.

There is still no GPU, display, or GL context to arrange. `embreex` is not a
renderer — it is trimesh's fast ray-triangle backend, and every view is ray-traced
one ray per pixel, so it is what makes rendering practical rather than optional.
Without it trimesh silently falls back to a pure-numpy intersector: on this
container that turned a seven-view session on a 2,016-triangle model from seconds
into minutes, and made one test in the suite exhaust 16 GB of RAM and get killed.
The fallback is silent and looks exactly like slowness, so if rendering seems
inexplicably slow, check the backend first:

```bash
python3 -c "import trimesh; print(type(trimesh.creation.icosphere().ray).__module__)"
# trimesh.ray.ray_pyembree = fast; trimesh.ray.ray_triangle = the slow fallback
```

## Commands

| Command | Description |
|---------|-------------|
| `/paint <model.stl\|model.3mf>` | Full run: segment in 3D, name, design, limit, critique, export. |
| `/paint <model> --intent "a baby dragon"` | Say what the piece is; one phrase disambiguates a grey render. |
| `/paint <model> --size-mm 187` | The real printed height; inferred and flagged when absent. |
| `/paint <model> --colors "black, orange, bone, grey"` | Use this filament list, in nozzle order; the last one is the body default. |
| `/paint <model> --palette mine` | Use the saved inventory at `~/.config/model-paint/filaments.json`. |
| `/paint` | Prompt for a path. |

After a run, changes are seconds, not minutes: "make the eyes black" re-maps
the already-named parts and re-exports without a single new vision call.

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
four-nozzle machine. `hex` should be the filament's real color: it drives every
render and the project's filament settings, so a wrong hex means a preview that
lies to you.

## Running the pipeline directly

The command is a wrapper over one CLI, which is also usable on its own:

```bash
cd plugins/model-paint

# Full run: segmentation, naming, design, limiting, critic, verified export.
python3 -m paintpipe.cli \
    --input samples/baby-dragon.stl --out /tmp/dragon-paint \
    --intent "a cute baby dragon flexi toy" --size-mm 187 \
    --colors "white:#FFFFFF, black:#000000, orange:#FF8000, grey:#808080"

# Segmentation only -- no vision calls, writes atoms.png to sanity-check a model.
python3 -m paintpipe.cli --input samples/creature.stl --out /tmp/quick \
    --size-mm 80 --no-vision

# Change your mind afterwards -- no vision, seconds.
python3 -m paintpipe.cli --input samples/baby-dragon.stl --out /tmp/dragon-paint \
    --colors "white:#FFFFFF, black:#000000, orange:#FF8000, grey:#808080" \
    --repaint "eyes:black, horns:orange"
```

A full run costs minutes to tens of minutes and real vision calls, scaling with
triangle count; the log prints the parts found, an isolation table, every
filament decision with its ΔE, the critic's verdict, and the geometry
verification line.

## How it works

Six stages (`paintpipe/pipeline.py`). Geometry proposes; agents decide; the
export proves. Where a constant appears it is a legibility or budget bound —
how many ids fit readably in one render, how many views to buy — never a part
boundary.

1. **Segment in 3D** (`segment3d.py`, deterministic) — a per-face scale-space
   index (characteristic scale and signed relief by diffusion over the face
   graph), Felzenszwalb regions over scale + relief + dihedral edge weights,
   then a persistence merge tree. The "atoms" offered for naming are a cut of
   that tree, so their boundaries are concave junctions and relief edges found
   in 3D — hips, not the ankle-line a surface tiling happens to draw. Every
   atom keeps its own sub-tree, which is what makes "color the sub-part" a
   descent rather than a re-segmentation.
2. **Name** (vision) — the agent reads paired shaded + numbered-id renders from
   three elevation rings and says which atoms belong to which part of a
   vocabulary it proposed itself from overview renders plus your intent. Votes
   are fused statistically across all views: selection beats judgement.
3. **Descend** — atoms whose votes straddle two parts are split along their own
   sub-tree and re-asked with the new ids highlighted. Unvoted leftovers
   inherit from labelled neighbours across face adjacency.
4. **Refine** (`refine.py`) — parts the vocabulary promised but nobody found
   get a recovery ladder: a zoomed re-ask over the declared parent, then
   locate-then-zoom from a pixel box, a prune gate over claimed patches, and as
   a last resort a design cut confirmed in context. Every recovered, drawn,
   rejected and failed part is reported as itself.
5. **Paint, then limit, then critique** — the painter colors the named parts
   unconstrained first ("color it beautifully"); only then is the scheme
   assigned to your filaments (area- and accent-weighted, exhaustive over the
   regions), and a critic reviews the finished limited renders and may override
   assignments. The continuous renders are the honest test of the
   segmentation; the final renders are what the printer will lay down.
6. **Export** (`scripts/paintlib/`, deterministic) — encodes `paint_color`
   strings with a verified port of OrcaSlicer's own
   `TriangleSelector::serialize()`, writes the project config, and proves the
   geometry survived before handing the file over.

## Limitations

Honest list, because a wrong paint job costs a print.

- **Naming needs vision.** `--no-vision` stops after segmentation, on purpose:
  there is no honest deterministic stand-in for looking at a model and saying
  which piece is the tail. Full runs cost real model calls (typically a few
  dollars on a large sculpt) and the log reports the spend.
- **Painted-on features may stay painted-on.** A feature that exists only in
  the texture sense — lips on a smooth face, an eye with no socket geometry —
  can fail the recovery ladder's in-context confirmation and is then reported
  as rejected rather than being invented badly.
- **Support and seam painting are not handled.** The plugin writes
  multi-filament paint only. Support-blocker/enforcer painting, seam painting,
  and modifier meshes stay in the slicer's hands.
- **Four filaments, no swaps.** The plan assumes independent nozzles: the color
  count is capped at 4 and there is no purge-tower or filament-change
  modelling.
- **No geometry edits, ever** — including the ones you might want. Splitting a
  part to paint half of it, or thickening a feature so a light filament covers
  properly, are things this plugin will refuse to do. Use CAD, then come back.

## License

MIT.
