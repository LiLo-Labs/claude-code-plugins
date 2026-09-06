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

import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

from . import bridge, viewport

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

ANIMATION
  Two failure modes here are silent, produce correct-looking measurements at
  authoring time, and only surface on someone else's machine.

  Drivers do not run in an untrusted file. Blender refuses driver expressions
  unless Auto Run Python Scripts is on, which is off by default everywhere. A rig
  that routes custom properties through drivers into shape keys animates its
  properties, leaves every shape key at zero, and renders a mesh that is
  byte-identical on every frame. It works while you build it and dies when the
  file is reopened. Key the shape keys directly in the Action instead.

  Only morph targets and armature bones survive glTF. Drivers do not. Lattice
  deformers do not. Modifier animation does not. So anything that must move in a
  game engine has to be a shape key or a bone, and anything else has to be baked
  into one before export.

  Do not report an animation as working on the strength of the viewport. Sample
  evaluated vertex positions across frames and report the displacement; confirm
  the loop closes by measuring frame N+1 against frame 1; and if it is going to
  an engine, export it and re-import it and measure the copy.

WORK WHERE IT CAN BE SEEN
  Someone may have this Blender open in front of them. The workspace tab,
  shading mode, framing and status bar are driven for you from outside, so do
  not spend calls on those. What only you can do safely, because only you know
  when it will not break the next operation:

    - Go into Edit Mode for selection work rather than doing it all through
      bpy.data, so a watcher sees what is being selected and why.
    - Leave the subject selected and active when you finish a step.
    - Come back to Object Mode before anything that assumes it.

  This is worth a call, not a budget. Never let it change what you build.

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


def blender_listening(host=None, port=None, timeout=2.0):
    """True when something is accepting on the bridge port.

    Deliberately a TCP connect and not a `ping`. The addon accepts connections
    on a background thread and answers them on Blender's main thread, so during
    a long render or remesh the main thread is busy and a ping round-trip blocks
    — while the socket still accepts. Connect-only tells "Blender has gone away"
    apart from "Blender is working", which a ping cannot.
    """
    host = host or os.environ.get("BLENDPIPE_HOST", "127.0.0.1")
    port = int(port or os.environ.get("BLENDPIPE_PORT", "9876"))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class _Watchdog:
    """Kill the run if Blender disappears underneath it.

    An unattended agent talking to a closed socket does not stop. It gets an
    error, reasons about it, tries again, and burns every turn it was given
    while producing nothing — nine minutes of that is what prompted this. The
    preflight below catches Blender being absent at the start; this catches it
    dying at turn three, which the preflight cannot.
    """

    def __init__(self, process, every=5.0, tolerate=2):
        self.process, self.every, self.tolerate = process, every, tolerate
        self.lost = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _watch(self):
        misses = 0
        while not self._stop.wait(self.every):
            if self.process.poll() is not None:
                return
            misses = 0 if blender_listening() else misses + 1
            if misses >= self.tolerate:
                self.lost = True
                self.process.terminate()
                return


#: Every live run, so there is always something to point `--stop` at.
REGISTRY = os.path.join(RUNS, "running.json")


def _live():
    """Runs that are actually still going, pruning any that have exited."""
    try:
        with open(REGISTRY) as handle:
            entries = json.load(handle)
    except (OSError, ValueError):
        return []
    alive = []
    for entry in entries:
        try:
            os.kill(entry["pid"], 0)
        except OSError:
            continue
        alive.append(entry)
    return alive


def _write_registry(entries):
    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    with open(REGISTRY, "w") as handle:
        json.dump(entries, handle, indent=2)


def _register(run_dir, pid):
    entries = _live()
    entries.append({"pid": pid, "run_dir": run_dir, "started": time.time()})
    _write_registry(entries)
    with open(os.path.join(run_dir, "agent.pid"), "w") as handle:
        handle.write("%d\n" % pid)


