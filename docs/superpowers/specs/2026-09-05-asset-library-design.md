# forge — a recursive library of things that are modelled as they are made

Status: design. Nothing built to it yet. Grounded in three working prototypes,
listed under Evidence.

Supersedes the first draft of this file, which was written as though from a
blank page and missed that `forge-library` already existed.

## What this is

A personal library of objects, built up over years, where each object is modelled
the way it would actually be made — from raw materials forward. Every object
knows what it is made of, how its parts are joined, what it weighs, how it
varies, what state it is in, how it moves, and how it comes apart.

It is recursive by intent. You cannot have a crowbar without smithing, or
smithing without charcoal, so asking for a crowbar asks for its whole ancestry.
The library grows by resolving what it does not yet have.

## The positions everything follows from

**Assets are specifications; geometry is an output.** A `.blend` is a build
artefact, regenerable and disposable. The asset is a data file. You edit it in a
text editor or a script; Blender is only needed to bake it. This is the only form
in which "configurable outside Blender" is true rather than aspirational, and it
is what lets the library outlive Blender versions.

**A bill of materials is a by-product of generation, not an annotation.** A
generator that placed six boards knows there are six; one that drove two nails
per board end knows there are 112. Nobody can say how many nails are in a
downloaded mesh. Procedural generation is the only route to a BOM anyone should
believe.

**Model once at true fidelity; derive everything cheaper.** A leaf is modelled
properly — midrib, lobes, curl — as an asset with its own mass and its own
lifecycle. The tree's foliage cards sample a bake *of that leaf*. Cards, impostors
and LODs are build outputs, never hand-authored. This is what makes leaf
varieties and styles mix and match: swap the leaf, rebake, every tree that
references it updates.

**Measured beats asserted, everywhere.** Volume from `bmesh`, not bounding boxes.
Texel density computed, not eyeballed. Triangle counts against a budget declared
before building. A claim without a number attached is not a claim.

## What already exists

Three things, and the design should extend rather than replace them.

**`forge-library`** — 172 tests passing in 6.87s with no Blender. Being rebuilt
from scratch, keeping:

- `spec/standard.json`, the "MAS" export contract: metre units, Z-up authoring →
  Y-up export, glTF 2.0 targeting Godot 4 and Unreal 5, `GEO-`/`RIG-`/`SKT-`
  naming prefixes, forbidden trailing tokens, `max_non_manifold_edges: 0`,
  `max_loose_verts: 0`. Expensive to re-derive; keep wholesale.
- **The maths/`bpy` split.** `geom.py` and `rules.py` do not import `bpy`; a
  single module does. For hundreds of assets, most validation must never launch
  Blender.
- **`registry.part` with `requires` / `provides`.** The graph primitive the
  resolver needs, queryable without importing builders.
- **The five rule layers** — core, part, interface, assembly, standard — chosen
  by asking what the smallest thing that can violate the rule is.
- **No `bpy.ops` in builders.** `from_pydata`, because operators act on the
  active object and can silently return the previous one.

Discarded: the leather-goods parts (belt, buckle, chape, keeper, tips, wrap) as
domain content, and anything assuming a single-material soft-goods domain. The
old tree remains in git history and under its existing tags.

**`blendpipe`** (tagged `blender-v0.1.0`) is the Blender-driving and verification
arm: the socket bridge, `verify_geometry`, the headless agent runner, the Agent
panel. `validate.py` checking a `.blend` against `standard.json` and
`verify_geometry` measuring live geometry are the same job from two sides and
should share one implementation.

**`~/GameAssets`** — 1,463 packs, 814k files, `assets.db` with `packs`, `files`,
`concepts` and `edges(src, rel, dst)` carrying `IS_A` and `HAS_PART`. `HAS_PART`
is already the BOM relation. A `MADE_FROM` relation puts the recipe graph in the
database the library already searches. Built artefacts land here as a new
`source`, indexed like any other pack.

## The load-bearing requirement

**Every part is its own watertight closed solid. Parts touch; they never
overlap.**

Volume is meaningful only on a closed mesh, and the whole BOM rests on volume.
Interpenetrating shells standing in for a joint break it, and they are the
default outcome of casual modelling.

Expected to be expensive; was not. The prototype crate came out 148/148 closed at
5,816 faces on the first attempt, with zero overlaps verified by an axis-aligned
test at 0.01 mm.

