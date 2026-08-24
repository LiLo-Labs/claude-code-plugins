"""PreToolUse hook: refuse Bash commands that would modify mesh geometry.

Reads the tool call on stdin, applies guard_lib's rules to the command, and
exits 2 with an explanation when the command would re-mesh, weld, decimate,
transform, repair, or overwrite a model the user intends to print. Exit 0
otherwise, including for anything this hook cannot understand -- a guardrail
that fails closed on malformed input would block ordinary work for no gain, and
the geometry claim is verified independently after the fact anyway.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard_lib import evaluate, format_block


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return 0

    findings = evaluate(command)
    if not findings:
        return 0

    sys.stderr.write(format_block(command, findings) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
