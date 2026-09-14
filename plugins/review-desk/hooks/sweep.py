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

While a desk is open it also reads, and only reads, the Claude Code settings
files that apply to this session, and adds one line when no allow rule covers
the `gh pr merge` an approval runs: in auto mode the classifier can refuse that
merge, and the approval then waits for someone at the computer. A settings file
it cannot read or parse makes it say nothing about merges, since it cannot tell
what is allowed. It never writes settings: a permission is the user's to grant.
"""
import json
import os
import re
import stat
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

# The merge /review-collect runs for an approval, and the allow rule the README
# and review-collect.md name for it. tests/test_protocol_docs.py holds the docs
# to these. Claude Code matches permission rules against the command a
# PreToolUse hook returns, so under RTK's rewriting hook the command matched is
# `rtk gh pr merge ...` and needs its own rule.
MERGE_COMMAND = "gh pr merge 1 --repo o/r --match-head-commit 0123abc --squash"
MERGE_RULE = "Bash(gh pr merge *)"
RTK_MERGE_RULE = "Bash(rtk gh pr merge *)"
README_SECTION = "Unattended merges"

# A settings file larger than this is not read. Settings are a few kilobytes;
# the cap keeps a stray huge file from slowing session start.
SETTINGS_MAX_BYTES = 1 << 20


class Unreadable(Exception):
    pass


def bash_rule_covers(rule, command, broad):
    """Whether a permission rule matches `command` as Claude Code's permissions
    docs describe Bash rules: `*` stands for any text, a trailing ` *` also
    matches the bare command, and `:*` at the end means the same as ` *`.
    A blanket rule (`Bash`, `Bash(*)`) counts only when `broad`: auto mode
    drops such allow rules, while deny and ask rules of that shape still apply.
    Any other rule with nothing before its first `*` (`Bash(* --force)`) is
    never counted as an allow rule, so the advice errs toward being shown, and
    as a deny or ask rule it counts only when it actually matches `command`."""
    if not isinstance(rule, str):
        return False
    rule = rule.strip()
    if rule == "Bash":
        return broad
    m = re.fullmatch(r"Bash\((.*)\)", rule, re.S)
    if not m:
        return False
    pattern = m.group(1)
    if pattern.endswith(":*"):
        pattern = pattern[:-2] + " *"
    if pattern.strip() == "*":
        return broad
    if "*" in pattern and not pattern.split("*", 1)[0].strip() and not broad:
        return False
    if re.fullmatch(".*".join(re.escape(p) for p in pattern.split("*")), command, re.S):
        return True
    return pattern.endswith(" *") and pattern.count("*") == 1 and command == pattern[:-2]


def git_root(directory):
    """The nearest ancestor holding `.git`, found by stat alone so session start
    does not wait on a git process."""
    here = os.path.abspath(directory)
    for _ in range(64):
        if os.path.exists(os.path.join(here, ".git")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return None
        here = parent
    return None


def user_settings_path():
    """Where Claude Code reads user settings: `$CLAUDE_CONFIG_DIR/settings.json`
    when that is set, else `~/.claude/settings.json`."""
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(config, "settings.json")


def settings_paths(cwd):
    """(is user settings, path) for the files Claude Code reads permissions from
    for a session in `cwd`: user settings, the directory's shared and local
    project settings, and local settings at the repository root. Managed
    settings are not read."""
    paths = [(True, user_settings_path())]
    if cwd:
        paths.append((False, os.path.join(cwd, ".claude", "settings.json")))
        paths.append((False, os.path.join(cwd, ".claude", "settings.local.json")))
        root = git_root(cwd)
        if root:
            paths.append((False, os.path.join(root, ".claude", "settings.local.json")))
    seen, unique = set(), []
    for user, path in paths:
        key = os.path.realpath(path)
        if key not in seen:
            seen.add(key)
            unique.append((user, path))
    return unique


def read_settings(path):
    """The settings object at `path`, or None when there is no file. Anything
    else that is not a small regular file holding a JSON object raises
    Unreadable; the stat check keeps a FIFO from blocking the open."""
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > SETTINGS_MAX_BYTES:
        raise Unreadable(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise Unreadable(path)
    return data


def rewrites_through_rtk(data):
    hooks = data.get("hooks")
    groups = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    for group in groups if isinstance(groups, list) else []:
        inner = group.get("hooks") if isinstance(group, dict) else None
        for hook in inner if isinstance(inner, list) else []:
            command = hook.get("command") if isinstance(hook, dict) else None
            if isinstance(command, str) and re.search(r"\brtk\b", command):
                return True
    return False


def merge_advice(cwd):
    """One line for the session when no allow rule lets `gh pr merge` run
    unattended, or None: when a rule covers it, when a deny or ask rule shows
    the user chose to be stopped, or when any settings file cannot be read."""
    try:
        allow, stop, rtk, classify_all = [], [], False, False
        for user, path in settings_paths(cwd):
            data = read_settings(path)
            if data is None:
                continue
            perms = data.get("permissions", {})
            if not isinstance(perms, dict):
                raise Unreadable(path)
            for key in ("allow", "ask", "deny"):
                rules = perms.get(key, [])
                if not isinstance(rules, list):
                    raise Unreadable(path)
                (allow if key == "allow" else stop).extend(rules)
            rtk = rtk or rewrites_through_rtk(data)
            # Claude Code reads autoMode from user settings, not project files.
            auto = data.get("autoMode") if user else None
            classify_all = classify_all or (isinstance(auto, dict) and auto.get("classifyAllShell") is True)
    except (Unreadable, OSError, ValueError, RecursionError):
        return None
    needs = [(MERGE_COMMAND, MERGE_RULE)]
    if rtk:
        needs.append(("rtk " + MERGE_COMMAND, RTK_MERGE_RULE))
    if any(bash_rule_covers(r, cmd, broad=True) for r in stop for cmd, _ in needs):
        return None
    missing = [rule for cmd, rule in needs
               if not any(bash_rule_covers(r, cmd, broad=False) for r in allow)]
    where = f'as the review-desk README section "{README_SECTION}" explains'
    if classify_all:
        return (
            "Unattended merges are not allowed here: autoMode.classifyAllShell is on in "
            "user settings, which suspends every Bash allow rule in auto mode, so an "
            "approval collected from a review desk can stop at blocked until someone "
            f"merges it by hand. Tell the user that in one line, {where}. Do not change "
            "any settings file yourself."
        )
    if not missing:
        return None
    rules = " and ".join(f"`{r}`" for r in missing)
    return (
        "Unattended merges are not allowed here: no permission allow rule in the "
        "Claude Code settings this session reads covers `gh pr merge`, so in auto mode "
        "an approval collected from a review desk can stop at blocked until someone "
        f"merges it by hand. Tell the user in one line that adding {rules} to "
        f"permissions.allow in {user_settings_path()} lets approvals merge unattended, "
        f"{where}. Do not add the rule or change any settings file yourself."
    )


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
        text = message(waiting, repos_of(cwd), cwd)
        advice = merge_advice(cwd)
        if advice:
            text += "\n\n" + advice
        print(context(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