## Schema

Every field below exists because its absence forced a judgement that geometry
could not supply. Nothing here is speculative.

### Sections and parts

    section: { w_mm, h_mm, grain_axis }
    part:    { name, section, length_mm, count, material, role }
    role:    bearer | frame | cladding | closure | fastener

`grain_axis` belongs to the section, not the object: building every part with its
local +X along its length made "U along the length" and "grain along the length"
both free under one material. `role` is what a material policy keys on — oak
bearers under pine cladding is a statement about load path.

### Joints

    joint:         { a, b, type, lap: {over, under}, fasteners }
    fastener_rule: { kind, pattern, n, stagger_mm, min_embedment_mm,
                     requires_backing, capacity_N, source }

Five findings from the crate, each a decision the shape could not make:

1. **Which part laps which.** Side boards over end boards, or the reverse? Both
   give an identical outer box. The choice sets the end-board length — 364 mm,
   not 400 — and which end grain shows at the corner.
2. **What a fastener may land in.** A nail needs a receiving member of stated
   thickness. That constraint is what *forced the lid cleats to exist*: nothing
   in "a lid of boards" implies them, but "every board must be nailed to
   something" does.
3. **Fastener count is a rule, not a list.** "Two per bearing, staggered"
   generated all 112 positions.
4. **Which contacts are joints.** The deck meets the skids on a 70 mm face and
   the battens on a 45 mm face. One is nailed; the other is captured by the wall
   boards. Geometry sees two identical contacts.
5. **Store intent, not results.** `4 × 90 + 3 × 18 = 414` was solved backwards
   from a target height. Store `courses: 4, gap_mm: 18` so resizing re-solves
   instead of breaking.

`capacity_N` carries a published figure with a `source` — timber design codes
give nail withdrawal and lateral capacity per diameter, penetration and density.
Look it up; do not simulate it.

### States — discrete arrangements

Distinct from axes. A state is a set of transforms and visibility over parts that
already exist; it remodels nothing. The prototype produced four states with zero
geometry added, moving 41 objects.

    state: { name, parts: {<part>: constraint}, damage, props, salvage }

Constraints must be **derived, not typed**. Hand-authored transforms were wrong
three times out of four in the prototype: `closed` floated above the rim,
`lid_beside` stood on its edge, and the object drifted between cells.

    closed:     { lid: seated_on: rim }
    prised:     { lid: hinged_at: back_cleat, angle: 25deg,
                  damage: [nails_pulled, edge_splintered], props: [crowbar] }
    lid_beside: { lid: resting_on: ground, offset: 1.1 × footprint_x }
    lidless:    { lid: absent }

`seated_on: rim` cannot float. `resting_on: ground` cannot stand on edge.

**The state carries the evidence of how it was reached.** A lid nailed with 24
nails does not hinge — opening it is a destruction event, so the opened state has
pulled nails, splintered edges and the tool that did it. `salvage` differs per
state: 24 straight nails if never opened, 24 bent ones if prised.

### Axes — continuous variation

    axes: { wetness: 0..1, fill: empty|straw|sacks, wind: calm|windy|storm,
            season: spring|summer|autumn|winter, tech_level: <period> }

Declared per asset, because the same weather means different mechanisms on
different objects. Wind on an awning is geometry — shape keys, measured at 132 mm
of travel. Wind on a crate is nothing; rain on a crate is entirely material —
roughness down, albedo darker, damp creeping along the grain. A shared "weather"
flag across the library would be wrong.

`tech_level` is a *visual* axis, not only economic. A riven plank has a split face
following the grain; a pit-sawn one has kerf marks. A neolithic crate is pegged
and contains no iron; an 1890s crate is wire-nailed. One generator, one
parameter, two visibly different objects with different bills of materials.

### LOD

    lod: { 0: <modelled>, n: { derived_from: 0, method: bake|decimate|impostor } }

Never authored. A card is a bake of LOD0 seen from a fixed angle; an impostor is
an atlas of them. Verifiable: render LOD0 and its derived card from the same
angle and diff the silhouettes.

### Time — events exist at several scales

    event: { name, scales: { <scale>: { kind, duration, representation } } }

