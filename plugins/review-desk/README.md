# review-desk

Review a pull request as a conversation instead of a diff.

A diff tells you what changed. It gives you no way to ask **why**, which is most
of what a reviewer actually wants to do — so requests get waved through, or
answered with instructions, and neither of those is judgement.

This publishes a pull request as a page: what is needed to judge it, a
conversation with Claude held inside it, and a decision recorded at the end.
The discussion then comes back and is written into the pull request, so the
reasoning lives with the code rather than evaporating.

## Use

    /review-desk <owner/repo>#<number>       # publish it, hand over the link
    /review-collect <owner/repo>#<number>    # answer, write the discussion in, act on the decision

Both also take a pull request URL. A bare number means the pull request the
conversation has been about, which can belong to another repository; only when
the conversation says nothing does the working directory's remote decide. Pull request numbers repeat
across repositories, and `/review-collect` comments and can merge, so name the
repository. A ring and the session-start hook always pass the full name.

## Worth knowing

The chat in the page goes to **the working session**: the Claude Code session
that opened the pull request, with the conversation, the repository and its
tools. It answers while it is running, and can rewrite the desk and push changes
to the pull request while you watch. Whatever you highlight goes along with the
question, with the tab and section you were reading. A message sent while no
session is running is answered by the next one to start.

The panel says when the working session last answered, and has a **Check**
button that rings it and waits. If nothing answers, the page shows the command
that brings that session back (`claude --resume …`), for someone at the computer
to run; a page cannot start a session by itself. After any `git push`, a hook
lists the open desks for every repository named by any git remote of the
checkout the push ran from, so a push to a fork reaches the upstream's desk, and
the session rewrites whatever the push made out of date.

A page can be read three ways: **Document**, **Since you read**, and **Against
main** — whatever branch the request is against. The two changed views are
redlines, drawn in the document rather than beside it: what went is struck
through where it stood, what arrived is underlined in its place, and a reworded
sentence shows the old phrase then the new one. Prose stays prose — a changed
heading is still a heading — and a source file keeps every line, changed or not,
because a file read as a handful of fragments cannot be judged. Syntax colouring
and diagrams are left off in these two views: both are drawn by replacing a
block's markup, which would take the marks with it.

*Since you read* is what is new to you on this tab, which is how a back and
forth reaches you. *Against main* is what the request itself changes: the file as
it will be against the file as it is on the branch, which is the thing you are
being asked to approve. A page that has moved says so in a bar over it, and a
view with nothing to compare with is offered but disabled — so a page you have
never read still answers the second question, and a file the request adds says
that instead of drawing a comparison with nothing.

**Mark as read** moves the read baseline; looking at the document does not, and
neither view touches the other. The setting holds for the desk, so asking what
changed is one press and then it is simply how the desk reads. What you have
read is remembered per browser tab, so the reload a ring causes does not lose
it; a desk opened on another device has read nothing yet and still has the
request's own diff.

The page draws mermaid diagrams: the ones Claude writes into the description,
fenced `mermaid` blocks in any markdown file the request carries, and `.mmd`
files. A diagram that does not parse shows its source and the error instead.
The library (mermaid 11.15.0, pinned by hash) loads only on pages that have a
diagram.

The page's footer says which review-desk built it, and every save records the
same version. A desk is a published page: it stays the version that published
it, so a fix that has shipped reaches an open desk only when that desk is
republished.

The page needs the `db` and `artifact` capabilities. Without `db` neither a
message nor a decision can reach the session. The build script prints the exact
object to publish with: `db` carries write rules, so only the desk's owner (the
session) can write replies, presence, context and documents, while anyone the
desk is shared with can still write the discussion and the decision. The page
shows the session's words only from its replies. Since 0.8.0 the discussion
document holds the reviewer's messages and where each one has got to, but no copy
of the answers, which any of those viewers could have written. A desk published
before 0.7.0 has no rules until it is republished.

**Approve** asks once before it records anything: the page names the pull request
and the commit it would merge, says how many answers are still being written or
messages still waiting, and records only on **Confirm**. **Back** or Escape
leaves nothing stored. **Needs changes** asks for its reason instead.

