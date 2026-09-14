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
push whose branches cannot be told (a refspec that is a shell expansion such
as `"$(git branch --show-current)"` included), lists every desk as before. A
command with several pushes lists the desks of each.

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
# git push's own options, from its option table (builtin/push.c), checked against
# git 2.50.1. Only these take their value as the next word. `--force-with-lease`
# and `--signed` take one only attached with `=`: `git push --signed yes origin
# b` pushes to a repository named yes.
PUSH_VALUE_OPTIONS = {"--repo", "--receive-pack", "--exec", "--push-option",
                      "--recurse-submodules"}
# Pushes that update every branch, or only tags, so no one desk can be picked.
PUSH_EVERYTHING = {"--all", "--branches", "--mirror", "--tags"}
PUSH_FLAGS = PUSH_EVERYTHING | {
    "--verbose", "--quiet", "--delete", "--dry-run", "--porcelain", "--force",
    "--force-with-lease", "--force-if-includes", "--thin", "--set-upstream",
    "--progress", "--prune", "--no-verify", "--verify", "--follow-tags",
    "--signed", "--atomic", "--ipv4", "--ipv6"}
PUSH_OPTIONAL_VALUE = {"--force-with-lease", "--signed"}
PUSH_SHORT_FLAGS = set("vqdnfu46")
PUSH_SHORT_VALUE = "o"  # -o, --push-option
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


def pushes(command, cwd):
    """Every push in the command, in order, as (directory, words after `push`):
    the session's directory, moved by any `cd` before that push and by
    `git -C`. Every push, not the first: `git push origin a && git push origin
    b` moves both pull requests. Empty when the command does not push."""
    base, found = cwd, []
    for words in segments(command):
        push = push_directory(words, base)
        if push:
            found.append(push)
        elif len(words) > 1 and words[0] == "cd":
            base = os.path.join(base, os.path.expanduser(words[1]))
    return found


def option_words(word):
    """How many words the git push option `word` spans: 1, or 2 when its value
    is the next word. None for an option git push does not declare, or one
    written in a shape git refuses, since its value may be the next word and
    then every word after it is misread."""
    if word.startswith("--"):
        name, attached, _ = word.partition("=")
        if name.startswith("--no-") and "--" + name[5:] in PUSH_FLAGS | PUSH_VALUE_OPTIONS:
            return None if attached else 1
        if name in PUSH_VALUE_OPTIONS:
            return 1 if attached else 2
        if name in PUSH_FLAGS and (not attached or name in PUSH_OPTIONAL_VALUE):
            return 1
        return None
    # A cluster of short options such as `-fu`; `-o` ends it, taking the rest of
    # the word as its value, or the next word when nothing follows.
    for k, letter in enumerate(word[1:], start=1):
        if letter == PUSH_SHORT_VALUE:
            return 1 if k + 1 < len(word) else 2
        if letter not in PUSH_SHORT_FLAGS:
            return None
    return 1


def refspecs(args):
    """The refspecs among a push's arguments (the words after `push`): its
    positional words after the first, which git always takes as the repository
    (`--repo` only stands in when there is none), with redirections such as
    `2>&1` set aside. None when an option pushes more than named branches, or is
    one this hook cannot read."""
    positional, options_done, i = [], False, 0
    while i < len(args):
        word = args[i]
        if word and all(c in "<>&" for c in word):
            i += 2  # the redirection and its target
        elif word.isdigit() and i + 1 < len(args) and args[i + 1][:1] in "<>&":
            i += 1  # the descriptor in front of a redirection
        elif not options_done and word == "--":
            options_done = True
            i += 1
        elif not options_done and word.startswith("-") and word != "-":
            if word in PUSH_EVERYTHING:
                return None
            span = option_words(word)
            if span is None:
                return None
            i += span
        else:
            positional.append(word)
            i += 1
    return positional[1:]


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


def push_branch(directory):
    """The remote branch a bare `git push` updates, from `@{push}`; falls back
    to the checked-out branch when git cannot say. A local branch can push to a
    differently named remote branch (`local-b` tracking `origin/b` with
    push.default=upstream), and the desk records the remote name."""
    try:
        done = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--abbrev-ref",
             "--symbolic-full-name", "@{push}"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        done = None
    pushed = done.stdout.strip() if done and done.returncode == 0 else ""
    if "/" in pushed:
        return pushed.split("/", 1)[1]
    return current_branch(directory)


# Characters that mark a word as a shell expansion the hook only sees
# unexpanded (`"$BRANCH"`, `"$(git branch --show-current)"`, backticks, and the
# `$` left when an unquoted `$(` is split at its parenthesis), or a glob. Git
# does accept some of them in branch names (`feat(x)`); such a push is read as
# unknown, which lists every desk rather than missing one.
NOT_A_NAME = re.compile(r"[$`(){}\[\]*?~\\]")


def pushed_branches(args, directory):
    """The names of the branches a push with `args` updates on the remote: the
    destination of each refspec, or the checked-out branch when the push names
    none or names HEAD. None when that cannot be told (`--all`, a wildcard
    refspec, a shell expansion, `:` or an empty refspec, a detached HEAD, a git
    failure), and the caller then lists every desk rather than guess one. The
    refspec wins over the checkout: after `git push origin other` the
    checked-out branch is not what moved."""
    specs = refspecs(args)
    if specs is None:
        return None
    names = set()
    for spec in specs or ["HEAD"]:
        source, _, destination = spec.lstrip("+").partition(":")
        name = destination or source
        if not name or NOT_A_NAME.search(name):
            return None
        if name in ("HEAD", "@"):
            name = push_branch(directory)
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
    found = [(directory, args, repos_of(directory))
             for directory, args in pushes(command, cwd or os.getcwd())]
    if not any(repos for _, _, repos in found):
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
    listed = set()
    for directory, args, repos in found:
        desks = [i for i, e in enumerate(entries) if is_open(e) and entry_repo_in(e, repos)]
        if any(entries[i].get("branch") for i in desks):
            branches = pushed_branches(args, directory)
            desks = [i for i in desks if entry_on_branch(entries[i], branches)]
        listed.update(desks)
    open_desks = [entries[i] for i in sorted(listed)]
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
