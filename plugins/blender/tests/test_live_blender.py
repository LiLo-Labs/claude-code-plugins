"""Integration checks against a real Blender. Skips cleanly when there is none.

    python3 plugins/blender/tests/test_live_blender.py
    BLENDER_BIN=/path/to/blender python3 .../test_live_blender.py

Why this exists as well as test_blendpipe.py: that suite talks to a fake which
answers `execute` with a canned report, so it proves the wire protocol and the
gate arithmetic and cannot prove anything about `bpy`. Three real bugs shipped
in the gap -- a probe that could not parse, a render that named the wrong
engine, and renders of unlit scenes -- and every one of them is invisible until
Blender actually runs the code. Each check below is anchored to one of them.
"""

import glob
import json
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from blendpipe import bridge, gates  # noqa: E402

PASSED, FAILED = [], []
PORT = int(os.environ.get("BLENDPIPE_TEST_PORT", "9878"))

CANDIDATES = [
    os.environ.get("BLENDER_BIN"),
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "/usr/bin/blender",
    "/usr/local/bin/blender",
    "/snap/bin/blender",
]


def check(label, condition, detail=""):
    (PASSED if condition else FAILED).append(label)
    print("  %-4s %s%s" % ("ok" if condition else "FAIL", label,
                           "" if condition or not detail else "  <- " + str(detail)))


def find_blender():
    for path in CANDIDATES:
        if path and os.path.exists(path):
            return path
    for path in glob.glob("/Applications/Blender*.app/Contents/MacOS/Blender"):
        return path
    return None


def ex(code, timeout=300):
    """Run a snippet in Blender; fail loudly rather than returning a half-result."""
    reply = bridge.call("execute", {"code": code}, timeout=timeout, port=PORT)
    if not reply.get("ok"):
        raise AssertionError(reply.get("traceback") or reply.get("stderr") or "execute failed")
    return reply.get("result")


# Measuring the image inside Blender keeps this suite dependency-free -- no
# numpy, no Pillow -- and bpy.data.images already decodes PNG.
MEASURE = '''
import bpy
img = bpy.data.images.load(%r)
w, h = img.size
px = list(img.pixels)
bg = (px[0], px[1], px[2])
minx, miny, maxx, maxy = w, h, -1, -1
lo, hi = 1.0, 0.0
for y in range(h):
    row = y * w
    for x in range(w):
        i = (row + x) * 4
        r, g, b = px[i], px[i + 1], px[i + 2]
        if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > 0.02:
            if x < minx: minx = x
            if x > maxx: maxx = x
            if y < miny: miny = y
            if y > maxy: maxy = y
            v = (r + g + b) / 3.0
            if v < lo: lo = v
            if v > hi: hi = v
bpy.data.images.remove(img)
result = None if maxx < 0 else {
    "fill_w": (maxx - minx) / w, "fill_h": (maxy - miny) / h,
    "off": max(abs((minx + maxx) / 2 - w / 2), abs((miny + maxy) / 2 - h / 2)) / w,
    "clipped": minx <= 0 or miny <= 0 or maxx >= w - 1 or maxy >= h - 1,
    "shading_range": hi - lo,
}
'''


def measure(path):
    return ex(MEASURE % path)


def clear():
    ex("""
import bpy
for o in list(bpy.context.scene.objects):
    bpy.data.objects.remove(o, do_unlink=True)
""")


def test_bridge_is_live():
    print("\nlive bridge")
    info = bridge.call("ping", port=PORT)
    check("the addon registered and answers", bool(info.get("pong")))
    check("and reports a Blender version", bool(info.get("blender")), info)
    check("on the protocol the client speaks", info.get("protocol") == 1)


def test_probe_runs_in_blender(out):
    """Bug: probe_code() emitted `TARGETS = null` and died with NameError.

    The fake never compiled the probe, so 56 checks passed over a generator
    whose default output was not Python.
    """
    print("\nprobe against real geometry")
    clear()
    ex("import bpy; bpy.ops.mesh.primitive_cube_add(size=2)")
    reply = bridge.call("execute", {"code": gates.probe_code()}, timeout=300, port=PORT)
    check("the default probe executes inside Blender", reply.get("ok"),
          reply.get("traceback"))
    if not reply.get("ok"):
        return
    report = reply["result"]
    check("and measures the mesh", "Cube" in report, sorted(report))
    cube = report.get("Cube", {})
    check("a clean cube is all quads", cube.get("quad_ratio") == 1.0, cube.get("quad_ratio"))
    check("and watertight", cube.get("watertight") is True)
    check("and passes the gate", gates.verdict(gates.evaluate(report))["passed"])

    # An explicit target list is the other branch through the same generator.
    named = bridge.call("execute", {"code": gates.probe_code(["Cube"])}, timeout=300, port=PORT)
    check("an explicit target list also executes", named.get("ok"), named.get("traceback"))