def stop_all():
    """Kill every live run. The off switch that exists however one was launched."""
    stopped = []
    for entry in _live():
        pid = entry["pid"]
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except OSError:
                break
            time.sleep(0.25)
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        stopped.append(entry)
    _write_registry([])
    return stopped


def running():
    """What is live right now, so 'is anything driving Blender?' has an answer."""
    return _live()


def _summarise(event):
    """Turn one stream-json event into at most one line worth printing.

    Deliberately lossy. The full stream goes to transcript.jsonl; what reaches a
    watching human should be the shape of the work -- which tool, on what -- not
    every token. `execute_python` gets its first non-import line, because that is
    almost always the operation being performed.
    """
    kind = event.get("type")

    if kind == "system" and event.get("subtype") == "init":
        return [{"kind": "start", "tools": len(event.get("tools") or [])}]

    if kind == "assistant":
        out = []
        for block in (event.get("message") or {}).get("content") or []:
            # Reasoning is the most useful thing to show a person watching and
            # the least useful thing to show in full. First sentence only.
            if block.get("type") == "thinking":
                text = (block.get("thinking") or "").strip().split(". ")[0]
                if text:
                    out.append({"kind": "think", "tool": "thinking", "detail": text[:160]})
                continue
            if block.get("type") == "text":
                text = (block.get("text") or "").strip().split("\n")[0]
                if text:
                    out.append({"kind": "say", "tool": "says", "detail": text[:160]})
                continue
            if block.get("type") != "tool_use":
                continue
            name = (block.get("name") or "").rsplit("__", 1)[-1]
            args = block.get("input") or {}
            detail = ""
            if name == "execute_python":
                lines = [l.strip() for l in (args.get("code") or "").splitlines()]
                body = [l for l in lines
                        if l and not l.startswith(("#", "import ", "from "))]
                detail = (body[0] if body else "")[:78]
            elif name == "render_views":
                detail = "angles %s" % (args.get("angles") or [0])
            elif name in ("verify_geometry", "export_mesh"):
                detail = str(args.get("objects") or args.get("path") or "")[:60]
            out.append({"kind": "tool", "tool": name, "detail": detail})
        return out

    if kind == "result":
        return [{"kind": "done",
                 "turns": event.get("num_turns"),
                 "cost": event.get("total_cost_usd"),
                 "error": event.get("is_error")}]

    return []


#: How a summary kind maps to the icon the sidebar draws it with.
_PANEL_KIND = {
    "think": "think", "say": "step", "scene": "build", "start": "step", "done": "verify",
}
_TOOL_KIND = {
    "execute_python": "build", "render_views": "render", "verify_geometry": "verify",
    "export_mesh": "verify", "save_file": "step",
}


def push_to_blender(summary, turn=None):
    """Mirror one progress line into Blender's own sidebar.

    Best-effort and deliberately swallowing: the panel is a convenience, and a
    run must never fail because a cosmetic update did. Blender being busy with
    the very work being reported is the normal case, not an error.
    """
    if summary.get("kind") == "scene":
        entry = "%s — %d obj, %d faces, %d mats" % (
            summary["stage"], summary["objects"], summary["faces"], summary["materials"])
        params = {"kind": "build", "entry": entry, "stage": summary["stage"]}
    elif summary.get("kind") in ("think", "say"):
        params = {"kind": _PANEL_KIND[summary["kind"]], "entry": summary["detail"]}
    elif summary.get("kind") == "tool":
        text = summary["tool"] + ((" " + summary["detail"]) if summary["detail"] else "")
        params = {"kind": _TOOL_KIND.get(summary["tool"], "tool"), "entry": text}
    elif summary.get("kind") == "done":
        params = {"kind": "verify", "entry": "finished, %s turns" % summary.get("turns"),
                  "stage": "done"}
    else:
        return
    if turn is not None:
        params["turn"] = turn
    try:
        bridge.call("activity", params, timeout=10)
    except Exception:
        pass


