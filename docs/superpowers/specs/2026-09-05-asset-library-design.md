# A parametric asset library with a truthful bill of materials

Status: design, not yet built. Grounded in one working prototype — see Evidence.

## What this is

A personal library of objects that are modelled as they would actually be made,
built up over years. Each object knows what it is made of, how its parts are
joined, what it weighs, how it varies, how it moves, and how it comes apart.

The market stall built on 2026-09-04 is the shape of the problem: four meshes,
five materials, no fasteners, no masses, no way to ask it anything. The crate
built on 2026-09-05 is the shape of the answer: 148 parts, 148 of them
watertight, 112 modelled nails, 16.156 kg measured rather than asserted.

## The position everything follows from

**Assets are specifications; geometry is an output.**

A `.blend` is a build artefact, regenerable and disposable. The asset is a data
file that declares sections, counts, materials, joints and variation axes. You
edit it in a text editor, a web UI or a script; Blender is only needed to bake
it. This is what makes the library outlive Blender versions, and it is the only
form in which "configurable outside Blender" is true rather than aspirational.

Three things fall out of that, and each is worth more than it costs:

**A bill of materials is a by-product of generation, not an annotation.** When a
generator places six boards at 400 × 90 × 18 it already knows the count and the
dimensions; when it drives two nails per board end it knows there are 112. No
downloaded mesh can tell you how many nails are in it. Procedural generation is
the only route to a BOM anyone should believe.

**The BOM is self-verifying.** Boards are boxes and nails are cylinders, so the
spec can *predict* a mass analytically before anything is built. The mesh then
*measures* one with `bmesh.calc_volume`. Agreement means the generator is
faithful; divergence is a bug with a number attached. Every asset carries its
own regression test, for free.

**Tech level is visible, so process belongs in the geometry.** A riven plank has
a split face following the grain; a pit-sawn one has kerf marks; a planed one is
smooth. A neolithic crate is pegged and contains no iron; an 1890s crate is
wire-nailed. That is one generator with a `tech_level` axis producing visibly
different objects with different bills of materials — an enormous return on one
parameter, and the thing that keeps 400 assets coherent rather than unrelated.

## The load-bearing requirement

**Every part is its own watertight closed solid. Parts touch; they never
overlap.**

Volume is only meaningful on a closed mesh, and the entire BOM rests on volume.
Interpenetrating shells standing in for a joint break this, and they are the
default outcome of casual modelling — the market stall does exactly that, which
is why it can never carry a truthful BOM without being rebuilt.

This was expected to be expensive and was not: the crate came out 148/148 closed
on the first attempt at 5,816 faces, with zero interpenetrations verified by an
axis-aligned bounding-box test at 0.01 mm tolerance.

Everything else in this design is downstream of that one rule.

## The schema

Derived from what the crate build actually had to decide, not from invention.
Each field below exists because its absence forced a judgement that geometry
could not supply.

### Sections and parts

    section:  { w_mm, h_mm, grain_axis }     # grain lives on the section
    part:     { name, section, length_mm, count, material, role }
    role:     bearer | frame | cladding | closure

`grain_axis` on the section rather than the object is what let one material give
both "U along the length" and "grain along the length" for boards and battens
alike. `role` is what a material policy keys on — oak on the bearers, pine
elsewhere, is a statement about load path, not about individual parts.

### Joints — the part geometry cannot supply

    joint: { a, b, type, lap: {over, under}, fasteners }
    fastener_rule: { kind, pattern, n, stagger_mm, min_embedment_mm,
                     requires_backing }

Five findings, each from a decision the crate build had to make alone:

1. **Which part laps which.** Side boards over end boards, or the reverse? Both
   produce an identical outer box. The choice sets the end-board length (364 mm,
   not 400) and decides which end grain is exposed at the corner.
2. **What a fastener may land in.** A nail needs a receiving member of stated
   minimum thickness. This constraint is what *forced the lid cleats to exist* —
   nothing in "a lid made of boards" implies them, but "every board must be
   nailed to something" does.
3. **Fastener count is a rule, not a list.** "Two per bearing, staggered"
   generated all 112 positions. Store the rule; regenerate the positions.
4. **Which contacts are joints.** The deck touches the skids on a 70 mm face and
   the battens on a 45 mm face. One is nailed; the other is captured by the wall
   boards instead. Geometry sees two identical contacts and cannot choose.
5. **Intent, not results.** `4 × 90 + 3 × 18 = 414` was solved backwards from a
   target height. Store `courses: 4, gap_mm: 18` so resizing re-solves instead of
   breaking.

### Variation axes

    axes: { lid_open: 0..1, fill: 0..1, wetness: 0..1,
            wind: calm|windy|storm, tech_level: <period> }

Declared, not implied. This is what turns "combine assets to meet a goal" from an
open modelling request into a query with an answer.

### Materials

One shared table, never repeated per asset, so "the fabric changed" is one edit
that repropagates every mass in the library.

    material: { name, density_kg_m3, source, tech_level }