Pressing **Approve** or **Needs changes** reaches the session two ways. The page
stores the decision and publishes a small file into itself, which wakes the
Claude Code session watching the desk within seconds of it going idle; that
session writes back a pickup, and the page shows when it landed. It then
answers every message still waiting before it comments on or merges the pull
request, so the comment never calls a question unanswered. An approval followed
by a later message is not merged: it is recorded as `blocked`, and the reviewer
is asked to decide again. The same happens when commits are pushed after
**Approve**: the page stores the head commit it was showing with the decision,
and the session merges only that commit, with `gh pr merge --match-head-commit`.
When the head has moved, the session first writes the new commit into the desk,
so the page shows it and the reviewer's next decision is on it. A trivial fixup
pushed after approval therefore needs the reviewer to approve again.

A decision is acted on once: later messages and **Check** presses ring the same
desk, and a pickup already holding that decision and its outcome tells the
session to answer the messages rather than comment or merge again. A pickup with
no outcome is a claim; if the session that wrote it stops, another takes it over
after 5 minutes, and reads the pull request first so it neither comments nor
merges twice.

If no session is watching, a session-start hook reads `~/.review-desks.json` and
lists in full the open desks whose repository is named by any git remote of the
session's directory (origin, a fork's upstream, or any other), and the open
desks whose recorded launch directory is the session's directory, even outside
a git repository. It counts the ones open elsewhere, so the next session started
in either place picks the desk up. A desk is closed in the ledger, by stamping
`collectedAt`, only when its pull request is merged or closed. A desk sent back
with **Needs changes**, or blocked, is still listed, and still rewritten after a
push, while it is revised.

A session can watch at most five desks at once. The sweep asks for at most four,
so a desk published afterwards still gets a watch, and the session checks the
publish result rather than assuming one. A message a session claimed and never
answered, because that session stopped, is taken over by another session once
the claim has sat at "working" for 5 minutes, and at once by the same session
brought back with `claude --resume`, which keeps its id. The page itself still
shows such a claim as working until then; showing a stalled claim differently on
the page is left to a later release.

## Unattended merges

An approval on the desk merges on its own only if Claude Code lets the session
run `gh pr merge` without asking. In auto mode it often does not: the
classifier refused `gh pr merge` for an approved desk ("Merge Without Review",
then "External System Writes"), the desk recorded `blocked`, and the pull
request merged only when someone ran the command by hand. What lets it through
is a permission allow rule in your Claude Code settings:

    {
      "permissions": {
        "allow": ["Bash(gh pr merge *)"]
      }
    }

With RTK (Rust Token Killer) or any other PreToolUse hook that
rewrites shell commands, the rule also needs the rewritten form, because Claude
Code matches rules against the command the hook returns:

    "allow": ["Bash(gh pr merge *)", "Bash(rtk gh pr merge *)"]

The place for it is `~/.claude/settings.json`, your user settings. Desks are
collected from whichever directory a session starts in, and user settings apply
in all of them; a rule in a repository's `.claude/settings.json` or
`.claude/settings.local.json` covers only sessions started there. The
`/permissions` command shows the rules in effect.

What it costs: the rule allows every `gh pr merge` a session writes, in any
repository `gh` can reach, not only desk approvals. The desk's own checks (the
approved commit via `--match-head-commit`, no message after the decision) apply
only to merges that go through `/review-collect`. Narrowing the rule by
repository is not reliable, since Claude Code's docs call argument-matching
patterns fragile. It has no effect when a deny or ask rule also matches
`gh pr merge` (those are evaluated first), or when `autoMode.classifyAllShell`
is on, which suspends every Bash allow rule in auto mode.

The plugin does not add the rule itself. A permission is yours to grant, and a
plugin that wrote its own allow rule would be approving the very merge the check
is there to stop. It only reads: while a desk is open and no allow rule in your
user settings, or in the session directory's project settings, covers
`gh pr merge`, the session-start hook adds one line naming the rule. When a
merge is refused anyway, `/review-collect` records `blocked` with that rule in
the detail the reviewer reads, and running `/review-collect owner/repo#number`
after the rule is in place merges the approval without a new decision.

## Why it exists

Built for a reviewer who reads pull requests on an iPad, away from any terminal,
and who needs to approve intent before code exists rather than audit code after
it arrives.
