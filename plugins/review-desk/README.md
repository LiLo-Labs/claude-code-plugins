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

Both also take a pull request URL. A bare number resolves only within the
current repository: the pull request the conversation has been about, or else
the one the working directory's remote points at. Pull request numbers repeat
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

The page draws mermaid diagrams: the ones Claude writes into the description,
fenced `mermaid` blocks in any markdown file the request carries, and `.mmd`
files. A diagram that does not parse shows its source and the error instead.
The library (mermaid 11.15.0, pinned by hash) loads only on pages that have a
diagram.

The page needs the `db` and `artifact` capabilities. Without `db` neither a
message nor a decision can reach the session. The build script prints the exact
object to publish with: `db` carries write rules, so only the desk's owner (the
session) can write replies, presence, context and documents, while anyone the
desk is shared with can still write the discussion and the decision. The page
shows the session's words only from its replies. Since 0.8.0 the discussion
document holds the reviewer's messages and where each one has got to, but no copy
of the answers, which any of those viewers could have written. A desk published
before 0.7.0 has no rules until it is republished.

Pressing **Approve** or **Needs changes** reaches the session two ways. The page
stores the decision and publishes a small file into itself, which wakes the
Claude Code session watching the desk within seconds of it going idle; that
session writes back a pickup, and the page shows when it landed. It then
answers every message still waiting before it comments on or merges the pull
request, so the comment never calls a question unanswered. An approval followed
by a later message is not merged: it is recorded as `blocked`, and the reviewer
is asked to decide again.

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

## Why it exists

Built for a reviewer who reads pull requests on an iPad, away from any terminal,
and who needs to approve intent before code exists rather than audit code after
it arrives.
