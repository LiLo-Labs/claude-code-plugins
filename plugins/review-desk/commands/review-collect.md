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

Take the working session's answers from `review/pr-<n>/replies` (list it, one
document per answered message, keyed by the message's `id`), not from the
`content` of the `"via": "session"` turns. Anyone the desk is shared with can
write `review/pr-<n>`, so a turn there can claim to be the session's answer;
only the desk's owner can write `replies`. A session turn with no reply document
was not answered by the session, whatever its `content` says.

That `reason` is the request. Quote it in the comment rather than paraphrasing
it, and act on it — the conversation is context for why they asked, but the
reason is what they actually asked for.

If there is no document, the discussion was never saved. Say so rather than
inventing one.

If there is a decision, and `review/pr-<n>/context/pickup` does not already hold
the same `decision` and `decidedAt`, write the pickup before anything else, as
`/review-desk` describes under "When they decide". Until one lands, the
reviewer's page says it is still waiting.

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

After acting on a decision, report what happened as the pickup's `outcome`, as
`/review-desk` describes under "When they decide": `merged` with the method and
commit, `revising` with the work, or `blocked` with what stopped you. A merge
that auto mode or branch protection refuses is `blocked`, never silence; the
reviewer's page otherwise goes on saying the decision was picked up.

## Never

When you have acted on a decision -- the comment posted, and merged or not --
set `collectedAt` on that request's entry in `~/.review-desks.json` to the
current UTC time. An entry that stays null is listed again by the plugin's
session-start sweep every time a session starts in that repository, so leaving
it means nagging;
stamping one you did not act on means the decision is silently dropped.

Do not merge on a decision you inferred rather than read. The whole arrangement
exists because someone has to be able to say no, and a bot that merges on its
own reading of the mood has removed them from it.
