"""Runs *inside* Blender: register the real addon and serve the real socket.

`--background` has no event loop, so `bpy.app.timers` never fires and the pump
would never run. This script is itself on Blender's main thread, so it drains
the queue by calling the addon's own `_pump()` -- the same function the timer
calls, on the same thread it would call it from. What that does not cover is the
timer registration itself; `test_addon_is_importable_shape` asserts that
structurally.
"""

import importlib.util
import os
import sys
import time

ROOT = sys.argv[sys.argv.index("--") + 1]
PORT = int(sys.argv[sys.argv.index("--") + 2])
sys.path.insert(0, ROOT)

spec = importlib.util.spec_from_file_location(
    "blendpipe_addon", os.path.join(ROOT, "blendpipe", "addon.py"))
addon = importlib.util.module_from_spec(spec)
# Registered before exec so tests can reach the live module through sys.modules
# and check its helpers exactly, rather than inferring them from pixels.
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()

server = addon.BridgeServer(port=PORT)
server.start()
print("BLENDPIPE-TEST-READY", flush=True)

stop = os.path.join(ROOT, ".live-stop-%d" % PORT)
deadline = time.time() + 600
while time.time() < deadline and not os.path.exists(stop):
    addon._pump()
    time.sleep(0.02)
server.stop()
