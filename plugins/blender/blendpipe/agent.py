"""Drive Blender headlessly with `claude -p`, on the user's own subscription.

The hosted products charge $19-89/month for a loop that is, mechanically, a
language model writing `bpy` through MCP and looking at its own renders. That
loop is this file. `claude -p` authenticates as the user, so the inference is
already paid for by a subscription they have, and the only thing left that costs
money is generative-3D, which this does not touch.

Why an agent rather than a staged pipeline
------------------------------------------
Every stage here -- unwrap, material, retopo -- is reachable through
`execute_python`. Handing the model the goal and letting it choose the method
beats prescribing one: asked for an even, non-overlapping unwrap it projected
each face into its own plane basis with U along the longest edge, which is an
exact isometry and orients wood grain along every beam for free. The obvious
instruction to write would have been "use Smart UV Project", which is worse.

So GUIDANCE below states goals and the measurements that decide them, and never
the operator to call. Prescribing the method caps the result at the author's
knowledge of Blender.

No guardrails run here, by construction: the hooks are plugin hooks, and this
attaches the MCP server with --mcp-config rather than loading the plugin, so
nothing blocks an export. `verify_geometry` still measures -- it just reports.
"""

import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.expanduser(os.environ.get("BLENDPIPE_RUNS", "~/.blendpipe/runs"))

#: Sonnet is the headless default and it hallucinates about renders -- the sibling
#: plugins record it inventing "tattered cloak/fringe edge" on a grey seashell.
#: Pin the model; this is not a preference.
MODEL = os.environ.get("BLENDPIPE_MODEL", "claude-opus-5")

TOOLS = [
    "mcp__blender__blender_status",
    "mcp__blender__scene_summary",
    "mcp__blender__object_info",
    "mcp__blender__execute_python",
    "mcp__blender__render_views",
    "mcp__blender__verify_geometry",
    "mcp__blender__export_mesh",
    "mcp__blender__save_file",
    "mcp__blender__list_backends",
    # Not optional. render_views returns paths; Read is what puts the pixels in
    # front of the model. Without it the critique loop is a model describing an
    # image it has not seen.
    "Read",
]

GUIDANCE = """\
You are driving a live Blender session through the blender MCP tools.

Work through execute_python. Prefer bpy.data over bpy.ops where both work --
bpy.ops depends on context and fails in ways that are hard to diagnose from
here.

Nothing is finished until you have rendered it, opened the render, and measured
it. render_views returns file paths; READ them with the Read tool. A render you
did not open tells you nothing, and describing an image you have not seen is the
single most common way this pipeline produces confident nonsense.

verify_geometry measures whether the mesh is USABLE. The render tells you
whether it is RIGHT. Neither substitutes for the other: a watchtower whose legs
stopped short of its platform once passed at 98% quads, watertight, zero
findings. Clean geometry in the wrong shape passes every measurement there is.

These are the targets. How you hit them is yours to choose -- the obvious
operator is often not the best one.

MODELLING
  Build procedurally for anything hard-surface, architectural, modular or
  parametric. Reach for generate_mesh only for organic form, and say the cost
  before spending it.

TOPOLOGY
  Quads where it will deform or subdivide. n-gons are acceptable on flat
  hard-surface faces and bad anywhere that bends. If a mesh arrives as triangle
  soup, remesh it rather than describing it as clean.

UVS
  The target is measurable, and verify_geometry reports all three:
    - islands that do not overlap (area_sum at or below 1.0 -- above 1.0 is
      arithmetic proof they overlap, since the unit square cannot hold more)
    - texel density even across the mesh (ratio near 1.0; past 4x one part is
      visibly softer than its neighbour at the same texture size)
    - packed reasonably tight, so resolution is not wasted on empty space
  Joining objects stacks their unwraps -- thirty joined boxes have a UV layer
  and cannot be textured. Orienting U along the length of a beam or up the slope
  of a roof makes grain and courses line up for free.

MATERIALS
  Real Blender shader nodes, Principled BSDF, assigned to the faces they belong
  to. Procedural texture nodes for grain and variation. Keep them editable --
  do not bake unless asked. Watch for anisotropic mapping artefacts: stretching
  UV heavily and then sampling noise gives parallel stripes rather than grain,
  and micro-detail bump must sample an unstretched space or it smears with it.

SCALE
  Real-world dimensions, scale applied. An unapplied scale breaks modifiers,
  physics and most exporters.

FINISH
  End with a short plain-text report: what you built, what the measurements say,
  and what is still wrong. Say what you could not fix. Do not describe something
  as finished when a measurement disagrees.
"""


