#!/usr/bin/env python3
"""Stop a runaway loop from spending real money on mesh generation.

Every `generate_mesh` call on a paid backend is a charge on the user's own API
key. An agent that re-rolls a bad prompt in a loop is the exact failure this
guards: it is fast, it looks like progress, and nobody notices until the invoice.

The ceiling is per session and deliberately low. It is not a security boundary —
the user can raise it with BLENDPIPE_MAX_GENERATIONS — it is a speed bump that
forces the agent to stop and think about the prompt instead of the button.

Generation on a local backend is free, so it is not counted.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hook_state  # noqa: E402

LIMIT = int(os.environ.get("BLENDPIPE_MAX_GENERATIONS", "10"))


def paid_backend_in_use(tool_input):
    """True unless we can tell the generation is free."""
    explicit = (tool_input.get("backend") or "").strip().lower()
    if explicit:
        return explicit != "local"
    pinned = (os.environ.get("BLENDPIPE_BACKEND") or "").strip().lower()
    if pinned:
        return pinned != "local"
    # Unpinned: local wins when configured, so an available local URL means free.
    return not os.environ.get("BLENDPIPE_LOCAL_URL")


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    if not hook_state.is_tool(event.get("tool_name"), "generate_mesh"):
        return 0

    tool_input = event.get("tool_input") or {}
    if not paid_backend_in_use(tool_input):
        return 0

    session = event.get("session_id")
    state = hook_state.load(session)
    used = int(state.get("paid_generations", 0))

    if used >= LIMIT:
        sys.stderr.write(
            "BlendPipe spend guard: %d paid mesh generations have already run in this "
            "session, which is the limit.\n\n"
            "Stop and reconsider rather than re-rolling. Usually one of these is true:\n"
            "  - the subject is hard-surface or modular and should be built procedurally "
            "with execute_python, which is free and gives better topology\n"
            "  - the prompt has not actually changed between attempts, so you are paying "
            "for variance\n"
            "  - the result was fine and the real problem is scale, orientation or "
            "topology, all of which are fixed in Blender for free\n\n"
            "Tell the user what has been spent and ask before continuing. To raise the "
            "ceiling: BLENDPIPE_MAX_GENERATIONS=%d.\n" % (used, LIMIT * 2))
        return 2

    hook_state.record(session, paid_generations=used + 1)
    if used + 1 == LIMIT:
        sys.stderr.write("BlendPipe: this is paid generation %d of %d for this session.\n"
                         % (used + 1, LIMIT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
