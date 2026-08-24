"""PreToolUse hook: warn before anything edits the paint codec.

scripts/paintlib/encoding.py is a port of OrcaSlicer's own serializer, checked
against fixtures taken from that source. A plausible-looking change to it does
not fail loudly: it produces 3MFs that open fine and slice into the wrong
colors, or that Orca silently discards the paint from. Every output file the
plugin has ever written depends on it being exactly right.

So this is a warning, not a block -- the codec may legitimately need to grow
(more filaments, a new subdivision case) -- but it should never be edited by
accident or in passing. Exit 0 with a systemMessage: Claude sees the note and
proceeds.
"""

import json
import os
import sys

PROTECTED = (
    os.path.join("scripts", "paintlib", "encoding.py"),
    os.path.join("paintlib", "encoding.py"),
)

NOTE = (
    "model-paint: %s is the paint codec -- a verified port of OrcaSlicer's "
    "TriangleSelector::serialize(). Its output is what every painted 3MF is "
    "made of, and a wrong-but-plausible encoding produces files that open "
    "cleanly and slice into the wrong colors. Change it only deliberately, keep "
    "the fixtures in tests/test_paint.py passing (they come from OrcaSlicer's "
    "source, not from this code), and re-run the full test suite before "
    "trusting any output written afterwards."
)


def _paths(tool_input):
    """Every file path a Write/Edit-shaped tool call names."""
    if not isinstance(tool_input, dict):
        return []
    found = []
    for key in ("file_path", "filePath", "path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str):
            found.append(value)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            if isinstance(edit, dict) and isinstance(edit.get("file_path"), str):
                found.append(edit["file_path"])
    return found


def is_protected(path):
    normalized = path.replace("\\", "/")
    return any(normalized.endswith(suffix.replace("\\", "/")) for suffix in PROTECTED)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0

    hits = [path for path in _paths(payload.get("tool_input")) if is_protected(path)]
    if not hits:
        return 0

    json.dump({"systemMessage": NOTE % hits[0], "suppressOutput": True}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