An event has a native time-scale and coarser representations *derived* from it,
the same way LOD works for geometry. Speed is not a dial you can turn
arbitrarily.

    leaf_fall:
      seconds: { kind: animation,  duration: 3s,
                 representation: one leaf tumbling, aerodynamic }
      hours:   { kind: particle,   representation: scatter accumulating as litter }
      months:  { kind: transition, representation: canopy full -> thinning -> bare,
                 plus ground litter state }

A leaf tumbling for three seconds, played back at one-thirtieth speed to fill a
month, drifts imperceptibly and looks wrong. The monthly representation is not
the fine one slowed down — it is a state transition between `season` values, and
the individual trajectories are meaningless at that scale.

The consuming game declares its tick; the asset supplies the representation that
matches, or says it has none for that scale.

**Honest note on the fine scale.** A real leaf tumbles because of lift and
flutter. Bullet has no aerodynamics, so a rigid-body drop gives a stone, not a
leaf. The seconds-scale representation needs either a hand-authored tumble baked
to keyframes or a simple lift model — and, either way, baking, since it must
survive glTF.

### Compatibility

Two kinds, and only one is declarative.

    declared: { setting, art_direction, tier }
    measured: { texel_density_px_m, tris_per_m3, palette }

    setting:       medieval-european | sci-fi | modern | fantasy | ...
    art_direction: realistic | stylised | flat | painterly
    tier:          background | prop | hero

A `style: "medieval"` string nobody enforces is worthless. The measured half is
what actually makes a scene look wrong and can be checked: `check_mix([...])`
returns *"texel density 8× apart — tree 512 px/m, crate 64"*, a number you can
act on. `tier` is declared but implies the measurable bands, which is what makes
"6,000 triangles" and "128–320 px/m" contracts rather than opinions.

### Materials and provenance

One shared table; never repeated per asset, so changing a material repropagates
every mass in the library.

    material: { name, density_kg_m3, source, tech_level, min_gauge }
    version:  <schema version>     # required from asset #1
    period:   <when this was possible>

Pine 500, oak 750, wrought iron 7700 kg/m³ as used by the prototype. Asset #1
will be written against a schema asset #400 has outgrown; without a version they
cannot be migrated. Historical order is a research burden — cut nails replaced
hand-forged around 1800, wire nails around 1890 — and anachronisms are hard to
unpick later.

## The recipe graph and the resolver

    recipe: { inputs, tools, process, outputs, losses, period }

    oak log ──> plank ──┬──> crate ──> crate stack
                        └──> counter ─┐
    flax ──> thread ──> canvas ───────┼──> market stall
    iron ore ──> billet ──> nail ─────┘

`tools` are themselves assets with recipes. Asking for a crowbar asks for
smithing, charcoal, a kiln. The resolver walks `requires`/`provides`; every
unsatisfied requirement becomes the next build target. That is how the library
automates — you do not queue the work, the graph does.

**Destruction is the same edge backwards.** Making a plank yields offcuts and
shavings; breaking a crate yields boards and bent nails. One definition gives
crafting and salvage both.

Two rules decide whether this terminates:

**A declared terminal set.** Stone, wood, clay, ore-bearing rock, plant fibre,
hide, water — things picked up off the ground. Short, written once. Without it
the recursion never bottoms out.

**A bootstrap predecessor for every tool.** You need a hammer to make a hammer.
History resolves this with a cruder ancestor: a stone hammer makes the first iron
one. Each tool declares a strictly simpler `bootstrap`, terminating at something
shaped by hand. **A cycle here does not error, it simply never finishes** — this
is the most likely thing to go wrong quietly.

Growth is exponential in reach but sub-linear in effort, because prerequisites
are shared: charcoal feeds the bloomery, the forge and the kiln. The first twenty
assets are the expensive ones.

## Mesh economy and the review path

The classic failure of generated meshes is being overdone: recursive branching to
exhaustion, every leaf as geometry, bark as displacement — 60k triangles for a
tree that should be 4k.

**Budgets are declared before building and measured after.** Exceeding one must
be reported, not quietly shipped, and detail must not be silently stripped to
squeeze under.

**Method is stated in words** so the approach can be rejected, not only the
output. For a tree: tapered tubes along curves, 8 sides at the base to 4 at the
tips, three orders of branching, leaves as cards baked from the modelled leaf,
bark as material.

**Every asset ships review artefacts**, and they are not optional:

- a solid turnaround and a **wireframe turnaround from the same angles**
- triangle counts per part against the declared budget
- measured texel density against the tier's band
- the method, in prose