def test_gate_catches_broken_geometry():
    """The gate's whole job. Asserted here on geometry Blender actually built."""
    print("\nthe gate on broken geometry")
    clear()
    ex("""
import bpy, bmesh
bpy.ops.mesh.primitive_cube_add(size=2)
o = bpy.context.active_object; o.name = "Broken"
me = o.data
bm = bmesh.new(); bm.from_mesh(me)
bm.faces.ensure_lookup_table(); bm.verts.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.faces[0]], context='FACES_ONLY')
bm.edges.ensure_lookup_table()
e = bm.edges[0]
v = bm.verts.new((3.0, 0.0, 0.0))
bm.faces.new((e.verts[0], e.verts[1], v))
bm.verts.new((5.0, 5.0, 5.0))
bm.to_mesh(me); bm.free()
o.scale = (1.7, 1.7, 1.7)
""")
    report = ex(gates.probe_code())
    m = report["Broken"]
    check("non-manifold edges are counted", m["non_manifold_edges"] > 0, m["non_manifold_edges"])
    check("loose vertices are counted", m["loose_verts"] > 0, m["loose_verts"])
    check("an unapplied scale is seen", m["unapplied_scale"] is True, m["scale"])
    check("and it is not watertight", m["watertight"] is False)
    v = gates.verdict(gates.evaluate(report))
    check("the gate blocks it", not v["passed"])
    check("naming non_manifold as blocking",
          any(f["check"] == "non_manifold" and f["severity"] == "blocking" for f in v["findings"]))

    # Inverted normals only mean anything on a closed mesh, so check that path too.
    clear()
    ex("""
import bpy, bmesh
bpy.ops.mesh.primitive_uv_sphere_add(radius=1)
bpy.context.active_object.name = "Inside"
me = bpy.context.active_object.data
bm = bmesh.new(); bm.from_mesh(me)
bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
bm.to_mesh(me); bm.free()
""")
    inv = gates.verdict(gates.evaluate(ex(gates.probe_code())))
    check("inside-out normals on a closed mesh are blocking",
          any(f["check"] == "inverted_normals" for f in inv["findings"]))


def test_uv_quality_on_real_geometry():
    """Build the real failure case rather than a synthetic report.

    Joining boxes is the ordinary way a procedural asset is assembled, and every
    box brings its own default cube unwrap. The result has a UV layer, reports
    `uvs: UVMap`, and cannot be textured -- which is exactly what the old check
    called a pass.
    """
    print("\nuv quality on real geometry")
    clear()
    ex("""
import bpy
parts = []
for i in range(12):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(i * 1.5, 0, 0))
    parts.append(bpy.context.active_object)
bpy.ops.object.select_all(action='DESELECT')
for p in parts:
    p.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
bpy.ops.object.join()
bpy.context.active_object.name = "Joined"
""")
    uv = ex(gates.probe_code(["Joined"]))["Joined"]["uv"]
    check("joined boxes stack their unwraps", uv["overlaps"] is True, uv["area_sum"])
    check("and the area proves it (>1.0 cannot fit)", uv["area_sum"] > 1.0, uv["area_sum"])
    check("many faces share one UV spot", uv["stacked_faces"] > 3, uv["stacked_faces"])
    findings = {f["check"]: f["severity"]
                for f in gates.verdict(gates.evaluate(ex(gates.probe_code(["Joined"]))))["findings"]}
    check("the gate reports it", findings.get("uv_overlap") == "warning", findings)
    check("as a warning, not a block", "blocking" not in findings.values(), findings)

    # Unwrapping it should clear the finding -- the measurement has to move when
    # the thing it measures is fixed, or it is decoration.
    ex("""
import bpy
o = bpy.data.objects["Joined"]
bpy.ops.object.select_all(action='DESELECT')
o.select_set(True); bpy.context.view_layer.objects.active = o
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
bpy.ops.object.mode_set(mode='OBJECT')
""")
    after = ex(gates.probe_code(["Joined"]))["Joined"]["uv"]
    check("a real unwrap clears the overlap", after["overlaps"] is False, after["area_sum"])
    check("and packs into the square", after["area_sum"] <= 1.0, after["area_sum"])
    check("and evens the texel density",
          after["texel_density_ratio"] is not None and after["texel_density_ratio"] < 4.0,
          after["texel_density_ratio"])


