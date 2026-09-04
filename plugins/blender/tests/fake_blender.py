"""A stand-in for the Blender addon, so the bridge can be tested without Blender.

It speaks the same newline-delimited JSON protocol as blendpipe/addon.py and
returns canned measurements. This exists because the interesting failures in this
plugin are in the wiring — framing, protocol, the gate evaluator — and none of
them need a 400 MB application running to be caught.
"""

import json
import socket
import threading


class FakeBlender:
    def __init__(self, scenario=None):
        self.scenario = scenario or {}
        self.calls = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self._stop.set()
        self.sock.close()

    def _loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        buf = b""
        try:
            while not self._stop.is_set():
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        conn.sendall(json.dumps(self._reply(json.loads(line))).encode() + b"\n")
        except OSError:
            pass
        finally:
            conn.close()

    def _reply(self, request):
        command = request.get("command")
        self.calls.append((command, request.get("params")))
        if command in self.scenario:
            value = self.scenario[command]
            return value(request) if callable(value) else {"ok": True, "data": value}
        default = getattr(self, "_d_" + command, None)
        if default is None:
            return {"ok": False, "error": "unknown command %r" % command}
        return {"ok": True, "data": default(request.get("params") or {})}

    # -- defaults ---------------------------------------------------------
    def _d_ping(self, _p):
        return {"pong": True, "blender": "4.2.0", "protocol": 1, "file": "/tmp/scene.blend"}

    def _d_scene_summary(self, _p):
        return {"scene": "Scene", "frame": 1, "unit_system": "METRIC", "unit_scale": 1.0,
                "render_engine": "BLENDER_EEVEE_NEXT", "object_count": 2, "truncated": False,
                "counts_by_type": {"MESH": 1, "LIGHT": 1},
                "objects": [
                    {"name": "Goblin", "type": "MESH", "verts": 4210, "faces": 4180,
                     "dimensions": [0.8, 0.6, 1.7], "hidden": False},
                    {"name": "Key", "type": "LIGHT", "verts": None, "faces": None,
                     "dimensions": [0, 0, 0], "hidden": False}],
                "collections": ["Collection"], "selected": ["Goblin"], "active": "Goblin"}

    def _d_object_info(self, params):
        return {"name": params.get("name", "Goblin"), "type": "MESH",
                "location": [0, 0, 0], "rotation_euler": [0, 0, 0], "scale": [1.7, 1.7, 1.7],
                "dimensions": [0.8, 0.6, 1.7],
                "world_bounds": {"min": [-0.4, -0.3, 0.0], "max": [0.4, 0.3, 1.7]},
                "parent": None, "modifiers": ["SUBSURF"], "materials": ["Skin"],
                "mesh": {"vertices": 4210, "edges": 8300, "faces": 4180, "tris": 4180,
                         "quads": 0, "ngons": 0, "quad_ratio": 0.0, "uv_layers": [],
                         "shade_smooth": True}}

    def _d_execute(self, params):
        code = params.get("code", "")
        if "TARGETS" in code:      # the geometry probe
            return {"ok": True, "stdout": "", "stderr": "", "result": self.scenario.get(
                "probe", {"Goblin": _MEASUREMENT})}
        return {"ok": True, "stdout": "ran\n", "stderr": "", "result": None}

    def _d_render(self, params):
        angles = params.get("angles") or [0]
        return {"images": ["/tmp/r/view_%03d.png" % int(a) for a in angles],
                "output_dir": "/tmp/r", "engine": "BLENDER_EEVEE_NEXT"}

    def _d_import_mesh(self, params):
        return {"imported": [params.get("name") or "Imported"], "path": params.get("path")}

    def _d_export_mesh(self, params):
        return {"path": params["path"], "bytes": 2_400_000, "objects": params.get("objects") or "all"}

    def _d_save(self, params):
        return {"path": params.get("path") or "/tmp/scene.blend", "bytes": 1_200_000}


#: A generated mesh straight off a paid backend: triangle soup, no UVs, wrong scale.
_MEASUREMENT = {
    "verts": 42000, "edges": 126000, "faces": 84000, "tris": 84000, "quads": 0, "ngons": 0,
    "quad_ratio": 0.0, "non_manifold_edges": 0, "boundary_edges": 18, "wire_edges": 0,
    "loose_verts": 0, "zero_area_faces": 0, "duplicate_verts": 214, "watertight": False,
    "signed_volume": 0.4, "inverted_normals": False, "uv_layers": [], "material_slots": 1,
    "dimensions": [0.8, 0.6, 1.7], "scale": [1.7, 1.7, 1.7], "unapplied_scale": True,
    "location": [0.0, 0.0, 0.0], "modifiers": [],
}
