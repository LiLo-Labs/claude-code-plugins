"""Shared state for the BlendPipe hooks.

The two guardrails here both need to remember something across tool calls — how
much has been spent, and whether the geometry was ever actually checked. A hook
is a fresh process every time, so that memory lives in a small JSON file keyed by
the session.

Kept in the runs directory rather than the project tree: this is session
bookkeeping, not something anyone should ever commit or review.
"""

import json
import os
import time

RUNS = os.path.expanduser(os.environ.get("BLENDPIPE_RUNS", "~/.blendpipe/runs"))


def _path(session_id):
    safe = "".join(c for c in str(session_id or "default") if c.isalnum() or c in "-_")[:64]
    return os.path.join(RUNS, "state-%s.json" % (safe or "default"))


def load(session_id):
    try:
        with open(_path(session_id)) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save(session_id, state):
    path = _path(session_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(state, handle)
    os.replace(tmp, path)


def record(session_id, **fields):
    state = load(session_id)
    state.update(fields)
    state["updated"] = time.time()
    save(session_id, state)
    return state


#: Claude Code namespaces a *plugin's* MCP tools as
#: mcp__plugin_<plugin>_<server>__<tool>, while a user-configured server is just
#: mcp__<server>__<tool>. These hooks originally matched only the second form,
#: so in a real install neither guardrail ever fired -- no spend ceiling, and no
#: verify-before-export -- while every unit test passed, because the tests fed
#: the hooks the name the hooks expected. Accept both, and don't pin the exact
#: namespacing scheme in three places.
def is_tool(tool_name, suffix, server="blender"):
    """True when tool_name is this plugin's `suffix` tool under any namespacing."""
    if not isinstance(tool_name, str) or not tool_name.startswith("mcp__"):
        return False
    head, sep, tail = tool_name[len("mcp__"):].partition("__")
    return bool(sep) and tail == suffix and server in head.split("_")
