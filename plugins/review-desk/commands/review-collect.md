---
description: Read the review conversation back, write it into the PR, and merge on approval
argument-hint: "[number, owner/repo#number, or URL — defaults to what we are discussing]"
---

Collect the discussion held on the review desk for pull request **$1**, put it
somewhere permanent, and act on the decision.

A conversation that stays in a page is a conversation that is lost. The
reasoning behind a decision is usually worth more than the decision, and it
belongs with the code it was about.

## Work out which request

`$1` resolves the same way it does for `/review-desk`: a URL or
`owner/repo#number` says it outright, a bare number means the request under
discussion in this conversation rather than whatever the working directory
points at, nothing at all means the current branch, and only silence in the
conversation hands the decision to the directory's remote. Name the repository
you resolved to before acting.

This matters more here than it does there. `/review-desk` that guesses wrong
publishes a page; this command writes a comment onto a pull request and can
merge it. Guessing wrong is not recoverable by closing a tab.

Pass `--repo` on every `gh` call.

## Read it back

Find the artifact published for this request (`action: "list"` on the Artifact
tool if the URL is not to hand), then read the stored conversation:

    action: "read_db", db_op: "get", collection: "review", doc_id: "pr-<n>"

The document holds `threads` — the conversations, each with its `turns` in order
and the passage it was started from — and `decision`, which is `approved`,
`needs changes`, or absent if they have not finished. A `needs changes` decision
also carries `reason`: what the reviewer said has to change, in their words.

That `reason` is the request. Quote it in the comment rather than paraphrasing
it, and act on it — the conversation is context for why they asked, but the
reason is what they actually asked for.

If there is no document, the discussion was never saved. Say so rather than
inventing one.

## Write it into the request

Post one comment on the pull request summarising the exchange. Not a transcript
— a summary that would be useful to someone finding this in five years:

- **What was asked, and what it turned on.** The question behind the question.
- **What changed as a result** — a claim withdrawn, a decision reversed, a gap
  admitted. If nothing changed, say that; a review that changed nothing is worth
  recording as much as one that did.
- **What was left open**, so it is not silently dropped.

Attribute plainly: the reviewer's words are theirs, the answers came from the
page. Quote sparingly and only where the exact wording carries the point.

## Act on it

**Approved** — merge it. Say which merge you used and confirm it landed.

**Needs changes** — do not merge. Turn what they asked for into the specific
work, and say what you are going to do before doing it.

**Undecided** — say so and stop. Do not interpret silence as either.

## Never

Do not merge on a decision you inferred rather than read. The whole arrangement
exists because someone has to be able to say no, and a bot that merges on its
own reading of the mood has removed them from it.
