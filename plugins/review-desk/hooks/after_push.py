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

The repository is any GitHub remote of the directory the push ran from, not
only origin: a fork's push updates a pull request whose desk is recorded under
the upstream.

Within that repository, a desk whose ledger entry records its `branch` is
listed only when that branch is pushed: the branches the push's refspecs name,
or the checked-out branch when it names none. Several desks open in one
repository are otherwise listed together, and a session can write one pull
request's commits onto another's desk. An entry without a `branch`, and any
push whose branches cannot be told, lists every desk as before.

Silent unless the command was a push from a checkout with an open desk. Every
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
PUSH_VALUE_OPTIONS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
# Pushes that update every branch, or only tags, so no one desk can be picked.
PUSH_EVERYTHING = {"--all", "--branches", "--mirror", "--tags"}
ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")

# The only ledger outcomes that close a desk. A `revising` or `blocked` desk is
# still under review: the reviewer can change their decision or send a message,
# and the revision's pushes still need the desk rewritten.
TERMINAL = ("merged", "closed")

OWNER_NAME = re.compile(r"[^/]+/[^/]+")


def well_formed(entry):
    """Whether a ledger entry has the shape a desk is named by: `repo` an
    owner/name string, `pr` a positive integer, `url` a non-empty string, and
    `branch` and `head`, which older entries lack, either absent, null or
    strings. Only types and shapes, never values, so a repo written in another
    case still matches. The ledger is edited by hand, and a repo that is a list
    reached a dict key in sweep.message and crashed the session-start hook."""
    if not isinstance(entry, dict):
        return False
    repo, pr, url = entry.get("repo"), entry.get("pr"), entry.get("url")
    return (isinstance(repo, str) and OWNER_NAME.fullmatch(repo) is not None
            and type(pr) is int and pr > 0
            and isinstance(url, str) and url != ""
            and all(entry.get(field) is None or isinstance(entry.get(field), str)
                    for field in ("branch", "head")))


def is_open(entry):
    """A well-formed ledger entry nobody has closed. The recorded outcome decides:
    an entry whose outcome is not terminal stays open even if it carries a
    collectedAt stamp (a hand edit, or a session that stamped too early). An
    entry stamped with no outcome at all was written before outcomes were
    recorded and is left closed, since nothing here can tell a merged one from
    a revising one."""
    if not well_formed(entry):
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
    """If `words` run `git ... push`: the directory they push from and the words
    after `push`. Else None."""
    words = unwrap(words)
    if not words or os.path.basename(words[0]) != "git":
        return None
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] == "-C" and i + 1 < len(words):
            base = os.path.join(base, os.path.expanduser(words[i + 1]))
        i += 2 if words[i] in GIT_VALUE_OPTIONS else 1
    if i < len(words) and words[i] == "push":
        return base, words[i + 1:]
    return None


def pushed_from(command, cwd):
    """Where the command's push runs, and the words after its `push`: the
    session's directory, moved by any `cd` before the push and by `git -C`.
    None when the command does not push."""
    base = cwd
    for words in segments(command):
        found = push_directory(words, base)
        if found:
            return found
        if len(words) > 1 and words[0] == "cd":
            base = os.path.join(base, os.path.expanduser(words[1]))
    return None


def refspecs(args):
    """The refspecs among a push's arguments (the words after `push`): its
    positional words after the repository, with redirections such as `2>&1` set
    aside. None when an option pushes more than named branches."""
    positional, repo_given, options_done, i = [], False, False, 0
    while i < len(args):
        word = args[i]
        if word and all(c in "<>&" for c in word):
            i += 2  # the redirection and its target
        elif word.isdigit() and i + 1 < len(args) and args[i + 1][:1] in "<>&":
            i += 1  # the descriptor in front of a redirection
        elif not options_done and word == "--":
            options_done = True
            i += 1
        elif not options_done and word.startswith("-"):
            if word in PUSH_EVERYTHING:
                return None
            repo_given = repo_given or word == "--repo" or word.startswith("--repo=")
            i += 2 if word in PUSH_VALUE_OPTIONS else 1
        else:
            positional.append(word)
            i += 1
    return positional if repo_given else positional[1:]