def test_render_lights_an_unlit_scene(out):
    """Bug: a procedural session deletes the default light, so every render
    after it was a silhouette on near-black. The tool result says to go and look
    at the image; there was nothing in it to look at."""
    print("\nrender lighting")
    clear()
    ex("import bpy; bpy.ops.mesh.primitive_monkey_add(size=2); bpy.ops.object.shade_smooth()")
    lit = bridge.call("render", {"output_dir": os.path.join(out, "lit"),
                                 "angles": [0], "resolution": 200}, port=PORT)
    check("a scene with no lights is lit by the rig", lit.get("lit_by") == "blendpipe studio rig",
          lit.get("lit_by"))
    m = measure(lit["images"][0])
    check("and the subject is visible at all", m is not None)
    # A silhouette has one flat value; a lit surface has a gradient across it.
    check("with a shading gradient, not a flat silhouette",
          m and m["shading_range"] > 0.15, m and round(m["shading_range"], 3))
    check("the rig leaves nothing behind",
          ex("import bpy; result=[o.name for o in bpy.context.scene.objects]") == ["Suzanne"])

    ex("""
import bpy
d = bpy.data.lights.new('Key', type='AREA'); d.energy = 500
bpy.context.scene.collection.objects.link(bpy.data.objects.new('Key', d))
""")
    users = bridge.call("render", {"output_dir": os.path.join(out, "users"),
                                   "angles": [0], "resolution": 160}, port=PORT)
    check("but a scene the user has lit keeps its own lighting",
          users.get("lit_by") == "the scene", users.get("lit_by"))


def test_render_reports_the_engine_it_used(out):
    """Bug: the engine was read after the finally restored the caller's, so an
    EEVEE critique render of a Cycles scene reported CYCLES."""
    print("\nrender engine reporting")
    clear()
    ex("import bpy; bpy.ops.mesh.primitive_cube_add(size=1); bpy.context.scene.render.engine='CYCLES'")
    r = bridge.call("render", {"output_dir": os.path.join(out, "engine"),
                               "angles": [0], "resolution": 96}, port=PORT)
    check("a Cycles scene renders on EEVEE for speed", r["engine"] != "CYCLES", r["engine"])
    check("and says so", r["engine"].startswith("BLENDER_EEVEE"), r["engine"])
    check("while the scene keeps the engine it had",
          ex("import bpy; result=bpy.context.scene.render.engine") == "CYCLES")


def test_framing_follows_the_lens(out):
    """Bug: distance was subject size x 2.2, a constant only right at 50mm.

    A 200mm scene camera framed the subject at a fraction of the frame and a
    400m subject fell past the default 100m clip_end -- and the render still
    succeeded, so nothing said anything was wrong.
    """
    print("\nframing")
    for label, lens, setup in (
        ("50mm", 50.0, "bpy.ops.mesh.primitive_monkey_add(size=2)"),
        ("200mm", 200.0, "bpy.ops.mesh.primitive_monkey_add(size=2)"),
        ("18mm", 18.0, "bpy.ops.mesh.primitive_monkey_add(size=2)"),
        ("400m subject", 50.0, "bpy.ops.mesh.primitive_cube_add(size=400)"),
        ("0.02m subject", 50.0, "bpy.ops.mesh.primitive_cube_add(size=0.02)"),
    ):
        clear()
        ex("import bpy\n%s\nd=bpy.data.cameras.new('C'); d.lens=%r\n"
           "c=bpy.data.objects.new('C', d); bpy.context.scene.collection.objects.link(c)\n"
           "bpy.context.scene.camera=c" % (setup, lens))
        r = bridge.call("render", {"output_dir": os.path.join(out, "fit-" + label.replace(" ", "-")),
                                   "angles": [0, 90, 180, 270], "resolution": 200}, port=PORT)
        shots = [measure(p) for p in r["images"]]
        check("%s: the subject is in every frame" % label, all(s is not None for s in shots))
        if not all(shots):
            continue
        check("%s: nothing is cut off by the frame or the clip range" % label,
              not any(s["clipped"] for s in shots))
        widest = max(max(s["fill_w"], s["fill_h"]) for s in shots)
        check("%s: it fills the frame at its widest angle" % label, widest > 0.6, round(widest, 3))
        check("%s: and stays centred" % label,
              all(s["off"] < 0.1 for s in shots), round(max(s["off"] for s in shots), 3))


