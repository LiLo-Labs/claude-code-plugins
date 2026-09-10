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
   `sample` and `db` capabilities, hand over the link.
2. They read, ask, argue, and press **Approve** or **Needs changes**.
3. `/review-collect <pr>` — read the discussion, summarise it into the pull
   request, merge or revise.

## What it is honest about

**The Claude inside the page is not the session that wrote the code.** It is a
fresh call that can see the request and the conversation and nothing else. It
cannot run tests, read other files, or check anything. Say so at handover, and
make sure the page carries enough material that it can answer well from what it
has.

**The reviewer pays for the calls**, and the first one asks their consent.

**Without `db` the conversation is not saved.** The page still works and the
discussion still happens, but nothing comes back. Declare both capabilities.

## The rule that matters

Never merge on a decision you inferred. Read it from the record or ask. The
entire point of the arrangement is that someone can say no, and a bot merging on
its own reading of the mood has quietly removed them from it.
