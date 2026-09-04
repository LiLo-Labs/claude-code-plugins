---
name: blender
description: Use when the user wants to model, generate, inspect, fix or export 3D assets in Blender - building geometry procedurally with Blender Python, generating organic meshes from a text prompt, checking a mesh for non-manifold edges, topology, UVs, scale or polycount, rendering a turnaround to judge a result, or exporting to glb/fbx/obj/stl for a game engine, renderer or printer. Triggers on "model this in Blender", "make me a 3D X", "text to 3D", "fix this mesh", "check the topology", "clean up this model", "export for Godot/Unity/Unreal".
---

# Blender

The `blender` MCP tools drive a live Blender session. `execute_python` runs code
inside it, `generate_mesh` buys a mesh from a backend, `render_views` shows you
what you made, and `verify_geometry` tells you whether it is actually usable.
Everything between those is judgment, and this skill is that judgment.

Two rules that never bend:

- **Nothing is finished until it has been rendered, looked at, and verified.**
  A model you have not seen and not measured is a guess. Saying "done" on a guess
  is the failure mode this whole plugin exists to prevent.
- **Generation costs the user's money. Procedural does not.** Never call
  `generate_mesh` on a subject that `execute_python` builds better, and never
  call it twice on a prompt you have not improved in between.

## Start of every session

Call `blender_status`. It tells you whether Blender is reachable, which backend
is configured, and what it costs. If Blender is not running, say so and give the
three setup steps from the error — do not attempt other tools and report a
cascade of the same failure.

## The one real decision: procedural or generated

This is the choice that determines whether the result is good, and it is made
before any other work.

| Build it procedurally with `execute_python` | Generate it with `generate_mesh` |
|---|---|
| Architecture, rooms, terrain, roads | Creatures, characters, faces |
| Furniture, crates, barrels, machinery | Plants, trees, organic clutter |
| Weapons, vehicles, hard-surface props | Sculpted statues, ornament, cloth folds |
| Anything modular, repeated, or tiling | Anything you would sculpt rather than model |
| Anything parametric ("make it 20% taller") | One-off hero assets with no clean primitive form |
| Anything the user will want to edit numerically | |

Procedural is free, instant, exactly specified, re-runnable with changed numbers,
and produces clean quad topology by construction. Generation is the only sane
option for organic form, and it costs real money per attempt and arrives as
triangle soup at arbitrary scale.

When the subject is mixed — a goblin holding a sword — generate the goblin and
model the sword. Do not generate the whole thing and hope.

**When you are unsure, build procedurally first.** A free thirty-second attempt
that the user rejects costs nothing; a paid generation they reject costs money
and taught you less, because a procedural failure tells you exactly which
parameter was wrong.

## Writing Blender Python

- **`bpy.data` over `bpy.ops`.** Operators depend on the UI context — the active
  object, the current mode, which area the mouse is over — and from here that
  context is whatever Blender happened to be left in. `bpy.data.meshes.new` and
  `bmesh` work the same way every time. Use `bpy.ops` only where there is no
  data-level equivalent (importers, some modifier applies, remesh operators).
- **Build with `bmesh` for anything non-trivial.** It is faster than operator
  spam and it is the only way to get predictable topology.
- **Assign to `result`** to get structured data back. Do not print a dict and
  parse the text.
- **One coherent step per call.** Not one line, and not an entire asset. A call
  that creates the base mesh, one that adds the detail, one that does materials —
  so that when something is wrong you know which step to fix.
- **Name every object you create.** `Cube.003` is how a scene becomes unworkable.

Conventions to hold to unless the user says otherwise: **+Z up, -Y front**,
metric units, objects built at the world origin, real-world scale (a door is
2.0m, not 2.0 "units"), and transforms applied before export.

## The loop

Every asset goes through the same five steps. Skipping step 3 or 4 is what
produces confident nonsense.

1. **Plan.** Say in one or two sentences what you are building, which route
   (procedural or generated), and roughly what it will cost. For a generation,
   say the dollar figure *before* spending it.
2. **Build.** `execute_python`, or `generate_mesh`.
3. **Look.** `render_views`, then **read the returned PNG paths**. The tool
   returns file paths; reading them is what actually puts the image in front of
   you. A turnaround you did not open told you nothing.
4. **Verify.** `verify_geometry` with the right preset. Blocking findings are not
   advisory — fix them and re-verify.
5. **Report.** Show the user the render and the verdict together. If anything is
   still wrong, say what and why, rather than presenting it as finished.

Iterate between 2 and 4. Only step 5 talks to the user as though the work is
done.

## Reading a render honestly

When you look at the turnaround, ask specific questions rather than "does this
look good":

- Is the **silhouette** readable from every angle? A shape that only works from
  the front is not a 3D asset.
- Is the **scale** right relative to the grid and to anything else in the scene?
- Are there **holes, spikes, or floating fragments** visible? Those are geometry
  defects the verify step will confirm.
- Does it match **what the user actually asked for**, not what was convenient to
  build?

If the answer to any of these is no, go back to step 2. Say what you saw that
sent you back — "the back of the head is hollow" is useful; "iterating" is not.

## Verify presets

| Preset | Use for | Enforces |
|---|---|---|
| `game` | real-time assets, the default | 100k face cap, UVs required, applied scale |
| `print` | 3D printing | watertight, no face cap, scale ignored |
| `render` | film/stills, background props | permissive, 2M faces |
| `none` | measuring only | nothing blocks |

Add `min_quad_ratio: 0.8` any time "clean topology" was promised or implied.
Generated meshes are all-triangle and will fail it — that is the point. A quad
remesh is the fix, not a lower threshold.

**Never relax a budget to make a check pass.** If the budget is genuinely wrong
for this asset, say so to the user and let them change it.

## Fixing what verification finds

Common findings and what actually fixes them:

- **duplicate verts** — merge by distance first, before UVs or subdivision;
  everything downstream is corrupted by them.
- **non-manifold edges** — usually interior faces from a boolean, or a boundary
  that should have been bridged. Look at it in a render before deleting anything.
- **inverted normals** — recalculate outside.
- **triangle soup** — a Remesh or QuadriFlow pass, then re-verify. Expect to lose
  some detail; say so.
- **unapplied scale** — apply it, and re-check dimensions afterwards, because
  applying scale is exactly when a model's real size becomes visible.
- **no UVs** — Smart UV Project is the floor, not a good unwrap. Say which it is.

## Cost discipline

- Say the price before the first generation, and say the running total if you
  generate more than twice.
- Improve the prompt between attempts. Re-rolling the same prompt is spending
  money on variance.
- Prefer an untextured preview when the shape is what is in question — you find
  out the silhouette is wrong before paying to texture it.
- `list_backends` shows what is configured. If a local backend is available,
  it is used automatically and generation is free; say that rather than warning
  about cost that is not being incurred.

## Exporting

Run `verify_geometry` first. Every time. Then match the format to the target:
**glb** for the web, three.js and most modern pipelines; **fbx** for Unity and
Unreal; **obj** for a static prop with no rig; **stl** for printing, and only
after a `print` preset verify.
