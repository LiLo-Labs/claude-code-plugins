---
name: review-desk
description: Use when a pull request needs a human decision and a diff is the wrong surface for it — design documents, architectural choices, anything where the reviewer needs to ask "why" before they can say yes. Also use when a reviewer is on a phone or tablet, away from a terminal, and cannot run anything. Publishes the request as a page they can talk to Claude inside, then writes the discussion back to the pull request and merges on their approval.
---

# Review desk

A diff is the wrong surface for a decision. It tells a reviewer what changed and
gives them no way to ask why — so they either wave it through or send
instructions, and neither is judgement.

This turns a pull request into a conversation: a page carrying what is needed to
judge it, an exchange with Claude held inside it, and a decision recorded at the
end that comes back here to be acted on.

## When it earns its place

- **A design document**, where the decision is about intent rather than code.
- **A reviewer away from a terminal.** They cannot run the tests, so anything
  needing checking must be checked before they are asked to look.
- **A request too large to read as a patch**, where what they need is orientation
  and a way to interrogate it.

For a two-line fix, this is overhead. Use it where a decision is genuinely being
asked for.

## How it goes

1. `/review-desk <pr>` — gather the request, build the page, publish it with the
   capabilities object the build prints (`db` with its write rules, and
   `artifact`), hand over the link.
2. They read, ask, argue, and press **Approve** or **Needs changes**. The page
   rings the session watching it; with no session watching, the next session
   start picks the desk up.
3. `/review-collect <pr>` — read the discussion, summarise it into the pull
   request, merge or revise. Each decision is collected once: a pickup already
   holding it means later rings only answer messages. The desk stays open,
   listed at session start and after pushes, until the request is merged or
   closed.

## Writing the page

Invoke `elements-of-style:writing-clearly-and-concisely` if it is available
before composing any prose that lands on the page — the summary, the openers,
the plain-English account of a code-only request. There is no way for a plugin
to require another plugin; this is the same soft reference
`superpowers:brainstorming` uses, and it does nothing when the skill is absent.

**Draw the change.** The page renders mermaid diagrams, and the request is
described with them: a sequence, flow or state diagram of what this change
does, with inferred edges dotted. The command's "Draw it" section has the rules.
Mermaid already in the request's files (fenced in markdown, or `.mmd`) is drawn
in place.

## What it is honest about

**The page's chat is the working session.** Messages go to the session that
opened the pull request, which answers with its tools and can change the desk
and the pull request. While no session is running, a message waits for the next
one to start, and the page says so. Say that at handover.

**Without `db` nothing reaches the session.** The page still renders, but
neither a message nor a decision can be stored. Declare both capabilities, with
the write rules the build prints, or anyone the desk is shared with can write a
reply the page shows as the working session's.

## The rule that matters

Never merge on a decision you inferred. Read it from the record or ask. The
entire point of the arrangement is that someone can say no, and a bot merging on
its own reading of the mood has quietly removed them from it.
