"""Keep Blender's own window pointed at whatever the agent is doing.

An unattended run rewrites the scene without moving the UI, so a person watching
sees a still frame of something that no longer exists — the window sits on the
last thing a human framed while the agent works somewhere else entirely. Two
minutes of that is indistinguishable from a wedged run.

This drives the workspace tab, the shading mode and the framing from outside, on
the same bridge the agent uses. Doing it here rather than asking the agent to do
it in its prompt is deliberate: the agent knows its stage exactly and this can
only infer it, but inference costs no prompt weight, cannot be forgotten
half-way through a run, and keeps working when the model is busy thinking rather
than calling tools — which is exactly when a watcher most needs a signal.

Everything it touches is view state. It never selects, moves or edits anything,
so it cannot disturb the work it is watching.
"""

import threading

from . import bridge

#: How far back to sit from a subject, as a multiple of its diagonal. Enough to
#: hold it comfortably in frame without the empty space view_all leaves.
FRAMING_MARGIN = 1.6
#: Floor on the framed span, so a 3 mm object does not put the camera inside it.
MIN_SPAN_M = 0.05
#: A mesh this flat and this much larger than everything else is scene
#: furniture, not the subject. Excluded from framing so the thing being worked
#: on fills the viewport.
GROUND_FLATNESS = 0.02
GROUND_RELATIVE_SIZE = 3.0

#: Near and far clip, relative to the viewing distance.
CLIP_NEAR_FRACTION = 0.01
CLIP_FAR_FACTOR = 100.0

#: Runs on Blender's main thread. Reads the scene, decides which workspace the
#: work has reached, and moves the window to it.
FOLLOW = r'''
import bpy, mathutils

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    stage, textured = "Layout", False
else:
    textured = any(m and m.use_nodes for o in meshes for m in o.data.materials)

    # "Has a UV layer" is true of every primitive, so it cannot mean unwrapped.
    # A real unwrap spreads islands across the square; a default cube unwrap and
    # a pile of stacked ones both stay in a corner.
    unwrapped = False
    for o in meshes:
        me = o.data
        if not me.uv_layers or len(me.polygons) <= 6:
            continue
        data = me.uv_layers.active.data
        xs = [data[i].uv.x for i in range(0, min(len(data), 400))]
        if xs and (max(xs) - min(xs)) > 0.5:
            unwrapped = True
            break
    stage = "Shading" if textured else ("UV Editing" if unwrapped else "Layout")

# Never move backward: MIN_STAGE is the furthest this run has already reached.
ORDER = ("Layout", "UV Editing", "Shading")
reached = max(ORDER.index(stage), MIN_STAGE if meshes else 0)
stage = ORDER[reached]

workspace = bpy.data.workspaces.get(stage)
if workspace is not None and bpy.context.window.workspace != workspace:
    bpy.context.window.workspace = workspace

# Blender's own status bar, bottom right. The cheapest possible answer to
# "is this thing working or has it hung", and it is real UI rather than a
# console line in a terminal the watcher may not have in front of them.
try:
    counts = "%d objects · %d faces" % (
        len(meshes), sum(len(o.data.polygons) for o in meshes))
    bpy.context.workspace.status_text_set("BlendPipe — %s · %s" % (stage.lower(), counts))
except Exception:
    pass

# Frame the MESHES, not the scene. view_all() includes lights and cameras, so a
# 25 mm acorn lit by lamps at 13 cm was framed as a speck among its own rig --
# the viewport was technically following the work and showing none of it.
# Written straight to the view matrix so nothing is selected or moved: a follower
# that changes selection can break the operation it is watching.
# The ground is not part of an asset. It belongs to the engine, and a scene
# only holds one while something is being looked at. Framing everything in the
# scene therefore fits the ground plane -- which is how a 25 mm acorn ended up a
# speck in the middle of a 14 m rectangle.
def _is_ground(obj, others):
    size = obj.dimensions
    flat = min(size) <= max(size) * GROUND_FLATNESS
    if not flat:
        return False
    span = max(size)
    biggest_other = max((max(o.dimensions) for o in others if o is not obj), default=0.0)
    return span >= biggest_other * GROUND_RELATIVE_SIZE


subjects = [o for o in meshes if not _is_ground(o, meshes)] or meshes

centre = None
distance = None
if subjects:
    corners = [o.matrix_world @ mathutils.Vector(c)
               for o in subjects for c in o.bound_box]
    lo = mathutils.Vector((min(c.x for c in corners), min(c.y for c in corners),
                           min(c.z for c in corners)))
    hi = mathutils.Vector((max(c.x for c in corners), max(c.y for c in corners),
                           max(c.z for c in corners)))
    centre = (lo + hi) / 2.0
    span = max((hi - lo).length, MIN_SPAN_M)
    distance = span * FRAMING_MARGIN

for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.shading.type = "MATERIAL" if textured else "SOLID"
        # Clip planes have to admit the subject, or a millimetre-scale asset is
        # framed correctly and clipped out of existence.
        if distance is not None:
            space.clip_start = min(space.clip_start, distance * CLIP_NEAR_FRACTION)
            space.clip_end = max(space.clip_end, distance * CLIP_FAR_FACTOR)
            r3d = space.region_3d
            if r3d.view_perspective != "CAMERA":
                r3d.view_location = centre
                r3d.view_distance = distance
        area.tag_redraw()

result = {
    "stage": stage,
    "reached": reached,
    "objects": len(meshes),
    "framed": len(subjects),
    "faces": sum(len(o.data.polygons) for o in meshes),
    "materials": len({m.name for o in meshes for m in o.data.materials if m}),
}
'''


