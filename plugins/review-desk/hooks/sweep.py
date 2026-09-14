#!/usr/bin/env python3
"""Session start: tell the session which review desks are still waiting on it.

A reviewer decides on a page, often when no session is running, and the page's
doorbell only reaches a session that is watching. This is the path that does
not depend on anyone watching: a session lists in full the open desks for any
repository its directory's remotes name (origin, upstream or any other), and
the desks whose ledger entry records this directory as the `cwd` the
publishing session was launched in, which covers a desk published from a
directory that is not a checkout of its repository. It cannot read a desk's decision
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

from after_push import entry_repo_in, is_open, repos_of

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


def same_directory(recorded, cwd):
    """Whether a ledger entry's recorded `cwd` names the session's directory.
    Compared resolved, so /tmp and /private/tmp on macOS are one place. Older
    entries have no `cwd`, and a hand-edited one may not be a string."""
    if not isinstance(recorded, str) or not recorded or not cwd:
        return False
    try:
        return os.path.realpath(recorded) == os.path.realpath(cwd)
    except (OSError, ValueError):
        return False


def message(waiting, repos, cwd=None):
    """The sweep for a session in `cwd`, whose remotes name `repos` (casefolded;
    empty outside a GitHub repository): the desks for those repositories or
    recorded as launched from `cwd` in full, then one line counting the rest."""
    mine, others = [], {}
    for e in waiting:
        if entry_repo_in(e, repos) or same_directory(e.get("cwd"), cwd):
            mine.append(e)
        else:
            others[e["repo"]] = others.get(e["repo"], 0) + 1
    lines = []
    if mine:
        watch = {id(e) for e in mine[-WATCH_CAP:]}
        lines += [
            "Review desks still open for this directory, by its remotes or "
            "because they were published from it (from ~/.review-desks.json):",
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
            'collection "review/pr-<number>/replies". When the pr-<number> '
            'document has a "repo" field naming a repository other than the '
            "desk's, that URL is another repository's desk: act on nothing there, "
            "and tell the user. Then, for each desk, in this order:",
            "- A recorded decision the pickup holds with the same decision and "
            "decidedAt and an outcome was handled; do not collect it again. A "
            "matching pickup with no outcome is a claim on the decision: when its "
            f'"session" is another session\'s (or it has none) and its "at" is more than '
            f"{STALE_CLAIM_MINUTES} minutes old, or its \"session\" is this "
            "session's own, it is stale, so take it over as /review-desk "
            'describes under "When they decide". Any other recorded decision is '
            "new: acknowledge it as that section describes.",
            "- Messages still waiting, meaning no reply document, or a reply at "
            '"working" that is a stale claim: its "session" is another '
            f'session\'s (or it has none) and its "at" is more than {STALE_CLAIM_MINUTES} minutes '
            'old, or its "session" is this session\'s own, whatever its age. '
            "claude --resume keeps the session id, and the turn that was "
            "answering it has stopped. Answer them as /review-desk describes "
            'under "While they read", before collecting any decision.',
            "- Only then collect a decision you acknowledged or took over, naming "
            "the desk in full: "
            + ", ".join(f"/review-collect {e['repo']}#{e['pr']}" for e in mine)
            + ". Never a bare number, which resolves to the request under "
            "discussion and can be the same number in another repository.",
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
            "session started in a checkout of that repository, or in the "
            "directory the desk was published from, lists them in full; "
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
    except (OSError, ValueError, RecursionError) as err:
        # RecursionError: valid JSON nested deeper than the decoder allows
        # before Python 3.14. Reported like any other unreadable ledger.
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
        cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
        cwd = cwd or os.getcwd()
        print(context(message(waiting, repos_of(cwd), cwd)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
