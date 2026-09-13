#!/usr/bin/env python3
"""After a git push: remind the session which review desks show that repository.

A desk shows a pull request as it was when the desk was written. Push a change
and the desk is wrong until the session rewrites it, and nothing else will
notice: the session made the change in the terminal, the reviewer is looking at
a page. This hook is the notice. It cannot rewrite the desk itself -- only the
Artifact tool can -- so it tells the session which desks to look at.

Silent unless the command was a push to a repository with an open desk. Every
outcome exits 0: a reminder that fails must never fail the push it follows.
"""
import json
import os
import re
import shlex
import subprocess
import sys

LEDGER = os.path.join(os.path.expanduser("~"), ".review-desks.json")


def pushed_from(command, cwd):
    """The directory the push ran in: `git -C <dir> push`, `cd <dir> && ... git
    push`, or the session's working directory."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    for i, w in enumerate(words):
        if w == "git" and i + 2 < len(words) and words[i + 1] == "-C":
            return os.path.expanduser(words[i + 2])
    m = re.search(r"(?:^|[;&|]\s*)cd\s+(\"[^\"]+\"|'[^']+'|\S+)", command)
    if m:
        return os.path.expanduser(m.group(1).strip("\"'"))
    return cwd


def repo_of(directory):
    """owner/name from the origin remote, for GitHub over https or ssh."""
    try:
        url = subprocess.run(
            ["git", "-C", directory, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    # `git` has to be the command itself -- at the start, or after && ; | -- so
    # `echo git push` or a commit message mentioning a push is not mistaken for one.
    if not re.search(r"(?:^|[;&|]\s*)(?:\w+=\S*\s+)*git(?:\s+-C\s+\S+)?\s+push\b",
                     command.strip()):
        return 0
    repo = repo_of(pushed_from(command, event.get("cwd") or os.getcwd()))
    if not repo:
        return 0
    try:
        with open(LEDGER, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return 0
    open_desks = [e for e in entries if isinstance(e, dict)
                  and e.get("repo") == repo and not e.get("collectedAt")
                  and e.get("pr") and e.get("url")]
    if not open_desks:
        return 0
    lines = [f"You just pushed to {repo}, which has open review desks:"]
    lines += [f"- #{e['pr']} {e['url']}" for e in open_desks]
    lines += [
        "",
        "If this push changed what a desk shows, rewrite it now, as /review-desk "
        'describes under "Changing the desk and the pull request": the '
        "description and any carried file that changed. Then tell the reviewer "
        "in a reply what changed and the commit. A push that touches none of "
        "these pull requests needs nothing.",
    ]
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": "\n".join(lines),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
