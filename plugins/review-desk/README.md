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

    /review-desk 12          # publish it, hand over the link
    /review-collect 12       # read the discussion back, write it in, merge

## Worth knowing

The chat in the page reaches either of two Claudes, and the reviewer picks.
**The working session** is the Claude Code session that opened the pull request:
it has the conversation, the repository and its tools, answers while it is
running, and can rewrite the desk and push changes to the pull request while you
watch. **Here, no tools** is a fresh call that sees only the page and answers
straight away. If the working session has not picked a message up after 45
seconds, the page offers the quick answer instead.

The reviewer pays for those calls and is asked for consent on the first one.

The page draws mermaid diagrams: the ones Claude writes into the description,
fenced `mermaid` blocks in any markdown file the request carries, and `.mmd`
files. A diagram that does not parse shows its source and the error instead.
The library (mermaid 11.15.0, pinned by hash) loads only on pages that have a
diagram.

The page needs the `sample`, `db` and `artifact` capabilities. Without `db` the
conversation still happens but nothing comes back, which defeats the point.

Pressing **Approve** or **Needs changes** reaches the session two ways. The page
stores the decision and publishes a small file into itself, which wakes the
Claude Code session watching the desk within seconds of it going idle; that
session writes back a pickup, and the page shows when it landed. If no session
is watching, a session-start hook lists every desk in `~/.review-desks.json`
that has not been collected, so the next session picks it up. A session can
watch at most five desks at once.

## Why it exists

Built for a reviewer who reads pull requests on an iPad, away from any terminal,
and who needs to approve intent before code exists rather than audit code after
it arrives.
