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
lists the open desks for that repository, so the session rewrites whatever the
push made out of date.

The page draws mermaid diagrams: the ones Claude writes into the description,
fenced `mermaid` blocks in any markdown file the request carries, and `.mmd`
files. A diagram that does not parse shows its source and the error instead.
The library (mermaid 11.15.0, pinned by hash) loads only on pages that have a
diagram.

The page needs the `db` and `artifact` capabilities. Without `db` neither a
message nor a decision can reach the session.

Pressing **Approve** or **Needs changes** reaches the session two ways. The page
stores the decision and publishes a small file into itself, which wakes the
Claude Code session watching the desk within seconds of it going idle; that
session writes back a pickup, and the page shows when it landed. If no session
is watching, a session-start hook lists the desks in `~/.review-desks.json` that
have not been collected for the repository a session starts or resumes in, and
counts the ones waiting elsewhere, so the next session there picks it up. A
session can watch at most five desks at once.

## Why it exists

Built for a reviewer who reads pull requests on an iPad, away from any terminal,
and who needs to approve intent before code exists rather than audit code after
it arrives.
