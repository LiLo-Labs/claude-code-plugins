#!/usr/bin/env python3
"""MCP stdio server for a live Blender session.

Dependency-free: speaks the MCP JSON-RPC protocol directly rather than pulling in
an SDK, so it runs on any Python 3.9+ with no install step — matching the other
servers in this marketplace.

The tools are shaped around one belief: the model should drive Blender by writing
Blender Python, not by calling a hundred pre-baked wrappers. `execute_python` is
therefore the primary tool and everything else exists because it cannot be done
well in a snippet — reaching a paid generator, framing a turnaround, or measuring
geometry the same way every time so that "it looks fine" can be contradicted.

Tools: blender_status, list_backends, scene_summary, object_info, execute_python,
       generate_mesh, render_views, verify_geometry, export_mesh, save_file
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from blendpipe import bridge, gates  # noqa: E402
from blendpipe.backends import BackendError, describe_all, resolve  # noqa: E402

PROTOCOL = "2024-11-05"
VERSION = "0.1.0"

#: Where generated meshes and renders land. Kept outside the project tree by
#: default so a modelling session never accidentally commits a 40 MB GLB.
RUNS = os.path.expanduser(os.environ.get("BLENDPIPE_RUNS", "~/.blendpipe/runs"))


def run_dir(label):
    path = os.path.join(RUNS, "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), label))
    os.makedirs(path, exist_ok=True)
    return path


TOOLS = [
 {"name": "blender_status",
  "description": "Check whether Blender is reachable and what is configured. Call this "
                 "first in any session that will touch Blender — every other tool fails "
                 "with the same connection error and this one explains how to fix it.",
  "inputSchema": {"type": "object", "properties": {}}},

 {"name": "list_backends",
  "description": "Which mesh-generation backends are configured, what they cost per "
                 "generation, and what is missing for the ones that are not. Generation "
                 "spends the user's money — check here and say the cost before doing it.",
  "inputSchema": {"type": "object", "properties": {}}},

 {"name": "scene_summary",
  "description": "Inventory of the current scene: object counts by type, per-object "
                 "vertex/face counts and dimensions, collections, selection, units and "
                 "render engine. Use before touching anything, and after any change that "
                 "was meant to create or remove objects.",
  "inputSchema": {"type": "object", "properties": {
     "limit": {"type": "integer", "default": 100,
               "description": "max objects listed individually; counts are always complete"}}}},

 {"name": "object_info",
  "description": "Everything about one object: transform, world bounding box, modifier "
                 "stack, materials, and for meshes the tri/quad/ngon breakdown and UV "
                 "layers. Use on the handful of objects that matter after scene_summary.",
  "inputSchema": {"type": "object", "properties": {
     "name": {"type": "string"}}, "required": ["name"]}},

 {"name": "execute_python",
  "description": "Run Python inside the live Blender session. This is the main way to "
                 "model: bpy and mathutils are already in scope, print() output comes "
                 "back, and assigning to `result` returns that value as JSON. Prefer "
                 "bpy.data over bpy.ops where both work — bpy.ops depends on context and "
                 "fails in ways that are hard to diagnose from here.",
  "inputSchema": {"type": "object", "properties": {
     "code": {"type": "string", "description": "Python source; multi-line is fine"},
     "timeout": {"type": "number", "default": 600,
                 "description": "seconds to allow; raise it for heavy remesh or simulation"}},
   "required": ["code"]}},

 {"name": "generate_mesh",
  "description": "Generate an organic mesh from a text prompt using the configured backend "
                 "and import it into the scene. THIS COSTS MONEY on paid backends — say "
                 "the cost first. Use it for organic subjects (creatures, characters, "
                 "foliage, sculpted props). For hard-surface, architectural, modular or "
                 "parametric work, write bpy through execute_python instead: it is free, "
                 "instant, editable and produces better topology.",
  "inputSchema": {"type": "object", "properties": {
     "prompt": {"type": "string", "description": "what to generate, described visually"},
     "backend": {"type": "string", "description": "override the configured backend: local, tripo, meshy, rodin"},
     "name": {"type": "string", "description": "name for the imported object"},
     "import": {"type": "boolean", "default": True, "description": "import into Blender when done"},
     "options": {"type": "object", "description": "backend-specific: art_style, topology, "
                 "target_polycount, face_limit, quad, texture, quality, tier, timeout"}},
   "required": ["prompt"]}},

 {"name": "render_views",
  "description": "Render a turnaround to PNG files on disk and return their paths — then "
                 "READ those paths to actually look at them. Judging a model without "
                 "looking at it is the single most common way this pipeline produces "
                 "confident nonsense. Defaults to four views at 640px on EEVEE, which is "
                 "seconds, not minutes.",
  "inputSchema": {"type": "object", "properties": {
     "angles": {"type": "array", "items": {"type": "number"}, "default": [0, 90, 180, 270],
                "description": "camera azimuths in degrees"},
     "elevation": {"type": "number", "default": 20},
     "resolution": {"type": "integer", "default": 640},
     "focus": {"type": "array", "items": {"type": "string"},
               "description": "object names to frame; omit to frame everything visible"},
     "engine": {"type": "string", "description": "BLENDER_EEVEE_NEXT or CYCLES; default is EEVEE for speed"},
     "samples": {"type": "integer", "default": 32, "description": "Cycles samples, ignored on EEVEE"}}}},

 {"name": "verify_geometry",
  "description": "Measure the real geometry and judge it against a budget: non-manifold "
                 "edges, degenerate and duplicate geometry, inverted normals, quad ratio, "
                 "polycount, UVs, unapplied scale, real-world size. A render says whether "
                 "it is the RIGHT thing; this says whether it is a USABLE thing. Run it "
                 "before telling the user anything is finished, and always before export.",
  "inputSchema": {"type": "object", "properties": {
     "objects": {"type": "array", "items": {"type": "string"},
                 "description": "names to check; omit for every mesh in the scene"},
     "preset": {"type": "string", "enum": ["game", "print", "render", "none"], "default": "game",
                "description": "game: 100k faces, UVs, applied scale. print: watertight, no "
                               "polycount cap. render: permissive. none: report only."},
     "max_faces": {"type": "integer"},
     "min_quad_ratio": {"type": "number", "description": "0..1; use 0.8 when clean topology was promised"},
     "require_watertight": {"type": "boolean"},
     "require_uvs": {"type": "boolean"},
     "max_dimension": {"type": "number", "description": "longest side in scene units"},
     "min_dimension": {"type": "number"}}}},

 {"name": "export_mesh",
  "description": "Export objects to glb, gltf, obj, fbx or stl. Run verify_geometry first "
                 "— exporting a mesh that has not been checked is how a defect reaches the "
                 "engine or the printer.",
  "inputSchema": {"type": "object", "properties": {
     "path": {"type": "string", "description": "output path; extension chooses the format"},
     "objects": {"type": "array", "items": {"type": "string"},
                 "description": "names to export; omit for the whole scene"}},
   "required": ["path"]}},

 {"name": "save_file",
  "description": "Save the .blend file. Pass a path the first time; afterwards it saves in "
                 "place. Worth doing before any destructive edit and after any result the "
                 "user approved — the scene lives in Blender's memory and an unsaved crash "
                 "loses the whole session's work.",
  "inputSchema": {"type": "object", "properties": {
     "path": {"type": "string"}}}},
]

PRESETS = {
    "game":   {"max_faces": 100_000, "require_uvs": True, "allow_unapplied_scale": False},
    "print":  {"max_faces": 5_000_000, "require_watertight": True, "require_uvs": False,
               "allow_unapplied_scale": True},
    "render": {"max_faces": 2_000_000, "require_uvs": False, "allow_unapplied_scale": True},
    "none":   {"max_faces": 10 ** 9, "require_uvs": False, "allow_unapplied_scale": True},
}


# --------------------------------------------------------------------------
# Tool handlers. Each returns text — the model reads prose far better than it
# reads a nested JSON blob, and the numbers that matter are all still in here.
# --------------------------------------------------------------------------

def t_status(_args):
    lines = []
    try:
        info = bridge.call("ping", timeout=5)
        lines.append("Blender %s connected on %s:%s"
                     % (info["blender"], bridge.DEFAULT_HOST, bridge.DEFAULT_PORT))
        lines.append("open file: %s" % (info.get("file") or "(unsaved)"))
    except bridge.BridgeError as exc:
        return str(exc)

    lines.append("")
    lines.append("mesh-generation backends:")
    for b in describe_all():
        mark = "ready" if b["available"] else "not configured"
        cost = "" if not b["cost_hint_usd"] else "  ~$%.2f/gen" % b["cost_hint_usd"]
        lines.append("  %-6s %-14s %-14s%s" % (b["name"], b["kind"], mark, cost))
        if not b["available"]:
            lines.append("         %s" % b["detail"])
    lines.append("")
    lines.append("runs directory: %s" % RUNS)
    return "\n".join(lines)


def t_backends(_args):
    lines = ["Mesh-generation backends, cheapest first:", ""]
    for b in describe_all():
        lines.append("%-6s  %-13s  %s" % (b["name"], b["kind"],
                     "READY" if b["available"] else "not configured"))
        if b["cost_hint_usd"]:
            lines.append("        roughly $%.2f per generation, billed to the user's own key"
                         % b["cost_hint_usd"])
        elif b["available"] or b["name"] == "local":
            lines.append("        no per-generation cost — your hardware")
        if not b["available"]:
            lines.append("        %s" % b["detail"])
        lines.append("")
    lines.append("BLENDPIPE_BACKEND pins one explicitly. Unset, the first ready backend in "
                 "this order wins, so a local generator takes over automatically once it "
                 "is configured.")
    lines.append("")
    lines.append("Neither is needed for procedural modelling — execute_python is free.")
    return "\n".join(lines)


def t_scene(args):
    s = bridge.call("scene_summary", {"limit": args.get("limit", 100)})
    lines = ["scene '%s' — %d objects, %s, %s units (scale %g)"
             % (s["scene"], s["object_count"], s["render_engine"],
                s["unit_system"].lower(), s["unit_scale"]),
             "by type: " + ", ".join("%s %d" % (k.lower(), v)
                                     for k, v in sorted(s["counts_by_type"].items()))]
    if s["collections"]:
        lines.append("collections: " + ", ".join(s["collections"]))
    lines.append("active: %s | selected: %s"
                 % (s["active"] or "none", ", ".join(s["selected"]) or "none"))
    lines.append("")
    if s["objects"]:
        lines.append("%-28s %-9s %9s %9s  %s" % ("name", "type", "verts", "faces", "dimensions"))
        for o in s["objects"]:
            lines.append("%-28s %-9s %9s %9s  %s%s"
                         % (o["name"][:28], o["type"].lower(),
                            o["verts"] if o["verts"] is not None else "-",
                            o["faces"] if o["faces"] is not None else "-",
                            "x".join("%.2f" % d for d in o["dimensions"]),
                            "  (hidden)" if o["hidden"] else ""))
    if s["truncated"]:
        lines.append("... truncated; raise limit to see the rest")
    return "\n".join(lines) if s["object_count"] else "The scene is empty."


def t_object(args):
    o = bridge.call("object_info", {"name": args["name"]})
    lines = ["%s (%s)" % (o["name"], o["type"].lower()),
             "  location   %s" % _vec(o["location"]),
             "  rotation   %s" % _vec(o["rotation_euler"]),
             "  scale      %s%s" % (_vec(o["scale"]),
                                    "   <- not applied" if any(abs(c - 1) > 1e-4 for c in o["scale"]) else ""),
             "  dimensions %s" % _vec(o["dimensions"]),
             "  bounds     min %s  max %s" % (_vec(o["world_bounds"]["min"]), _vec(o["world_bounds"]["max"]))]
    if o["parent"]:
        lines.append("  parent     %s" % o["parent"])
    if o["modifiers"]:
        lines.append("  modifiers  %s" % ", ".join(m.lower() for m in o["modifiers"]))
    lines.append("  materials  %s" % (", ".join(o["materials"]) or "none"))
    m = o.get("mesh")
    if m:
        lines += ["", "  mesh: %d verts, %d edges, %d faces" % (m["vertices"], m["edges"], m["faces"]),
                  "        %d quads, %d tris, %d ngons (%.0f%% quads)"
                  % (m["quads"], m["tris"], m["ngons"], m["quad_ratio"] * 100),
                  "        uv layers: %s" % (", ".join(m["uv_layers"]) or "NONE"),
                  "        shading: %s" % ("smooth" if m["shade_smooth"] else "flat")]
    return "\n".join(lines)


def _vec(v):
    return "(" + ", ".join("%8.3f" % c for c in v) + ")"


def t_execute(args):
    out = bridge.call("execute", {"code": args["code"]}, timeout=float(args.get("timeout", 600)))
    if not out.get("ok"):
        return ("The snippet raised:\n\n%s\n%s"
                % (out.get("traceback", "").rstrip(), _tail("stdout before the error", out.get("stdout"))))
    parts = []
    if out.get("stdout", "").strip():
        parts.append(out["stdout"].rstrip())
    if out.get("stderr", "").strip():
        parts.append("stderr:\n" + out["stderr"].rstrip())
    if out.get("result") is not None:
        parts.append("result: " + json.dumps(out["result"], indent=2)[:8000])
    return "\n\n".join(parts) if parts else "Ran with no output. Assign to `result` to return a value."


def _tail(label, text):
    text = (text or "").strip()
    return "" if not text else "\n%s:\n%s" % (label, text[-2000:])


def t_generate(args):
    prompt = args["prompt"]
    backend = resolve(args.get("backend"))
    out_dir = run_dir("gen")

    result = backend.generate(prompt, out_dir, options=args.get("options") or {})
    info = result.as_dict()
    lines = ["Generated with %s: %s" % (backend.name, info["path"]),
             "  %.1f MB" % (info["bytes"] / 1e6)]
    if backend.cost_hint:
        lines.append("  cost: roughly $%.2f charged to your %s key" % (backend.cost_hint, backend.name))

    if args.get("import", True):
        imported = bridge.call("import_mesh", {"path": result.path, "name": args.get("name")})
        lines.append("  imported as: %s" % ", ".join(imported["imported"]))
        lines.append("")
        lines.append("Generated meshes arrive at arbitrary scale and orientation and are "
                     "usually triangle soup. Run verify_geometry and render_views before "
                     "calling this finished.")
    return "\n".join(lines)


def t_render(args):
    out = bridge.call("render", {
        "angles": args.get("angles", [0, 90, 180, 270]),
        "elevation": args.get("elevation", 20),
        "resolution": args.get("resolution", 640),
        "focus": args.get("focus"),
        "engine": args.get("engine"),
        "samples": args.get("samples", 32),
        "output_dir": run_dir("render"),
    }, timeout=float(args.get("timeout", 900)))
    # Say what lit it. The renderer uses the scene's own lights when it has any
    # and only adds a studio rig to a scene with none — but that was invisible
    # from here, and an agent that lit its scene badly blamed this tool for the
    # result rather than its own two lamps.
    lit = out.get("lit_by") or "the scene"
    lighting = ("lit by the scene's own lights — if the result is flat or "
                "colourless, that is your lighting, not the renderer"
                if lit == "the scene" else
                "lit by a temporary studio rig, because the scene has no lights")
    return ("Rendered %d views on %s, %s:\n%s\n\nNow READ these files. A turnaround you did "
            "not look at tells you nothing."
            % (len(out["images"]), out["engine"], lighting,
               "\n".join("  " + p for p in out["images"])))


def _uv_phrase(m):
    """Say whether the UVs are usable, not merely present.

    "uvs: UVMap" was the old wording and it is the answer to a question nobody
    asked. Thirty joined boxes have a UV layer and cannot be textured.
    """
    if not m.get("uv_layers"):
        return "NONE"
    names = ", ".join(m["uv_layers"])
    uv = m.get("uv")
    if not uv:
        return names
    if uv["overlaps"]:
        return "%s OVERLAPPING (islands cover %.1fx the square)" % (names, uv["area_sum"])
    bits = ["%.0f%% packed" % (uv["area_sum"] * 100)]
    ratio = uv["texel_density_ratio"]
    if ratio:
        bits.append("density %.1fx" % ratio)
    if uv["faces_outside_0_1"]:
        bits.append("%d faces outside 0-1" % uv["faces_outside_0_1"])
    return "%s (%s)" % (names, ", ".join(bits))


def t_verify(args):
    report = bridge.call("execute", {"code": gates.probe_code(args.get("objects"))}, timeout=300)
    if not report.get("ok"):
        return "Could not measure the geometry:\n" + report.get("traceback", "")
    measurements = report.get("result") or {}
    if not measurements:
        return "No mesh objects to check."

    kwargs = dict(PRESETS.get(args.get("preset", "game"), PRESETS["game"]))
    for key in ("max_faces", "min_quad_ratio", "require_watertight", "require_uvs",
                "max_dimension", "min_dimension"):
        if args.get(key) is not None:
            kwargs[key] = args[key]

    findings = gates.evaluate(measurements, gates.Budget(**kwargs))
    v = gates.verdict(findings)

    lines = []
    for name, m in measurements.items():
        lines.append("%s: %d faces (%d quads / %d tris / %d ngons, %.0f%% quads), "
                     "%s, %s, size %s"
                     % (name, m["faces"], m["quads"], m["tris"], m["ngons"], m["quad_ratio"] * 100,
                        "watertight" if m["watertight"] else "%d boundary edges" % m["boundary_edges"],
                        "uvs: " + _uv_phrase(m),
                        "x".join("%.2f" % d for d in m["dimensions"])))
    lines.append("")
    lines.append("VERDICT: %s — %d blocking, %d warnings (preset: %s)"
                 % ("PASS" if v["passed"] else "FAIL", v["blocking"], v["warnings"],
                    args.get("preset", "game")))
    for f in v["findings"]:
        lines.append("")
        lines.append("  [%s] %s on %s" % (f["severity"], f["check"], f["object"]))
        lines.append("    %s" % f["detail"])
        lines.append("    fix: %s" % f["fix"])
    if not v["passed"]:
        lines.append("")
        lines.append("Do not export or call this finished until the blocking findings are cleared.")
    return "\n".join(lines)


def t_export(args):
    out = bridge.call("export_mesh", {"path": args["path"], "objects": args.get("objects")})
    return "Exported %s (%.2f MB), objects: %s" % (
        out["path"], out["bytes"] / 1e6,
        ", ".join(out["objects"]) if isinstance(out["objects"], list) else out["objects"])


def t_save(args):
    out = bridge.call("save", {"path": args.get("path")})
    return "Saved %s (%.2f MB)" % (out["path"], out["bytes"] / 1e6)


HANDLERS = {
    "blender_status": t_status,
    "list_backends": t_backends,
    "scene_summary": t_scene,
    "object_info": t_object,
    "execute_python": t_execute,
    "generate_mesh": t_generate,
    "render_views": t_render,
    "verify_geometry": t_verify,
    "export_mesh": t_export,
    "save_file": t_save,
}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        try:
            if method == "initialize":
                res = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                       "serverInfo": {"name": "blender", "version": VERSION}}
            elif method == "tools/list":
                res = {"tools": TOOLS}
            elif method == "tools/call":
                p = msg.get("params", {})
                fn = HANDLERS.get(p.get("name"))
                if fn is None:
                    text = "unknown tool %s" % p.get("name")
                else:
                    # Bridge and backend failures are the normal case, not a
                    # crash: Blender is often simply not open yet. They come
                    # back as readable tool output so the model can act on them.
                    try:
                        text = fn(p.get("arguments") or {})
                    except (bridge.BridgeError, BackendError) as exc:
                        text = str(exc)
                res = {"content": [{"type": "text", "text": text}]}
            elif method in ("notifications/initialized", "initialized"):
                continue
            else:
                res = None
            if mid is not None and res is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}), flush=True)
        except Exception as exc:
            if mid is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": mid,
                                  "error": {"code": -32000, "message": str(exc)}}), flush=True)


if __name__ == "__main__":
    main()
