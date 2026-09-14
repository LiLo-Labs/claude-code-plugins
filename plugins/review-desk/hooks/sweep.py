#!/usr/bin/env python3
"""Session start: tell the session which review desks are still waiting on it.

A reviewer decides on a page, often when no session is running, and the page's
doorbell only reaches a session that is watching. This is the path that does
not depend on anyone watching: a session started in a repository lists that
repository's desks nobody has collected. It cannot read a desk's decision
itself -- only the Artifact tool can -- so it hands the session the list and
what to do with it.

Desks for other repositories are only counted. Every listed desk costs a
database read before the user's first request, and a session opened in an
unrelated repository should not pay that for every desk on the machine.
hooks.json runs this on startup and resume only, so /clear and /compact do not
send a session back through the sweep in the middle of its work.

It never fails the session. Every outcome exits 0; a ledger it cannot read is
reported to the session rather than swallowed, because a silently unreadable
ledger is exactly how a decision gets lost.
"""
import json
import os
import sys

from after_push import is_open, repo_of

LEDGER = os.path.join(os.path.expanduser("~"), ".review-desks.json")

# A session holds at most five artifact watches, and a watch the session asked
# for is never evicted to make room. Filling all five here left a desk the
# session then published with no watch, so the sweep asks for four and keeps
# one slot for /review-desk. Older desks wait for the next session start.
WATCH_CAP = 4

# How long a claimed message may sit at "working" before another session takes
# it over. /review-desk states the same age; tests/test_protocol_docs.py holds
# the two together.
STALE_CLAIM_MINUTES = 5


def pending(entries):
    """Open entries, in ledger order (oldest first)."""
    return [e for e in entries if is_open(e)]


def message(waiting, here):
    """The sweep for a session whose origin is `here` (None outside a GitHub
    repository): this repository's desks in full, then one line counting the rest."""
    mine = [e for e in waiting if e["repo"] == here]
    others = {}
    for e in waiting:
        if e["repo"] != here:
            others[e["repo"]] = others.get(e["repo"], 0) + 1
    lines = []
    if mine:
        watch = {id(e) for e in mine[-WATCH_CAP:]}
        lines += [
            f"Review desks for {here} still open (from ~/.review-desks.json):",
            "",
        ]
        for e in mine:
            mark = " [watch]" if id(e) in watch else ""
            lines.append(f"- {e['repo']}#{e['pr']} {e['url']}{mark}")
        lines += [
            "",
            "Before the user's first request, read each desk with the Artifact "
            'tool, in one batch per desk: action "read_db", db_op "get", '
            'collection "review", doc_id "pr-<number>"; db_op "get", collection '
            '"review/pr-<number>/context", doc_id "pickup"; and db_op "list", '
            'collection "review/pr-<number>/replies". Then, for each:',
            "- A recorded decision whose decision and decidedAt the pickup does "
            "not already hold: follow /review-collect for that request. A pickup "
            "that already holds both means the decision was handled; do not "
            "collect it again.",
            "- Messages still waiting, meaning no reply document, or a reply at "
            f'"working" whose "at" is more than {STALE_CLAIM_MINUTES} minutes old '
            'and whose "session" is not this session: answer them as /review-desk '
            'describes under "While they read".',
            "- Nothing left to collect, and the pull request is merged or closed: "
            'set its outcome ("merged" or "closed") and collectedAt in '
            "~/.review-desks.json, the time in UTC.",
            '- Nothing left to collect, still open, marked [watch]: pass action '
            '"watch" with its URL, so the reviewer\'s button reaches this session, '
            "and stamp its presence with this session's resume command, as "
            '/review-desk describes under "Whenever a ring arrives".',
            "Say in one line what you found. Never act on a decision you did not "
            "read from the record.",
        ]
    if others:
        total = sum(others.values())
        counts = ", ".join(f"{repo} ({n})" for repo, n in others.items())
        if lines:
            lines.append("")
        lines.append(
            f"{total} more review {'desk waits' if total == 1 else 'desks wait'} "
            f"in other repositories, not read from this session: {counts}. A "
            "session started in that repository lists them in full; "
            "/review-collect owner/repo#number collects one from anywhere."
        )
    return "\n".join(lines)


def context(text):
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    })


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    if not isinstance(event, dict):
        event = {}
    try:
        with open(LEDGER, encoding="utf-8") as f:
            entries = json.load(f)
    except FileNotFoundError:
        return 0
    except (OSError, ValueError) as err:
        print(context(
            f"~/.review-desks.json could not be read ({err}). Review desk "
            "decisions recorded there cannot be collected until it is fixed; "
            "tell the user."
        ))
        return 0
    if not isinstance(entries, list):
        print(context(
            "~/.review-desks.json is not a list, so no review desk can be "
            "collected from it; tell the user."
        ))
        return 0
    waiting = pending(entries)
    if waiting:
        print(context(message(waiting, repo_of(event.get("cwd") or os.getcwd()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
