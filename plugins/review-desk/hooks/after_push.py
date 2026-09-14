#!/usr/bin/env python3
"""After a git push: remind the session which review desks show that repository.

A desk shows a pull request as it was when the desk was written. Push a change
and the desk is wrong until the session rewrites it, and nothing else will
notice: the session made the change in the terminal, the reviewer is looking at
a page. This hook is the notice. It cannot rewrite the desk itself -- only the
Artifact tool can -- so it tells the session which desks to look at.

The command this hook is shown is the one that ran, after any PreToolUse hook
rewrote it. With RTK installed, `git push` arrives as `rtk git push`. So a push
is recognised by the command that actually runs once wrappers and variable
assignments are set aside, not by the first word of the line.

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

# Commands that run the command after them, each with its options that take a
# separate value, so `timeout -s KILL 60 git push` skips exactly the right words.
WRAPPERS = {
    "rtk": set(),
    "command": set(),
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "nice": {"-n", "--adjustment"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
}
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                     "--super-prefix", "--config-env"}
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")

# The only ledger outcomes that close a desk. A `revising` or `blocked` desk is
# still under review: the reviewer can change their decision or send a message,
# and the revision's pushes still need the desk rewritten.
TERMINAL = ("merged", "closed")


def is_open(entry):
    """A well-formed ledger entry nobody has closed. The recorded outcome decides:
    an entry whose outcome is not terminal stays open even if it carries a
    collectedAt stamp (a hand edit, or a session that stamped too early). An
    entry stamped with no outcome at all was written before outcomes were
    recorded and is left closed, since nothing here can tell a merged one from
    a revising one."""
    if not isinstance(entry, dict):
        return False
    if not (entry.get("repo") and entry.get("pr") and entry.get("url")):
        return False
    if not entry.get("collectedAt"):
        return True
    outcome = entry.get("outcome")
    return bool(outcome) and outcome not in TERMINAL


def segments(command):
    """The simple commands in `command` as word lists, quoting resolved, split at
    && || ; | & newlines and parentheses. `2>&1` stays inside its command."""
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
        lex.whitespace = " \t\r"
        lex.whitespace_split = True
        lex.commenters = ""
        tokens = list(lex)
    except ValueError:
        # Unbalanced quotes. Plain splitting still finds an ordinary push.
        return [part.split() for part in re.split(r"[;&|\n()]+", command)]
    found, words = [], []
    for token in tokens:
        if token and all(c in "();|&\n" for c in token):
            found.append(words)
            words = []
        else:
            words.append(token)
    found.append(words)
    return found


def unwrap(words):
    """`words` with leading assignments and wrapper commands set aside."""
    i = 0
    while i < len(words):
        word = words[i]
        if ASSIGNMENT.match(word):
            i += 1
            continue
        if word not in WRAPPERS:
            break
        takes_value = WRAPPERS[word]
        i += 1
        if word == "rtk" and i < len(words) and words[i] == "proxy":
            i += 1
        while i < len(words) and words[i].startswith("-"):
            i += 2 if words[i] in takes_value else 1
        if word == "timeout":
            i += 1  # the duration
    return words[i:]


def push_directory(words, base):
    """The directory `words` push from, if they run `git ... push`; else None."""
    words = unwrap(words)
    if not words or os.path.basename(words[0]) != "git":
        return None
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            base = os.path.join(base, os.path.expanduser(words[i + 1]))
        i += 2 if words[i] in GIT_VALUE_OPTIONS else 1
    return base if i < len(words) and words[i] == "push" else None


def pushed_from(command, cwd):
    """Where the command's push runs: the session's directory, moved by any `cd`
    before the push and by `git -C`. None when the command does not push."""
    base = cwd
    for words in segments(command):
        directory = push_directory(words, base)
        if directory:
            return directory
        if len(words) > 1 and words[0] == "cd":
            base = os.path.join(base, os.path.expanduser(words[1]))
    return None


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
    directory = pushed_from(command, event.get("cwd") or os.getcwd())
    if not directory:
        return 0
    repo = repo_of(directory)
    if not repo:
        return 0
    try:
        with open(LEDGER, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(entries, list):
        return 0
    open_desks = [e for e in entries if is_open(e) and e["repo"] == repo]
    if not open_desks:
        return 0
    lines = [f"You just pushed to {repo}, which has open review desks:"]
    lines += [f"- #{e['pr']} {e['url']}" for e in open_desks]
    lines += [
        "",
        "If this push changed what a desk shows, rewrite it now, as /review-desk "
        'describes under "Changing the desk and the pull request": the '
        "description at context/body and any carried file that changed. Open "
        'context/body with a "Changed since you opened this" section naming '
        "each commit pushed since the desk was published and what it changed, "
        "so the reviewer reading the page learns the pull request moved. A push "
        "that failed, or touches none of these pull requests, needs nothing.",
    ]
    # A command that exits non-zero arrives as PostToolUseFailure, and
    # `git push && <a later step that fails>` pushed all the same.
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": event.get("hook_event_name") or "PostToolUse",
        "additionalContext": "\n".join(lines),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