def current_branch(directory):
    """The branch checked out in `directory`; None on a detached HEAD, outside
    a repository, and on any git failure."""
    try:
        done = subprocess.run(
            ["git", "-C", directory, "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    name = done.stdout.strip()
    return name if done.returncode == 0 and name else None


def pushed_branches(args, directory):
    """The names of the branches a push with `args` updates on the remote: the
    destination of each refspec, or the checked-out branch when the push names
    none or names HEAD. None when that cannot be told (`--all`, a wildcard
    refspec, a detached HEAD, a git failure), and the caller then lists every
    desk rather than guess one. The refspec wins over the checkout: after
    `git push origin other` the checked-out branch is not what moved."""
    specs = refspecs(args)
    if specs is None:
        return None
    names = set()
    for spec in specs or ["HEAD"]:
        source, _, destination = spec.lstrip("+").partition(":")
        name = destination or source
        if "*" in name:
            return None
        if name in ("HEAD", "@"):
            name = current_branch(directory)
            if name is None:
                return None
        if name.startswith("refs/heads/"):
            name = name[len("refs/heads/"):]
        elif name.startswith("refs/"):
            continue  # a tag or another ref, which no pull request is on
        names.add(name)
    return names


def entry_on_branch(entry, branches):
    """Whether a push of `branches` can have moved this well-formed entry's pull
    request. An entry that records no branch, and a push whose branches are
    unknown, always match: a reminder too many costs the session a line, one
    too few leaves a desk out of date."""
    branch = entry.get("branch")
    return branches is None or not branch or branch in branches


GITHUB_URL = re.compile(r"github\.com(?::\d+)?[:/]([^/\s:]+/[^/\s]+?)(?:\.git)?/?$")


def repos_of(directory):
    """owner/name of every GitHub remote of `directory`, over https or ssh,
    casefolded because GitHub names are case-insensitive. Every remote, not
    only origin: in a fork checkout origin is the fork, and the pull request
    and its desk belong to the upstream. Empty outside a repository, and on any
    git failure."""
    try:
        out = subprocess.run(
            ["git", "-C", directory, "remote", "-v"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return set()
    found = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            m = GITHUB_URL.search(parts[1])
            if m:
                found.add(m.group(1).casefold())
    return found


def entry_repo_in(entry, repos):
    repo = entry.get("repo")
    return isinstance(repo, str) and repo.casefold() in repos


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return 0
    command = event["tool_input"].get("command")
    if not isinstance(command, str):
        return 0
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    found = pushed_from(command, cwd or os.getcwd())
    if not found:
        return 0
    directory, args = found
    repos = repos_of(directory)
    if not repos:
        return 0
    try:
        with open(LEDGER, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError, RecursionError):
        # RecursionError: valid JSON nested deeper than the decoder allows
        # before Python 3.14.
        return 0
    if not isinstance(entries, list):
        return 0
    open_desks = [e for e in entries if is_open(e) and entry_repo_in(e, repos)]
    if any(e.get("branch") for e in open_desks):
        branches = pushed_branches(args, directory)
        open_desks = [e for e in open_desks if entry_on_branch(e, branches)]
    if not open_desks:
        return 0
    lines = ["You just pushed from a checkout whose remotes have open review desks:"]
    lines += [f"- {e['repo']}#{e['pr']} {e['url']}" for e in open_desks]
    lines += [
        "",
        "If this push updated one of these pull requests, rewrite its desk now, "
        'as /review-desk describes under "Changing the desk and the pull '
        'request": context/body as {"text", "head"}, with head the headRefOid '
        "from `gh pr view <number> --repo <owner/repo> --json headRefOid` read "
        "after the push, and any carried file that changed. Write head even when "
        "the description needs no change: the page stores it as decidedOn, and "
        "an approval of an older head is never merged. Open context/body with a "
        '"Changed since you opened this" section, computed rather than recalled: '
        "read the stored context/body, keep the lines that section already has, "
        "and add one per commit in `git log --reverse --format='%h %s' "
        "<head>..origin/<branch>`, with head and branch as the desk's entry in "
        "~/.review-desks.json records them. Once that write has landed, set the "
        "entry's head to the headRefOid it wrote. A push that failed, or touches "
        "none of these pull requests, needs nothing.",
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
