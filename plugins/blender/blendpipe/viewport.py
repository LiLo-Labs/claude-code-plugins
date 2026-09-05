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

#: Runs on Blender's main thread. Reads the scene, decides which workspace the
#: work has reached, and moves the window to it.
FOLLOW = r'''
import bpy

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

for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        area.spaces.active.shading.type = "MATERIAL" if textured else "SOLID"
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is not None:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.view3d.view_all()

result = {
    "stage": stage,
    "reached": reached,
    "objects": len(meshes),
    "faces": sum(len(o.data.polygons) for o in meshes),
    "materials": len({m.name for o in meshes for m in o.data.materials if m}),
}
'''


def follow_code(min_stage=0):
    """The snippet with this run's high-water stage bound in.

    repr, not json.dumps -- this is Python source, and that mistake has already
    been made once in this codebase.
    """
    return "MIN_STAGE = %r\n%s" % (int(min_stage), FOLLOW)


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
