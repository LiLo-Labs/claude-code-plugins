# blender

Drive a live Blender session from Claude Code: model procedurally with Blender
Python, generate organic meshes from a text prompt through a pluggable backend,
and prove the result is usable before anyone calls it finished.

## Why this exists

The hosted "AI for Blender" products charge $19–89/month for three things
bundled together: a desktop app, their model inference, and credits on a
generative-3D API. Only the third is a real cost. The bridge into Blender is a
solved problem, and the inference is already covered by a Claude Code
subscription — so this plugin unbundles the parts you can own and leaves you
paying only for GPU time you actually consume, on your own key, at a ceiling you
set.

The part worth building carefully is not the wiring. It is the loop that stops a
model from telling you a broken mesh is finished.

## What it does

```
Claude Code ──MCP──> blendpipe ──socket──> BlendPipe addon ──> Blender (bpy)
                          │
                          └──HTTP──> local GPU | Tripo | Meshy | Rodin
```

- **`execute_python`** — run Blender Python in the live session. This is the main
  way to model: free, instant, editable, and clean quad topology by construction.
- **`generate_mesh`** — text to mesh through whichever backend is configured,
  imported straight into the scene. Costs money on paid backends; free on yours.
- **`render_views`** — a turnaround on disk to actually look at.
- **`verify_geometry`** — non-manifold edges, degenerate and duplicate geometry,
  inverted normals, quad ratio, polycount, unapplied scale, real-world size, and
  whether the UVs are *usable* — overlap, texel density spread, packing — rather
  than merely present. Judged against a budget.
- **`scene_summary` / `object_info` / `export_mesh` / `save_file`** — the rest.

## The two guardrails

A prompt can ask for discipline. A hook enforces it.

- **Spend ceiling.** Paid generations are capped per session. An agent that
  re-rolls a bad prompt in a loop is fast, looks like progress, and is invisible
  until the invoice. Local generation is free and never counted.
- **Verify before export.** A mesh cannot leave without a passing
  `verify_geometry` behind it. Exporting something nobody measured is how a
  non-manifold edge reaches a game engine, where it costs hours instead of
  seconds.

## Procedural or generated

The choice that decides whether the result is good:

| Build it procedurally | Generate it |
|---|---|
| architecture, terrain, roads | creatures, characters, faces |
| furniture, crates, machinery | plants, foliage, organic clutter |
| weapons, vehicles, hard surface | sculpted ornament, cloth folds |
| anything modular or tiling | one-off hero assets with no primitive form |
| anything parametric | |

A language model writing `bpy` is genuinely excellent at the left column and
produces blobby nonsense in the right one. Generative 3D is the opposite. Most
real assets want both — generate the goblin, model the sword.

## Setup

`docs/setup.md`. Short version: install `blendpipe/addon.py` as a Blender addon,
press Start in the BlendPipe sidebar panel, run `/blender-status`.

Generation is optional. Set `BLENDPIPE_LOCAL_URL` to run it on your own GPU
(`docs/local-backend.md`) or one of `TRIPO_API_KEY` / `MESHY_API_KEY` /
`RODIN_API_KEY` to use a paid API. Local always wins when both are configured, so
moving to your own hardware later is one environment variable and nothing else.

## Commands

| Command | What it does |
|---|---|
| `/blender-status` | connection, backend, cost |
| `/blender-make` | model or generate, then render, verify and report |
| `/blender-check` | measure the geometry and say what would fail downstream |
| `/blender-export` | verify, then export to the right format for the target |
| `/blender-agent` | hand a whole asset to a headless Claude and let it work unattended |

## Tests

```
python3 plugins/blender/tests/test_blendpipe.py      # 99 checks, no Blender needed
python3 plugins/blender/tests/test_live_blender.py   # 65 checks against real Blender
```

The first suite covers the bridge protocol, the gate evaluator, the backend
resolution order, the MCP surface and both guardrails. A fake speaks the addon's
wire protocol, so none of it needs Blender running.

The second launches Blender headless, loads the addon, and drives the real
socket. It exists because the fake answers `execute` with a canned report, which
proves the wire protocol and the gate arithmetic and can prove nothing about
`bpy` — the gap where a probe that could not parse, a render that named the wrong
engine, and renders of unlit scenes all passed. It finds Blender automatically or
takes `BLENDER_BIN`, and skips rather than fails when there is none.