def mcp_config(path):
    """Write the MCP config that attaches this plugin's server to `claude -p`."""
    server = os.path.join(HERE, "mcp_blender.py")
    config = {"mcpServers": {"blender": {
        "command": sys.executable, "args": [server], "env": {}}}}
    with open(path, "w") as handle:
        json.dump(config, handle, indent=2)
    return path


def run(task, run_dir=None, max_turns=80, model=MODEL, timeout=3600, extra=""):
    """Run one task to completion. Returns the parsed CLI envelope plus paths."""
    if shutil.which("claude") is None:
        raise RuntimeError(
            "no 'claude' on PATH — this drives Blender with `claude -p` on your "
            "own subscription, so the CLI has to be installed and logged in")

    run_dir = run_dir or os.path.join(RUNS, time.strftime("%Y%m%d-%H%M%S-agent"))
    os.makedirs(run_dir, exist_ok=True)

    prompt = GUIDANCE + "\n\nTASK\n" + task.strip() + ("\n\n" + extra if extra else "")
    with open(os.path.join(run_dir, "prompt.txt"), "w") as handle:
        handle.write(prompt)

    command = [
        "claude", "-p", prompt,
        "--mcp-config", mcp_config(os.path.join(run_dir, "mcp.json")),
        "--model", model,
        "--max-turns", str(max_turns),
        "--output-format", "json",
    ]
    for tool in TOOLS:
        command += ["--allowedTools", tool]

    started = time.time()
    finished = subprocess.run(command, capture_output=True, text=True, timeout=timeout)

    if finished.returncode != 0:
        # Silence here cost a debugging round in the sibling plugins; keep the
        # evidence next to the run it belongs to.
        failure = os.path.join(run_dir, "failed.txt")
        with open(failure, "w") as handle:
            handle.write("exit %d\n\nSTDERR\n%s\n\nSTDOUT\n%s\n"
                         % (finished.returncode, finished.stderr[:4000],
                            finished.stdout[:4000]))
        raise RuntimeError("claude exited %d; see %s" % (finished.returncode, failure))

    try:
        envelope = json.loads(finished.stdout)
    except ValueError:
        envelope = {"result": finished.stdout}

    manifest = {
        "task": task,
        "model": model,
        "run_dir": run_dir,
        "turns": envelope.get("num_turns"),
        "seconds": round(time.time() - started, 1),
        # Reported for visibility. `claude -p` bills to the subscription; this is
        # the API-equivalent figure, not a charge.
        "cost_usd_equivalent": envelope.get("total_cost_usd"),
        "actor": "llm:%s@headless" % model,
    }
    with open(os.path.join(run_dir, "manifest.json"), "w") as handle:
        json.dump(manifest, handle, indent=2)
    with open(os.path.join(run_dir, "report.md"), "w") as handle:
        handle.write(envelope.get("result", ""))

    manifest["report"] = envelope.get("result", "")
    return manifest


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print((__doc__ or "").strip())
        print("\nusage: python3 -m blendpipe.agent \"model a wooden watchtower, "
              "unwrap and texture it\" [--turns N] [--model M]")
        return 0

    task, turns, model = argv[0], 80, MODEL
    rest = argv[1:]
    while rest:
        flag, rest = rest[0], rest[1:]
        if flag == "--turns" and rest:
            turns, rest = int(rest[0]), rest[1:]
        elif flag == "--model" and rest:
            model, rest = rest[0], rest[1:]

    result = run(task, max_turns=turns, model=model)
    print(result.pop("report"))
    print("\n---\n" + json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