def _print_event(summary):
    """Default progress line. One line per thing that happened, to stderr.

    stderr rather than stdout so the report stays pipeable on its own.
    """
    kind = summary.get("kind")
    if kind == "start":
        line = "· connected, %d tools" % summary.get("tools", 0)
    elif kind in ("think", "say"):
        # Without this the log goes silent for minutes while the model plans,
        # which is the exact "is it working or wedged" ambiguity this printer
        # exists to remove. It was being extracted for the Blender panel and
        # dropped here.
        line = "· %-16s %s" % ("thinking" if kind == "think" else "says",
                               summary["detail"])
    elif kind == "tool":
        line = "· %-16s %s" % (summary["tool"], summary["detail"])
    elif kind == "scene":
        line = "· scene            %s — %d objects, %d faces, %d materials" % (
            summary["stage"], summary["objects"], summary["faces"], summary["materials"])
    elif kind == "done":
        line = "· done, %s turns" % summary.get("turns")
    else:
        return
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def run(task, run_dir=None, max_turns=80, model=MODEL, timeout=3600, extra="",
        on_event=None, follow=True, panel=True):
    """Run one task to completion. Returns the parsed CLI envelope plus paths.

    `on_event` receives a small dict per step (see _summarise) and defaults to
    printing. `follow` drives Blender's own window to track the work.
    """
    if shutil.which("claude") is None:
        raise RuntimeError(
            "no 'claude' on PATH — this drives Blender with `claude -p` on your "
            "own subscription, so the CLI has to be installed and logged in")

    # Preflight before spending a single turn. Every tool in this run goes
    # through the bridge, so with Blender shut there is nothing to do and the
    # agent cannot discover that in a way that makes it stop.
    if not blender_listening():
        raise RuntimeError(
            "Blender is not reachable on %s:%s — start it with the BlendPipe "
            "addon running before handing it unattended work. Nothing in this "
            "run can do anything without it."
            % (os.environ.get("BLENDPIPE_HOST", "127.0.0.1"),
               os.environ.get("BLENDPIPE_PORT", "9876")))

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
        # Streamed rather than a single JSON blob at the end. A run is silent
        # for minutes while the model plans, and a silent run and a wedged run
        # look identical from outside -- which is how an earlier run spent nine
        # minutes talking to a closed socket with nobody the wiser.
        "--output-format", "stream-json",
        "--verbose",
        # --allowedTools grants permission; it does not control what is loaded.
        # Without these three the run inherits the user's entire environment --
        # every plugin, skill and MCP server they have installed. Measured at
        # 155 tools on this machine, against the eleven it needs, and the run
        # spent its first turns on ToolSearch and Skill before it modelled
        # anything. Turns are budgeted, so that is not merely untidy.
        "--strict-mcp-config",       # only the blender server passed above
        "--setting-sources", "",     # no user/project/local settings, so no plugins
        "--tools", "Read",           # the only built-in needed: opening renders
    ]
    for tool in TOOLS:
        command += ["--allowedTools", tool]

    on_event = on_event or _print_event
    if panel:
        # Start from empty, so what the sidebar shows is this run and not the
        # ghost of the last one.
        try:
            bridge.call("activity", {"clear": True, "stage": "starting",
                                     "note": task[:60], "turn": 0}, timeout=10)
        except Exception:
            pass
    started = time.time()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, bufsize=1)
    watchdog = _Watchdog(process).start()

    # Killing this runner must not leave `claude` behind still driving Blender.
    # It happened: pkill on the wrapper orphaned the child, which carried on
    # rebuilding the scene underneath the next run and overwrote its output
    # while that run was measuring it. An orphan here is not a stray process,
    # it is a second author of the same file.
    def _reap(signum=None, _frame=None):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if signum is not None:
            raise SystemExit(128 + signum)

    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            previous[sig] = signal.signal(sig, _reap)
        except (ValueError, OSError):
            pass          # not the main thread, or the platform disallows it
    atexit.register(_reap)

    # A run detached to survive the harness also survives a user pressing stop:
    # the interrupt reaches whatever launched it, never the child. Two runs once
    # drove one Blender for twenty minutes after being told to stop. So every
    # run records where it is, and `--stop` is an off switch that always exists.
    _register(run_dir, process.pid)

    follower = None
    if follow:
        follower = viewport.Follower(
            on_change=lambda state: on_event({"kind": "scene", **state})).start()

    # Appended as events arrive, not written at the end. A transcript that only
    # exists once the run finishes cannot tell you anything about a run that has
    # not finished, which is the only time you need it.
    transcript_path = os.path.join(run_dir, "transcript.jsonl")
    transcript_file = open(transcript_path, "w", buffering=1)

    envelope, transcript = {}, []
    try:
        for line in process.stdout or ():
            line = line.strip()
            if not line:
                continue
            transcript.append(line)
            transcript_file.write(line + "\n")
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "result":
                envelope = event
            turns = (envelope or {}).get("num_turns")
            for summary in _summarise(event):
                on_event(summary)
                if panel:
                    push_to_blender(summary, turn=turns)
        process.wait(timeout=timeout)
    finally:
        watchdog.stop()
        if follower:
            follower.stop()
        transcript_file.close()

    stderr = process.stderr.read() if process.stderr else ""
    finished = subprocess.CompletedProcess(command, process.returncode, "\n".join(transcript), stderr)

    if watchdog.lost:
        failure = os.path.join(run_dir, "failed.txt")
        with open(failure, "w") as handle:
            handle.write("Blender stopped listening %.0fs into the run; the agent was "
                         "terminated rather than left talking to a closed socket.\n\n%s\n"
                         % (time.time() - started, (finished.stdout or "")[:4000]))
        raise RuntimeError(
            "Blender went away %.0fs into the run, so it was stopped. Whatever it had "
            "built is gone with the session unless it saved. See %s"
            % (time.time() - started, failure))

    if finished.returncode != 0:
        # Silence here cost a debugging round in the sibling plugins; keep the
        # evidence next to the run it belongs to.
        failure = os.path.join(run_dir, "failed.txt")
        with open(failure, "w") as handle:
            handle.write("exit %d\n\nSTDERR\n%s\n\nSTDOUT\n%s\n"
                         % (finished.returncode, finished.stderr[:4000],
                            finished.stdout[:4000]))
        raise RuntimeError("claude exited %d; see %s" % (finished.returncode, failure))

    # `envelope` came off the stream as the terminal "result" event. Falling back
    # to the raw transcript keeps a truncated run readable rather than empty.
    if not envelope:
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
        print("       python3 -m blendpipe.agent --running")
        print("       python3 -m blendpipe.agent --stop")
        return 0

    if argv[0] == "--running":
        live = running()
        for entry in live:
            print("%d  %s  %.0fs" % (entry["pid"], entry["run_dir"],
                                     time.time() - entry["started"]))
        if not live:
            print("nothing running")
        return 0

    if argv[0] == "--stop":
        stopped = stop_all()
        for entry in stopped:
            print("stopped %d (%s)" % (entry["pid"], entry["run_dir"]))
        if not stopped:
            print("nothing running")
        return 0

    task, turns, model = argv[0], 80, MODEL
    rest = argv[1:]
    while rest:
        flag, rest = rest[0], rest[1:]
        if flag == "--turns" and rest:
            turns, rest = int(rest[0]), rest[1:]
        elif flag == "--model" and rest:
            model, rest = rest[0], rest[1:]

    try:
        result = run(task, max_turns=turns, model=model)
    except RuntimeError as exc:
        # These are all conditions with an answer — Blender shut, no CLI, the
        # session dying mid-run. A traceback buries the sentence that says what
        # to do about it.
        sys.stderr.write("%s\n" % exc)
        return 1

    print(result.pop("report"))
    print("\n---\n" + json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
