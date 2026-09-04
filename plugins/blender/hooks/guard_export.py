#!/usr/bin/env python3
"""Do not let a mesh leave without having been measured.

The plugin's whole claim is that a result is rendered, checked and only then
called finished. A prompt can ask for that; a hook can enforce the last step of
it. Exporting an unverified mesh is how a non-manifold defect reaches a game
engine or a printer, where it costs hours rather than seconds.

This blocks only the export tool, and only when no successful verify has been
recorded for the current session. It never blocks modelling, rendering or
inspection — the agent's ordinary work is untouched.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hook_state  # noqa: E402

#: A verify from an hour ago says nothing about a mesh edited since.
MAX_AGE = int(os.environ.get("BLENDPIPE_VERIFY_MAX_AGE", "1800"))


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    tool = event.get("tool_name")
    session = event.get("session_id")

    # PostToolUse on verify_geometry: remember that it happened, and whether it passed.
    if hook_state.is_tool(tool, "verify_geometry") and event.get("hook_event_name") == "PostToolUse":
        text = json.dumps(event.get("tool_response") or "")
        hook_state.record(session, verified_at=time.time(), verify_passed="VERDICT: PASS" in text)
        return 0

    if not hook_state.is_tool(tool, "export_mesh"):
        return 0

    state = hook_state.load(session)
    verified_at = state.get("verified_at")

    if not verified_at:
        sys.stderr.write(
            "BlendPipe export guard: nothing has been verified in this session.\n\n"
            "Run verify_geometry before exporting. Exporting a mesh nobody measured is "
            "how a non-manifold edge or a missing UV map reaches the engine, where it "
            "costs far more to find than it does here.\n")
        return 2

    age = time.time() - verified_at
    if age > MAX_AGE:
        sys.stderr.write(
            "BlendPipe export guard: the last verify was %d minutes ago and the mesh has "
            "very likely changed since.\n\nRe-run verify_geometry, then export.\n" % (age / 60))
        return 2

    if not state.get("verify_passed"):
        sys.stderr.write(
            "BlendPipe export guard: the last verify_geometry reported blocking findings "
            "and they have not been cleared.\n\n"
            "Fix them and re-verify. If you believe the budget is wrong for this asset, "
            "say so to the user and let them decide — do not export around it.\n")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
