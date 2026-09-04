"""BlendPipe — the Blender half of the bridge.

Install this file as a Blender addon (Edit > Preferences > Add-ons > Install),
enable "Interface: BlendPipe Bridge", then press Start in the BlendPipe panel of
the 3D viewport sidebar (N key). The MCP server on the other end connects to the
port shown there.

Why this file is shaped the way it is
-------------------------------------
`bpy` is not thread-safe and touching it from a socket thread corrupts Blender's
state in ways that surface much later as a crash with no useful traceback. So the
socket work and the Blender work are strictly separated:

    accept thread ──> per-connection thread ──> job queue
                                                    │
                          bpy.app.timers.register ──┘ (main thread, drains queue)

The connection thread parks on a threading.Event until the main thread has filled
in the result. Every single `bpy` access in this file happens inside `_pump`,
which the timer guarantees is on the main thread.

The wire protocol is newline-delimited JSON. A JSON-encoded string can never
contain a literal newline, so framing on "\n" is safe for arbitrary Python source
in the payload.
"""

bl_info = {
    "name": "BlendPipe Bridge",
    "author": "LiLo Labs",
    "version": (0, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > BlendPipe",
    "description": "Expose this Blender session to Claude Code over a local socket",
    "category": "Interface",
}

import base64
import io
import json
import os
import queue
import socket
import tempfile
import threading
import traceback
import contextlib

import bpy
import mathutils

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876
PROTOCOL_VERSION = 1

# Jobs waiting for the main thread. Each entry is a _Job.
_jobs: "queue.Queue" = queue.Queue()
_server = None


class _Job:
    """One request, parked until the main thread has answered it."""

    __slots__ = ("request", "done", "result")

    def __init__(self, request):
        self.request = request
        self.done = threading.Event()
        self.result = None


# --------------------------------------------------------------------------
# Command handlers. Every function here runs ON THE MAIN THREAD.
# --------------------------------------------------------------------------

def _h_ping(_params):
    return {
        "pong": True,
        "blender": bpy.app.version_string,
        "protocol": PROTOCOL_VERSION,
        "file": bpy.data.filepath or None,
    }


def _h_execute(params):
    """Run Python inside Blender and report what it printed.

    The namespace is pre-populated with bpy/mathutils because every useful
    snippet needs them and re-importing in each call is noise. Assigning to
    `result` in the snippet returns that value as JSON; that is the supported
    way to get structured data back rather than parsing stdout.
    """
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("execute needs a non-empty 'code' string")

    ns = {"bpy": bpy, "mathutils": mathutils, "result": None}
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(compile(code, "<blendpipe>", "exec"), ns)
    except Exception:
        return {
            "ok": False,
            "stdout": out.getvalue(),
            "stderr": err.getvalue(),
            "traceback": traceback.format_exc(limit=6),
        }

    return {
        "ok": True,
        "stdout": out.getvalue(),
        "stderr": err.getvalue(),
        "result": _jsonable(ns.get("result")),
    }


def _jsonable(value, _depth=0):
    """Best-effort conversion of a Blender/Python value into JSON.

    Snippets return Vectors, Matrices and bpy structs constantly. Rather than
    failing the whole call on an unserializable leaf, unknown types degrade to
    their repr so the caller still sees something useful.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if _depth > 6:
        return repr(value)
    if isinstance(value, (mathutils.Vector, mathutils.Euler, mathutils.Quaternion)):
        return [round(float(c), 6) for c in value]
    if isinstance(value, mathutils.Matrix):
        return [[round(float(c), 6) for c in row] for row in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v, _depth + 1) for v in value]
    if isinstance(value, bpy.types.Object):
        return _object_summary(value)
    return repr(value)


def _object_summary(obj):
    bbox = [tuple(obj.matrix_world @ mathutils.Vector(c)) for c in obj.bound_box]
    xs, ys, zs = zip(*bbox)
    summary = {
        "name": obj.name,
        "type": obj.type,
        "location": [round(float(c), 6) for c in obj.location],
        "rotation_euler": [round(float(c), 6) for c in obj.rotation_euler],
        "scale": [round(float(c), 6) for c in obj.scale],
        "dimensions": [round(float(c), 6) for c in obj.dimensions],
        "world_bounds": {
            "min": [round(min(xs), 6), round(min(ys), 6), round(min(zs), 6)],
            "max": [round(max(xs), 6), round(max(ys), 6), round(max(zs), 6)],
        },
        "parent": obj.parent.name if obj.parent else None,
        "modifiers": [m.type for m in obj.modifiers],
        "materials": [s.material.name for s in obj.material_slots if s.material],
    }
    if obj.type == "MESH":
        mesh = obj.data
        ngons = sum(1 for p in mesh.polygons if len(p.vertices) > 4)
        tris = sum(1 for p in mesh.polygons if len(p.vertices) == 3)
        quads = sum(1 for p in mesh.polygons if len(p.vertices) == 4)
        summary["mesh"] = {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "faces": len(mesh.polygons),
            "tris": tris,
            "quads": quads,
            "ngons": ngons,
            "quad_ratio": round(quads / len(mesh.polygons), 4) if mesh.polygons else 0.0,
            "uv_layers": [l.name for l in mesh.uv_layers],
            "shade_smooth": bool(mesh.polygons and mesh.polygons[0].use_smooth),
        }
    return summary


def _h_scene_summary(params):
    """The scene as a readable inventory rather than a dump.

    Full per-object detail for a large scene is tens of thousands of tokens and
    is almost never what the caller needs; they need to know what exists and
    which handful of objects to look at closely with object_info.
    """
    limit = int(params.get("limit", 100))
    scene = bpy.context.scene
    objects = list(scene.objects)
    listed = objects[:limit]
    return {
        "scene": scene.name,
        "frame": scene.frame_current,
        "unit_system": scene.unit_settings.system,
        "unit_scale": round(scene.unit_settings.scale_length, 6),
        "render_engine": scene.render.engine,
        "object_count": len(objects),
        "truncated": len(objects) > limit,
        "counts_by_type": _tally(o.type for o in objects),
        "objects": [
            {
                "name": o.name,
                "type": o.type,
                "verts": len(o.data.vertices) if o.type == "MESH" else None,
                "faces": len(o.data.polygons) if o.type == "MESH" else None,
                "dimensions": [round(float(c), 4) for c in o.dimensions],
                "hidden": not o.visible_get(),
            }
            for o in listed
        ],
        "collections": [c.name for c in bpy.data.collections],
        "selected": [o.name for o in bpy.context.selected_objects],
        "active": bpy.context.view_layer.objects.active.name
        if bpy.context.view_layer.objects.active
        else None,
    }


def _tally(items):
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def _h_object_info(params):
    name = params.get("name")
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError("no object named %r; call scene_summary to see what exists" % name)
    return _object_summary(obj)


def _h_import_mesh(params):
    """Bring a generated or downloaded mesh into the scene.

    The importers are chosen by extension rather than sniffing content because
    Blender's own operators are extension-bound anyway, and a wrong guess here
    produces a much clearer error than a half-imported scene.
    """
    path = os.path.expanduser(params.get("path", ""))
    if not os.path.isfile(path):
        raise ValueError("no file at %s" % path)

    before = set(bpy.data.objects.keys())
    ext = os.path.splitext(path)[1].lower()
    if ext == ".glb" or ext == ".gltf":
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        # Blender 4.x replaced the Python OBJ importer with a C++ one.
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=path)
        else:
            bpy.ops.import_scene.obj(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".stl":
        if hasattr(bpy.ops.wm, "stl_import"):
            bpy.ops.wm.stl_import(filepath=path)
        else:
            bpy.ops.import_mesh.stl(filepath=path)
    elif ext == ".ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.wm.ply_import(filepath=path)
        else:
            bpy.ops.import_mesh.ply(filepath=path)
    else:
        raise ValueError("unsupported extension %r (glb, gltf, obj, fbx, stl, ply)" % ext)

    created = [n for n in bpy.data.objects.keys() if n not in before]
    if params.get("name") and len(created) == 1:
        bpy.data.objects[created[0]].name = params["name"]
        created = [params["name"]]
    return {"imported": created, "path": path}


def _h_export_mesh(params):
    path = os.path.expanduser(params.get("path", ""))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    names = params.get("objects") or []
    ext = os.path.splitext(path)[1].lower()

    if names:
        bpy.ops.object.select_all(action="DESELECT")
        for name in names:
            obj = bpy.data.objects.get(name)
            if obj is None:
                raise ValueError("no object named %r" % name)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

    only_selected = bool(names)
    if ext in (".glb", ".gltf"):
        bpy.ops.export_scene.gltf(
            filepath=path,
            export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE",
            use_selection=only_selected,
        )
    elif ext == ".obj":
        if hasattr(bpy.ops.wm, "obj_export"):
            bpy.ops.wm.obj_export(filepath=path, export_selected_objects=only_selected)
        else:
            bpy.ops.export_scene.obj(filepath=path, use_selection=only_selected)
    elif ext == ".fbx":
        bpy.ops.export_scene.fbx(filepath=path, use_selection=only_selected)
    elif ext == ".stl":
        if hasattr(bpy.ops.wm, "stl_export"):
            bpy.ops.wm.stl_export(filepath=path, export_selected_objects=only_selected)
        else:
            bpy.ops.export_mesh.stl(filepath=path, use_selection=only_selected)
    else:
        raise ValueError("unsupported export extension %r" % ext)
    return {"path": path, "bytes": os.path.getsize(path), "objects": names or "all"}


def _h_render(params):
    """Render the scene, or a turnaround, to PNG on disk.

    Renders come back as file paths rather than inline base64 by default: a
    1024px PNG is roughly a megabyte of base64 and four of those in one tool
    result crowds out the conversation. The caller reads the paths with the Read
    tool, which is what actually puts pixels in front of the model.
    """
    out_dir = os.path.expanduser(params.get("output_dir") or tempfile.mkdtemp(prefix="blendpipe-"))
    os.makedirs(out_dir, exist_ok=True)
    scene = bpy.context.scene
    resolution = int(params.get("resolution", 640))
    samples = int(params.get("samples", 32))

    prev = {
        "x": scene.render.resolution_x,
        "y": scene.render.resolution_y,
        "pct": scene.render.resolution_percentage,
        "path": scene.render.filepath,
        "engine": scene.render.engine,
        "film": scene.render.film_transparent,
    }
    scene.render.resolution_x = scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    # EEVEE is the right default for a critique loop: a turnaround needs to be
    # readable in seconds, not physically correct in minutes. Callers who want
    # Cycles set engine explicitly.
    engine = params.get("engine")
    if engine:
        scene.render.engine = engine
    elif scene.render.engine == "CYCLES" and not params.get("keep_engine"):
        scene.render.engine = "BLENDER_EEVEE_NEXT" if _has_engine("BLENDER_EEVEE_NEXT") else "BLENDER_EEVEE"
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = samples

    camera, created_camera = _ensure_camera(params.get("focus"))
    angles = params.get("angles") or [0]
    written = []
    try:
        radius, center = _framing(params.get("focus"))
        for angle in angles:
            _place_camera(camera, center, radius, float(angle), float(params.get("elevation", 20.0)))
            path = os.path.join(out_dir, "view_%03d.png" % int(angle))
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            written.append(path)
    finally:
        scene.render.resolution_x = prev["x"]
        scene.render.resolution_y = prev["y"]
        scene.render.resolution_percentage = prev["pct"]
        scene.render.filepath = prev["path"]
        scene.render.engine = prev["engine"]
        scene.render.film_transparent = prev["film"]
        if created_camera:
            bpy.data.objects.remove(camera, do_unlink=True)

    return {"images": written, "output_dir": out_dir, "engine": scene.render.engine}


def _has_engine(identifier):
    try:
        return identifier in {
            item.identifier
            for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
        }
    except Exception:
        return False


def _ensure_camera(focus):
    """Use the scene camera when there is one, otherwise borrow a temporary.

    A temporary camera is removed afterwards so a critique render never leaves
    debris in the user's scene — a scene that slowly fills with Camera.001 is a
    real cost of automated rendering.
    """
    if bpy.context.scene.camera is not None:
        return bpy.context.scene.camera, False
    data = bpy.data.cameras.new("BlendPipeCam")
    camera = bpy.data.objects.new("BlendPipeCam", data)
    bpy.context.scene.collection.objects.link(camera)
    bpy.context.scene.camera = camera
    return camera, True


def _framing(focus):
    """Distance and center that fit the subject in frame."""
    objects = [bpy.data.objects[n] for n in focus if n in bpy.data.objects] if focus else [
        o for o in bpy.context.scene.objects if o.type == "MESH" and o.visible_get()
    ]
    if not objects:
        return 6.0, mathutils.Vector((0.0, 0.0, 0.0))

    corners = []
    for obj in objects:
        corners.extend(obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box)
    xs, ys, zs = zip(*[(c.x, c.y, c.z) for c in corners])
    center = mathutils.Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
    extent = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    return max(extent * 2.2, 0.5), center


def _place_camera(camera, center, radius, angle_deg, elevation_deg):
    import math

    a = math.radians(angle_deg)
    e = math.radians(elevation_deg)
    camera.location = center + mathutils.Vector(
        (radius * math.cos(a) * math.cos(e), radius * math.sin(a) * math.cos(e), radius * math.sin(e))
    )
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _h_save(params):
    path = os.path.expanduser(params["path"]) if params.get("path") else bpy.data.filepath
    if not path:
        raise ValueError("this session has never been saved; pass an explicit path")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return {"path": path, "bytes": os.path.getsize(path)}


HANDLERS = {
    "ping": _h_ping,
    "execute": _h_execute,
    "scene_summary": _h_scene_summary,
    "object_info": _h_object_info,
    "import_mesh": _h_import_mesh,
    "export_mesh": _h_export_mesh,
    "render": _h_render,
    "save": _h_save,
}


# --------------------------------------------------------------------------
# Main-thread pump
# --------------------------------------------------------------------------

def _pump():
    """Drain the job queue. Registered as a timer, so this is the main thread."""
    while True:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            break
        command = job.request.get("command")
        params = job.request.get("params") or {}
        handler = HANDLERS.get(command)
        try:
            if handler is None:
                raise ValueError(
                    "unknown command %r; known: %s" % (command, ", ".join(sorted(HANDLERS)))
                )
            job.result = {"ok": True, "data": handler(params)}
        except Exception as exc:
            job.result = {
                "ok": False,
                "error": "%s: %s" % (type(exc).__name__, exc),
                "traceback": traceback.format_exc(limit=6),
            }
        finally:
            job.done.set()
    return 0.05  # seconds until the next pump


# --------------------------------------------------------------------------
# Socket server (background threads — no bpy access below this line)
# --------------------------------------------------------------------------

class BridgeServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.host, self.port = host, port
        self._sock = None
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(5)
        self._sock.settimeout(0.5)
        self._stop.clear()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        if not bpy.app.timers.is_registered(_pump):
            bpy.app.timers.register(_pump, persistent=True)
        print("[BlendPipe] listening on %s:%d" % (self.host, self.port))

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if bpy.app.timers.is_registered(_pump):
            bpy.app.timers.unregister(_pump)
        print("[BlendPipe] stopped")

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        """One connection, newline-delimited JSON in both directions."""
        buf = b""
        conn.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    conn.sendall(self._handle(line) + b"\n")
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                conn.close()

    def _handle(self, line):
        try:
            request = json.loads(line.decode("utf-8"))
        except Exception as exc:
            return json.dumps({"ok": False, "error": "bad JSON: %s" % exc}).encode("utf-8")

        job = _Job(request)
        _jobs.put(job)
        # Long enough for a Cycles render, short enough that a wedged main thread
        # reports rather than hanging the caller forever.
        if not job.done.wait(timeout=float(request.get("timeout", 600))):
            return json.dumps(
                {"ok": False, "error": "timed out waiting for Blender's main thread"}
            ).encode("utf-8")
        return json.dumps(job.result).encode("utf-8")


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

class BLENDPIPE_OT_start(bpy.types.Operator):
    bl_idname = "blendpipe.start"
    bl_label = "Start BlendPipe Bridge"

    def execute(self, context):
        global _server
        if _server is not None:
            self.report({"INFO"}, "already running")
            return {"CANCELLED"}
        _server = BridgeServer(port=context.scene.blendpipe_port)
        try:
            _server.start()
        except OSError as exc:
            _server = None
            self.report({"ERROR"}, "could not bind port: %s" % exc)
            return {"CANCELLED"}
        context.scene.blendpipe_running = True
        return {"FINISHED"}


class BLENDPIPE_OT_stop(bpy.types.Operator):
    bl_idname = "blendpipe.stop"
    bl_label = "Stop BlendPipe Bridge"

    def execute(self, context):
        global _server
        if _server is not None:
            _server.stop()
            _server = None
        context.scene.blendpipe_running = False
        return {"FINISHED"}


class BLENDPIPE_PT_panel(bpy.types.Panel):
    bl_label = "BlendPipe"
    bl_idname = "BLENDPIPE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlendPipe"

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "blendpipe_port")
        if context.scene.blendpipe_running:
            layout.operator("blendpipe.stop", icon="PAUSE")
            layout.label(text="Listening on %d" % context.scene.blendpipe_port, icon="CHECKMARK")
        else:
            layout.operator("blendpipe.start", icon="PLAY")
            layout.label(text="Not connected", icon="UNLINKED")


_CLASSES = (BLENDPIPE_OT_start, BLENDPIPE_OT_stop, BLENDPIPE_PT_panel)


def register():
    bpy.types.Scene.blendpipe_port = bpy.props.IntProperty(
        name="Port", default=DEFAULT_PORT, min=1024, max=65535
    )
    bpy.types.Scene.blendpipe_running = bpy.props.BoolProperty(default=False)
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    global _server
    if _server is not None:
        _server.stop()
        _server = None
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.blendpipe_port
    del bpy.types.Scene.blendpipe_running


if __name__ == "__main__":
    register()