Pine 500, oak 750, wrought iron 7700 kg/m³ as used by the prototype.

### Provenance

    version: <schema version>          # required from asset #1
    period:  <when this was possible>
    source:  <citation for any real-world number>

Asset #1 will be written against a schema asset #400 has outgrown. Without a
version field they cannot be migrated. Historical order is a research burden —
cut nails replaced hand-forged around 1800, wire nails around 1890, riving
predates sawing by millennia — and plausible-sounding anachronisms are hard to
unpick later.

## The recipe graph

Each node declares what it consumes and produces. Nodes are both outputs and
inputs, so the library is a graph rather than a list.

    recipe: { inputs, tools, process, outputs, losses, period }

    oak log ──> plank ──┬──> crate ──> crate stack
                        └──> counter ─┐
    flax ──> thread ──> canvas ───────┼──> market stall
    iron ore ──> billet ──> nail ─────┘

`tools` are themselves assets with their own recipes, terminating at things
picked up off the ground. "Assets that show raw materials bundled together" are
not a special category — a stack of planks, a bolt of cloth, a keg of nails are
recipe outputs one level down.

**Destruction is the same edge run backwards.** Making a plank yields offcuts and
shavings; breaking a crate yields boards and bent nails. One recipe definition
gives both crafting and salvage.

## Physics

Bullet rigid-body simulation with breakable constraints, driven by BOM masses.
It serves three purposes at once and should not be built as a separate stage:

- **Verification** — does the assembly hold together, and does it fail somewhere
  sensible.
- **Destruction** — breakable constraints under load *are* the destruction
  animation, and the debris at rest is the salvage table made visible.
- **Weight sanity** — the sim is driven by the same masses the BOM reports.

**Limits, stated plainly.** Bullet has no concept of grain, shear strength or
nail withdrawal, and its thresholds are engine impulse units, not newtons.
Relative claims hold (this joint fails before that one); absolute ones do not.

**Do not reach for FEA.** CalculiX, Code_Aster and Elmer are free and capable,
but they need tetrahedral meshes, orthotropic wood properties, and they handle
the contact-and-friction problem you care about worst. The number wanted here is
already published: timber design codes give nail withdrawal and lateral capacity
per diameter, penetration and density. Look it up, put it in `capacity_N` with a
`source`, and calibrate Bullet against it.

**Calibrate once and record it.** Pick a reference failure — a 1.2 m drop onto
stone, corner first — tune thresholds until a crate fails as a crate should, then
hold those units constant library-wide. Otherwise every asset invents its own
scale and nothing is comparable.

Animation must be shape keys or armature bones. Drivers do not survive an
untrusted reopen; drivers, lattices and modifier animation do not survive glTF.
Simulate at authoring time, bake, ship the bake.

## Infrastructure constraint

The bridge drives **one shared Blender process**. Two concurrent runs corrupt
each other: during the prototype a second run wiped the scene three times and
overwrote the saved `.blend` 70 seconds after it was written. Either one Blender
per run on its own port, or a lock. This is not optional at library scale.

## Evidence

Everything above is grounded in one build, not projected.

| Claim | Measured |
|---|---|
| Watertight solids are affordable | 148/148 closed, 5,816 faces, first attempt |
| Parts touch, never overlap | 0 interpenetrations, AABB at 0.01 mm |
| Fasteners are derivable from a rule | 112 nails from "two per bearing, staggered" |
| Every fastener does work | all 112 sampled: board → receiving member, none in air |
| Mass is plausible | 16.156 kg; 136 kg/m³ apparent, 27% of solid pine |
| Against reality | modelled nail 3.3 g vs ~3.5 g real |

Known imprecision, reported by the build rather than discovered later: the nail
shank is a 12-sided prism, so its volume is 9.0% under a true cylinder. The BOM
reports the mesh that exists and carries a `faceting_note`.

## Proving order

Build up from a leaf; never down from the tree. Each addition is validated by
something that already exists and needs it.

1. **Crate → spec file.** Reverse the prototype into a declarative spec that
   regenerates it, and assert the regenerated BOM equals 16.156 kg. Until a spec
   reproduces a known-good asset, the format is unproven.
2. **Barrel.** The first asset with every axis at once — wood volume, iron
   volume, a fastening, an internal capacity in litres, a lid that opens.
3. **Plank, then the froe that rives it.** The first recipe edge and the first
   tool.
4. **Physics calibration** against a published fastener capacity.
5. **Composition** — the MCP verbs that assemble variants to meet a goal.

## Open questions

- Spec format: JSON is obvious and unpleasant to hand-edit. TOML or YAML reads
  better; JSON round-trips better. Undecided.
- Where specs live: in this plugin, or their own repository. The library outlives
  the plugin, which argues for its own repo — and `blendpipe-out/` is currently
  not under version control at all.
- Whether `gameassets` (1,549 packs, 814k assets, already indexed by concept and
  licence) becomes the retrieval half of `find_assets`, or stays separate.