The builder reads its own wireframes and reports what they show — dense clumps
where nothing needs detail, branch joins that are a mess of overlapping tubes.

## Physics

Bullet rigid bodies with breakable constraints, driven by BOM masses. It serves
three purposes and is not a separate stage: **verification** (does the assembly
hold, does it fail sensibly), **destruction** (breakable constraints under load
*are* the destruction animation, and the debris at rest is the salvage table made
visible), and **weight sanity**.

**Limits, plainly.** Bullet has no concept of grain, shear strength or nail
withdrawal, and its thresholds are engine impulse units, not newtons. Relative
claims hold; absolute ones do not.

**Do not reach for FEA.** CalculiX and Elmer are free and capable but need
tetrahedral meshes and orthotropic wood properties, and handle contact worst —
which is the quantity that matters here. The number is already published; put it
in `capacity_N` with a `source` and calibrate Bullet against it.

**Calibrate once, library-wide.** One reference failure — a 1.2 m drop onto stone,
corner first — tuned until a crate fails as a crate should, then those units held
constant. Otherwise every asset invents its own scale and nothing is comparable.

Animation must be shape keys or armature bones. Drivers do not survive an
untrusted reopen (measured: every shape key pinned at 0.0, geometry byte-identical
across frames); drivers, lattices and modifier animation do not survive glTF.
Simulate at authoring time, bake, ship the bake.

## Infrastructure

The bridge drives **one shared Blender process**, and two concurrent runs corrupt
each other: during the prototype a second run wiped the scene three times and
overwrote the saved `.blend` 70 seconds after it was written. One Blender per run
on its own port, or a lock. Not optional at library scale.

## Where things live

- **`forge`** — the pipeline. Generators, schema, resolver, BOM engine,
  validators, material table. Code, tested, mostly without Blender.
- **Asset specs** — versioned, in git. The spec *is* the asset; the compiler does
  not house the source.
- **`~/GameAssets/forge/`** — built artefacts: `.blend`, `.glb`, renders, sprite
  sheets. Large, regenerable, gitignored, indexed by `assets.db` as a new source.

## Evidence

| Claim | Measured |
|---|---|
| Watertight solids are affordable | 148/148 closed, 5,816 faces, first attempt |
| Parts touch, never overlap | 0 interpenetrations, AABB at 0.01 mm |
| Fasteners derive from a rule | 112 nails from "two per bearing, staggered" |
| Every fastener does work | all 112 sampled: board → receiving member |
| Mass is plausible | 16.156 kg; 136 kg/m³ apparent, 27% of solid pine |
| Against reality | modelled nail 3.3 g vs ~3.5 g real |
| States are nearly free | 4 states, 41 objects moved, 0 geometry added |
| Hand-typed transforms fail | 3 of 4 state poses wrong on first attempt |
| Drivers die silently | shape keys 0.0 on reopen, mesh identical every frame |
| Morph animation survives glTF | weights bit-exact; only Blender's importer clamps |

Known imprecision, reported by the builder rather than found later: the nail
shank is a 12-sided prism, so its volume is 9.0% under a true cylinder. The BOM
reports the mesh that exists and carries a `faceting_note`.

## Proving order

Build up from a leaf; never down from the tree. Each addition is validated by
something that already exists and needs it.

1. **Crate → spec file.** Reverse the prototype into a declarative spec that
   regenerates it, and assert the BOM still comes to 16.156 kg. Until a spec
   reproduces a known-good asset, the format is unproven.
2. **The resolver.** Ask "can I make this crate?" and get an honest ordered build
   list — no saw, no nails without a forge, no forge without charcoal. Cheap,
   and it tells us whether the first twenty assets are twenty or two hundred.
3. **Oak leaf → oak at three stages.** The first organic asset, the first LOD
   bake, and the first test of the mesh-economy review path.
4. **Crowbar**, with its ancestry, as the first genuinely recursive build.
5. **Physics calibration** against a published fastener capacity.
6. **Composition** — the MCP verbs that assemble variants to meet a goal.

## Open questions

- Spec format: JSON round-trips best and hand-edits worst; TOML reads better.
  Undecided.
- Whether asset specs live in the `forge` repo or their own. The library outlives
  the pipeline, which argues for separate.
- Whether `gameassets` becomes the retrieval half of `find_assets`, or stays
  separate and is queried.
- How much history to research per node before it becomes a drag on building.