def follow_code(min_stage=0):
    """The snippet with this run's stage and every constant it uses bound in.

    The snippet runs inside Blender, where nothing from this module exists. A
    name used in FOLLOW and not bound here is a NameError at the far end of a
    socket, reported nowhere, and the follower silently stops following.

    repr, not json.dumps -- this is Python source, and that mistake has already
    been made once in this codebase.
    """
    bindings = {
        "MIN_STAGE": int(min_stage),
        "FRAMING_MARGIN": FRAMING_MARGIN,
        "MIN_SPAN_M": MIN_SPAN_M,
        "CLIP_NEAR_FRACTION": CLIP_NEAR_FRACTION,
        "CLIP_FAR_FACTOR": CLIP_FAR_FACTOR,
        "GROUND_FLATNESS": GROUND_FLATNESS,
        "GROUND_RELATIVE_SIZE": GROUND_RELATIVE_SIZE,
    }
    preamble = "\n".join("%s = %r" % (k, v) for k, v in sorted(bindings.items()))
    return preamble + "\n" + FOLLOW


class Follower:
    """Poll the scene and move the window to match. Start it, stop it, done."""

    #: Work moves forward through these. The tab must not move backward with it:
    #: mid-build some objects are unwrapped and some are not, so the inferred
    #: stage oscillates, and a workspace tab flipping every five seconds is
    #: worse company than one that does not move at all.
    ORDER = ("Layout", "UV Editing", "Shading")

    def __init__(self, every=5.0, on_change=None, host=None, port=None):
        self.every, self.on_change = every, on_change
        self.host, self.port = host, port
        self.last = None
        self._peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _ratchet(self, state):
        """Carry the furthest stage forward; reset when the scene is cleared."""
        self._peak = 0 if not state.get("objects") else max(
            self._peak, int(state.get("reached", 0)))
        return state

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.stop()
        return False

    def _loop(self):
        while not self._stop.wait(self.every):
            try:
                reply = bridge.call("execute", {"code": follow_code(self._peak)},
                                    timeout=30, host=self.host, port=self.port)
            except Exception:
                # Blender busy or gone. The watchdog decides what that means;
                # a viewport follower must never be the thing that fails a run.
                continue
            if not reply.get("ok"):
                continue
            state = reply.get("result")
            if not state:
                continue
            self._ratchet(state)
            if state != self.last:
                self.last = state
                if self.on_change:
                    self.on_change(state)
