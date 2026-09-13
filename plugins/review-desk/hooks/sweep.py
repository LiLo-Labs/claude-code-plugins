#!/usr/bin/env python3
"""Session start: tell the session which review desks are still waiting on it.

A reviewer decides on a page, often when no session is running, and the page's
doorbell only reaches a session that is watching. This is the path that does
not depend on anyone watching: every session start lists the desks nobody has
collected. It cannot read a desk's decision itself -- only the Artifact tool
can -- so it hands the session the list and what to do with it.

It never fails the session. Every outcome exits 0; a ledger it cannot read is
reported to the session rather than swallowed, because a silently unreadable
ledger is exactly how a decision gets lost.
"""
import json
import os
import sys

LEDGER = os.path.join(os.path.expanduser("~"), ".review-desks.json")

# A session holds at most five artifact watches, so only the newest five
# undecided desks can have their doorbell heard live. Older ones wait for the
# next session start.
WATCH_CAP = 5


def pending(entries):
    """Entries with no collectedAt, in ledger order (oldest first)."""
    found = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("collectedAt"):
            continue
        if not (e.get("repo") and e.get("pr") and e.get("url")):
            continue
        found.append(e)
    return found


def message(waiting):
    watch = {id(e) for e in waiting[-WATCH_CAP:]}
    lines = [
        "Review desks still waiting to be collected (from ~/.review-desks.json):",
        "",
    ]
    for e in waiting:
        mark = " [watch]" if id(e) in watch else ""
        lines.append(f"- {e['repo']}#{e['pr']} {e['url']}{mark}")
    lines += [
        "",
        "Before the user's first request, read each desk's decision with the "
        'Artifact tool (action "read_db", db_op "get", collection "review", '
        'doc_id "pr-<number>"). Then, for each:',
        "- A recorded decision: follow /review-collect for that request.",
        "- Messages sent to the working session with no reply yet: answer them "
        'as /review-desk describes under "While they read".',
        "- No decision, and the pull request is merged or closed: set its "
        "collectedAt in ~/.review-desks.json to the current UTC time.",
        '- No decision, still open, marked [watch]: pass action "watch" with '
        "its URL, so the reviewer's button reaches this session.",
        "Say in one line what you found. Never act on a decision you did not "
        "read from the record.",
    ]
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
        print(context(message(waiting)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