def test_angle_zero_is_the_front():
    """Bug: angle 0 sat at +X, so view_000 -- the frame a reader sees first and
    the one that becomes the thumbnail -- was the *back* of the subject.

    The addon module is live in this Blender, so the orbit can be checked
    exactly rather than inferred from pixels.
    """
    print("\nturnaround orientation")
    got = ex("""
import sys, mathutils
addon = sys.modules["blendpipe_addon"]
c = mathutils.Vector((0.0, 0.0, 0.0))
result = {str(a): [round(v, 4) for v in addon._orbit_position(c, 10.0, a, 0.0)]
          for a in (0, 90, 180, 270)}
""")
    # Blender's front view (numpad 1) looks along +Y, so the camera sits at -Y.
    check("0 deg is Blender's front (-Y)", got["0"] == [0.0, -10.0, 0.0], got["0"])
    check("90 deg is the right side (+X)", got["90"] == [10.0, 0.0, 0.0], got["90"])
    check("180 deg is the back (+Y)", got["180"] == [0.0, 10.0, 0.0], got["180"])
    check("270 deg is the left side (-X)", got["270"] == [-10.0, 0.0, 0.0], got["270"])


def test_render_leaves_the_camera_alone(out):
    """The camera is the user's. Widening its clipping to fit a 400m subject is
    fine; leaving it widened is not."""
    print("\ncamera restoration")
    clear()
    ex("""
import bpy
bpy.ops.mesh.primitive_monkey_add(size=2)
d = bpy.data.cameras.new('User'); d.lens = 35.0; d.clip_start = 0.1; d.clip_end = 100.0
c = bpy.data.objects.new('User', d); bpy.context.scene.collection.objects.link(c)
bpy.context.scene.camera = c
""")
    read = ("import bpy; d=bpy.context.scene.camera.data;"
            " result={'start':d.clip_start,'end':d.clip_end,'ortho':d.ortho_scale}")
    before = ex(read)
    bridge.call("render", {"output_dir": os.path.join(out, "restore"),
                           "angles": [0], "resolution": 96}, port=PORT)
    check("clipping and ortho scale are put back", ex(read) == before, before)
    check("and the camera is back where the user left it",
          ex("import bpy; c=bpy.context.scene.camera;"
             " result=[round(v,5) for v in c.location] + [round(v,5) for v in c.rotation_euler]")
          == [0.0] * 6)

    ex("import bpy; d=bpy.context.scene.camera.data; d.type='ORTHO'; d.ortho_scale=1.0")
    r = bridge.call("render", {"output_dir": os.path.join(out, "ortho"),
                               "angles": [0, 90], "resolution": 200}, port=PORT)
    shots = [measure(p) for p in r["images"]]
    check("an orthographic camera frames the subject", all(s and not s["clipped"] for s in shots))
    check("and its ortho scale is restored",
          ex("import bpy; result=bpy.context.scene.camera.data.ortho_scale") == 1.0)


def test_exports_write_real_files(out):
    print("\nexport")
    clear()
    ex("import bpy; bpy.ops.mesh.primitive_monkey_add(size=2); bpy.context.active_object.name='Suzanne'")
    for ext in ("glb", "obj", "stl", "fbx", "gltf"):
        path = os.path.join(out, "export", "suzanne." + ext)
        try:
            reply = bridge.call("export_mesh", {"path": path, "objects": ["Suzanne"]},
                                timeout=180, port=PORT)
            ok = reply["bytes"] > 0 and os.path.exists(path)
        except Exception as exc:
            ok, reply = False, str(exc).splitlines()[0]
        check("%s exports a non-empty file" % ext, ok, reply)


def main():
    blender = find_blender()
    if blender is None:
        print("no Blender found -- set BLENDER_BIN to run these. Skipping.")
        return 0
    print("Blender: %s" % blender)

    out = os.path.join(os.environ.get("TMPDIR", "/tmp"), "blendpipe-live-%d" % os.getpid())
    os.makedirs(out, exist_ok=True)
    stop = os.path.join(ROOT, ".live-stop-%d" % PORT)
    if os.path.exists(stop):
        os.remove(stop)

    proc = subprocess.Popen(
        [blender, "--background", "--factory-startup", "--python",
         os.path.join(ROOT, "tests", "live_host.py"), "--", ROOT, str(PORT)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            if proc.poll() is not None:
                print("Blender exited before it was ready:\n" + (proc.stdout.read() or ""))
                return 1
            try:
                with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.3)
        else:
            print("Blender never opened port %d" % PORT)
            return 1

        for fn in (test_bridge_is_live, test_probe_runs_in_blender,
                   test_gate_catches_broken_geometry, test_uv_quality_on_real_geometry,
                   test_render_lights_an_unlit_scene,
                   test_render_reports_the_engine_it_used, test_angle_zero_is_the_front,
                   test_framing_follows_the_lens,
                   test_render_leaves_the_camera_alone, test_exports_write_real_files):
            try:
                fn(out) if fn.__code__.co_argcount else fn()
            except Exception as exc:
                check("%s raised" % fn.__name__, False, exc)
    finally:
        open(stop, "w").close()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        if os.path.exists(stop):
            os.remove(stop)

    print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("failed: " + ", ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
