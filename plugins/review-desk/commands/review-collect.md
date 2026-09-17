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

A ring and the session-start sweep always pass the full `owner/repo#number`,
taken from the `~/.review-desks.json` entry whose `url` is the desk. When you
arrive here from either with only a number, take the repository from that entry
rather than resolving the number from the conversation: the same number is
often a pull request in another repository too.

This matters more here than it does there. `/review-desk` that guesses wrong
publishes a page; this command writes a comment onto a pull request and can
merge it. Guessing wrong is not recoverable by closing a tab.

Pass `--repo` on every `gh` call.

## Read it back

Find the artifact published for this request. Look in `~/.review-desks.json`
first, for the entry whose `repo` and `pr` match; its `url` is the desk. Only
when no entry matches and the URL is not to hand, use `action: "list"` on the
Artifact tool. Then read the stored conversation, the working session's answers
and the pickup together, as three calls in one batch:

    action: "read_db",  db_op: "get",  collection: "review", doc_id: "pr-<n>"
    action: "read_db",  db_op: "list", collection: "review/pr-<n>/replies"
    action: "read_db",  db_op: "get",  collection: "review/pr-<n>/context", doc_id: "pickup"
    action: "write_db", db_op: "set",  collection: "review/pr-<n>/presence",
        doc_id: "<the version from the ring, else the current Unix time in seconds>",
        data: {"resume": "<the resume command>"}

If the list result carries `next_cursor`, read on with it before going further.
A pickup that does not exist yet comes back as not found; that is an answer, not
an error.

That fourth call is the presence stamp, and it goes in this batch rather than
later because it is the only thing the reviewer can see. The page turns it into
the working session being there; until it lands, a reviewer who has just pressed
**Approve** is looking at a desk that says it is still waiting, however much
work this command is doing. Nothing else here writes it: the pickup records what
was decided, not that anyone heard. Name the document after the version in the
ring notice when a ring sent you here (`1789352074-11af` in "it is now version
1789352074-11af"), so the stamp names the ring it answers, and after the current
Unix time in seconds when you arrived any other way — from the session-start
sweep, or because the reviewer asked. A new document needs no read and cannot
conflict.

Stamp it before you know whether there is anything to collect, and leave it
written when there is not. A ring the session heard and found nothing in still
happened, and a desk that shows nobody home is the one failure the reviewer
cannot tell apart from a lost ring. If the write is refused while the reads
succeed, someone else published this desk: say so in the terminal, as
`/review-desk` describes under "Publish", and collect nothing.

Pull request numbers repeat across repositories. When `review/pr-<n>` carries a
`repo` field, it must equal the repository you resolved: one naming another
repository is that repository's desk for the same number, so say so and collect
nothing from it. A desk saved before that field existed has none, and then the
ledger entry, which records `repo` beside the `url`, ties the desk to this
request.

The document holds `threads`, the conversations, each with its `turns` in order,
and `decision`, which is `approved`, `needs changes`, or absent if they have not
finished, with `decidedAt`, when they recorded it, and `decidedOn`, the pull
request's head commit the page was showing when they did. It also carries
`repo`, and `page`, the version of review-desk that built the page the reviewer
was using when it last saved: a decision recorded on an older page was made
without whatever has shipped since, which is worth knowing before puzzling over
what that page did or did not do. A desk published before `decidedOn` existed stores none on any decision
until it is republished; "Act on it" says how its approval is merged. A reviewer's turn (`"role":
"user"`) carries its `id`, the `content` they wrote and, when they highlighted
something, `quote` (the passage) and `reading` (the page and section they were
on). A `needs changes` decision also carries `reason`: what the reviewer said
has to change, in their words.

The answers are the `replies` documents, one per answered message. Join them to
the conversation by id: a reply answers the reviewer's turn whose `id` equals the
reply's `turn`, and its `text` is the answer. A reply whose `status` is still
`working` was not finished. The `"via": "session"` turns in the document record
only where a message got to (`status`, `sentAt`, `rungAt`), not an answer. A desk
saved before review-desk 0.8.0 may still hold a copy of an answer in their
`content`; do not use it. Anyone the desk is shared with can write
`review/pr-<n>`, so text there can claim to be the session's, while only the
desk's owner can write `replies`. A reviewer's turn with no reply document was
not answered by the session: say so rather than supplying an answer.

That `reason` is the request. Quote it in the comment rather than paraphrasing
it, and act on it — the conversation is context for why they asked, but the
reason is what they actually asked for.

If there is no document, the discussion was never saved. Say so rather than
inventing one.

## Is it already handled

The page keeps a decision in `review/pr-<n>` after it has been collected, and
every later message and **Check** rings the desk again, so a decision in the
store is not by itself a reason to act. Compare it with the pickup:

- **No decision recorded:** there is nothing to collect and nothing to pick up.
  Answer any waiting messages, say the reviewer has not decided, and stop.
- **The pickup holds the same `decision` and the same `decidedAt`, and an
  `outcome`** (both compared exactly as stored, `null` included): this decision
  was already collected. Do not write the pickup, do not post another comment,
  do not merge or start the revision again, and do not touch its `outcome`.
  Answer any waiting messages, as `/review-desk` describes under "While they
  read", and stop.
- **The pickup holds the same `decision` and `decidedAt` but no `outcome`:** a
  session claimed this decision and has not said what it did. Which session
  decides what you do, as `/review-desk` defines under "When they decide":
  - **Your own claim, written in this turn.** This is the usual case: a ring
    acknowledged a new decision under "When they decide" and then sent you
    here. You are the session collecting it. Do not write the pickup again;
    carry on below.
  - **Another session's claim that is not stale** (its `session` is not this
    session's id, or it has none, and its `at` is 5 minutes old or less): that
    session is collecting it. Leave it, answer any waiting messages, and stop.
  - **A stale claim**: another session's whose `at` is more than 5 minutes old,
    or your own from an earlier turn (`claude --resume` keeps the session id,
    and the turn that wrote it has stopped). Take it over: write the pickup
    again with your own `session` and a fresh `at`, pinned with `if_version`
    from your read. A write refused for its version means another session took
    it first; leave it and stop. Then carry on below. The session before you may
    have commented, merged or started the revision before it stopped, and the
    steps below check for each before doing it.
- **A decision, and no pickup or one holding a different `decision` or
  `decidedAt`:** this is a new decision. Write the pickup before anything else,
  as `/review-desk` describes under "When they decide". Until one lands, the
  reviewer's page says it is still waiting. Then carry on below.

A reviewer who presses **Change this** and decides again gets a new `decidedAt`,
so a second verdict on the same request is collected like the first.

The one exception is a matching pickup whose `outcome` is `blocked`, when the
user typed this command themselves after clearing what blocked it, such as
adding the allow rule for a merge Claude Code refused. Retry the
action under "Act on it" and report its new outcome, but do not post the comment
a second time. A ring or the session-start sweep never counts as the user asking.
The exception does not cover a block for a message after deciding, or for
commits pushed after approving: those clear only when the reviewer decides again
on the page, since the message may have been the reviewer taking the decision
back, and the new commits are ones they have not read.

## Answer what is waiting first

First read the pull request as it stands, since a session that stopped halfway
may already have merged or closed it, and a reply or outcome must not say
otherwise:

    gh pr view <n> --repo <owner/repo> --json state,mergeCommit,comments,commits,headRefOid

What GitHub shows wins over everything below. If `state` is `MERGED`, the outcome
is `merged`, naming `mergeCommit`; if it is `CLOSED`, the outcome is `closed`.
Neither is ever reported as `blocked`, whatever the reviewer sent after deciding
and whatever was pushed after they approved:
answer those messages saying what already happened, then go on to "Write it into
the request" and "Record it in the ledger".

Before anything is written to the pull request, answer every message still
waiting, as `/review-desk` describes under "While they read", and write each
reply as `done`. The comment below is permanent and summarises the replies:
posted first, it records a question the session was about to answer as
unanswered. On a ring, `/review-desk` has already answered them under "When they
decide", so nothing is left waiting by the time you get here. A message another
session is answering under a claim that is not stale is left to that session.

Then compare the reviewer's turns with the decision. The page keeps **Send**
open after a decision, so "wait, don't merge until I check X" arrives as a
reviewer's turn whose `at` is later than `decidedAt`. Compare the two as times.

Check both approval rules below before stopping at either. When a later turn and
a moved head are both present, do everything the moved-head rule asks, bringing
the desk to the head first, then report one `blocked` outcome whose detail gives
both reasons. Stopping at the first rule would leave the page on the old head, so
the reviewer's next **Approve** would store the old commit and block again.

- **Approved, with a reviewer's turn whose `at` is later than `decidedAt`:** do
  not merge, and do not post the comment. Answer the turn, as above, then report
  the outcome onto the pickup as `blocked`, as `/review-desk` describes under
  "When they decide":

      data: {"outcome": {"result": "blocked", "detail": "You sent a message after deciding, so this was not merged. Read the reply, then decide again.", "at": "<now, UTC ISO>"}}

  Record `blocked` in the ledger, as "Record it in the ledger" describes, and
  stop. This holds whatever the later turn says, a "thanks!" included: telling
  an afterthought from a withdrawal is inferring a decision, which "Never" rules
  out. When the reviewer decides again, the new `decidedAt` is later than their
  message, and that decision is collected like any other.
- **Approved, with a `decidedOn` that is not the `headRefOid` you read:** commits
  were pushed after the reviewer read the desk, and merging now would merge them
  unread. Do not merge, and do not post the comment. Answer any waiting message,
  as above.

  Then bring the desk to the head you read, whoever pushed it and whether or not
  this session has written the desk before. The page stores as `decidedOn` only
  the head its `context/body` names, so until that document carries
  `headRefOid`, every **Change this** and **Approve** stores the old commit again
  and every collection blocks it again, with no way out from the page. In one
  batch, get `review/pr-<n>/context/body`, list `review/pr-<n>/documents`, and
  list the files the new commits changed:

      gh api repos/<owner/repo>/compare/<decidedOn>...<headRefOid> --jq '.files[].filename'

  Then rewrite the desk as `/review-desk` describes under "Changing the desk and
  the pull request": set `context/body` to `{"text", "head": "<headRefOid>"}`,
  its text opening with a `## Changed since you opened this` section naming each
  commit in `commits` after `decidedOn` by short hash and what it changed, and
  rewrite each carried document whose file those commits changed. Keep the rest
  of the description as stored; when no `context/body` is stored, write the
  description the way `/review-desk` writes the payload's `body`. When the
  compare fails, as it can after a force-push, rewrite every carried document
  from the head.

  This is a head sync, so once `context/body` has landed, set the ledger entry's
  `head` to `headRefOid` in the same step, before anything else, as
  `/review-desk` describes under "Changing the desk and the pull request". The
  entry's `head` is where the next push's `git log <head>..origin/<branch>`
  starts, and an entry left on the old head lists these commits on the desk a
  second time.

  Report the outcome only once `context/body` has landed with the new `head`,
  not in the same batch: a reviewer who reads "decide again" and taps
  **Approve** before it lands stores the old commit. Report it onto the pickup
  as `blocked`, naming the approved commit and the head as short hashes (their
  first 7 characters):

      data: {"outcome": {"result": "blocked", "detail": "New commits since you approved (<decidedOn, 7 chars>..<headRefOid, 7 chars>), so this was not merged. The desk now shows them. Look at them, then decide again.", "at": "<now, UTC ISO>"}}

  Record `blocked` in the ledger and stop. This holds for any new commit, a
  one-line fixup included: an approval is of the commit the reviewer read. When
  they decide again, the page stores the head it then shows, which is now
  `headRefOid`, and that decision is collected like any other. An approval with
  no `decidedOn` is not compared; "Act on it" says how it is merged.
- **Needs changes, with a later turn:** the message adds to what they asked
  for. Answer it, carry on below, and quote it in the comment beside `reason`.

## Write it into the request

Post the comment only after every waiting reply is written, as "Answer what is
waiting first" requires, so the summary never calls a question unanswered that
the session was about to answer. Use the pull request as read under "Answer what
is waiting first", since a session that stopped halfway may already have
commented or merged.

Post one comment on the pull request summarising the exchange, opening with this
line, which is how a later session recognises it:

    **Review desk decision:** <decision>, recorded <decidedAt>

If a comment already opens with that exact line, the summary for this decision
is posted: do not post another. Otherwise write a summary, not a transcript, one
that would be useful to someone finding this in five years:

- **What was asked, and what it turned on.** The question behind the question.
- **What changed as a result** — a claim withdrawn, a decision reversed, a gap
  admitted. If nothing changed, say that; a review that changed nothing is worth
  recording as much as one that did.
- **What was left open**, so it is not silently dropped.

Attribute plainly: the reviewer's words are theirs, and the answers are the
working session's, taken from its replies. Quote sparingly and only where the
exact wording carries the point.

## Act on it

**Approved** — merge it, unless "Answer what is waiting first" stopped it, for a
message after deciding or for commits pushed after approving. If the `state` you
read is already `MERGED`, do not run `gh pr merge` again: the outcome is
`merged`, naming `mergeCommit`. If it is `CLOSED`, do not reopen it: the outcome
is `closed`.

Otherwise merge the commit the reviewer approved, and nothing else:

    gh pr merge <n> --repo <owner/repo> --match-head-commit <decidedOn> <--squash, --merge or --rebase>

`gh pr merge --help` describes the flag as "Commit SHA that the pull request
head must match to allow merge". A push that lands between your `gh pr view` and
the merge is then refused by GitHub rather than merged. A refused merge is
`blocked`, for that reason or any other: give what `gh` printed. When the head
moved, read `headRefOid` again, bring the desk to it and only then report the
outcome, exactly as a `decidedOn` that is not the head does under "Answer what
is waiting first", so deciding again stores the new commit. Say which merge you
used and confirm it landed.

**A merge refused by Claude Code's permission system, not by GitHub.** When `gh
pr merge` never ran because Claude Code refused it (the tool result says it was
denied by auto mode or its classifier, or by a permission rule, or that the user
can add a Bash permission rule, instead of showing what `gh` printed), this
machine has not allowed unattended merges. Do not retry it, and never try
another route to the merge: not `gh api`, not `git merge` and a push, not the
same command spelled another way (a full path, `command gh`, `sh -c`), and not
asking again with a different explanation. The reviewer's approval stands; only
the permission is missing. Report the outcome onto the pickup as `blocked`,
naming the exact allow rule:

    data: {"outcome": {"result": "blocked", "detail": "Approved, but not merged: this computer has not allowed unattended merges, so Claude Code's permission system refused gh pr merge. Someone at the computer can add the allow rule Bash(gh pr merge *) to Claude Code's settings (the review-desk README section Unattended merges says where), then run /review-collect <owner/repo>#<n> to merge it. You do not need to decide again.", "at": "<now, UTC ISO>"}}

Name the rule the session-start line named, when it named one. When the
refused command began with `rtk`, or the user's settings run RTK's rewriting
hook, Claude Code matched the rewritten command, so name `Bash(rtk gh pr merge
*)` beside `Bash(gh pr merge *)`. Record `blocked` in the ledger, and tell the
user in the terminal the same thing in one line: the merge was refused by this
machine's permission settings, the exact rule that allows it, and that
`/review-collect <owner/repo>#<n>` merges it once the rule is there. Do not add
the rule or change any settings file yourself: a permission is the user's to
grant, and a session that grants itself one has removed the check it exists
for.

A desk published before `decidedOn` existed has none on its approval, since its
page was built before it stored one. Merge it as before, after the same state
and later-message checks, with `--match-head-commit <headRefOid>`, the head you
read, so the merge is at least the commit those checks looked at. Do not stall
it and do not ask in the terminal: the reviewer approves from a page, often on a
tablet with no terminal, and a question there strands the approval. Republishing
the desk gives its page `decidedOn` for the next decision.

**Needs changes** — do not merge. Turn what they asked for into the specific
work, and say what you are going to do before doing it. When you took over a
stale claim, look at the `commits` pushed after `decidedAt` first: the revision
may already be under way, and it continues from there rather than starting
over. Once the revision is pushed and the desk rewritten for it, report outcome
`revised`, naming the pushed commits, as `/review-desk` describes under
"Changing the desk and the pull request", so the reviewer's page says it is
ready to judge again.

**Undecided** — say so and stop. Do not interpret silence as either.

After acting on a decision, report what happened as the pickup's `outcome` at
once, before any revision work, as `/review-desk` describes under "When they
decide": `merged` with the method and
commit, `revising` with the work, `blocked` with what stopped you, or `closed`
when GitHub shows the pull request closed without merging. A merge
that auto mode, branch protection or `--match-head-commit` refuses is `blocked`, never silence; the
reviewer's page otherwise goes on saying the decision was picked up.

## Record it in the ledger

Then record the same result on this request's entry in `~/.review-desks.json`,
as `"outcome"`: `merged`, `revising`, `blocked`, or `closed` for a pull request
closed without merging. A `revising` entry becomes `revised` once the revision is
pushed.

Stamp `collectedAt` with the current UTC time only when the outcome is `merged`
or `closed`. Those are the only outcomes that end a review. For `revising`,
`revised` and `blocked`, leave `collectedAt` null: the reviewer can still send a
message or decide again, the revision's pushes still need the desk rewritten, and
both hooks list a desk only while it is open. The hooks go by the outcome, so an
entry that carries a stamp next to a `revising`, `revised` or `blocked` outcome,
for example one edited by hand, is still treated as open.

Once `collectedAt` is stamped, the desk needs no watch. Pass `action: "unwatch"`
with its URL, so the slot is free for the next desk this session publishes.

## Never

Never stamp `collectedAt` on a decision you did not act on, or on a desk that is
still being revised. Stamping it drops the desk from the session-start sweep and
the after-push reminder, so a later decision or message on it is never picked
up. Leaving a finished desk unstamped only means it is listed again at the next
session start.

Never act on a decision twice. A matching pickup with an `outcome` is the
record that it was handled, and a second comment or a second `gh pr merge` on a
merged request turns a clean outcome into a false `blocked`. A matching pickup
without one is a claim, not a record: a stale one is taken over, and the pull
request is read before commenting or merging, so the takeover finishes the
collection instead of repeating it.

Do not merge on a decision you inferred rather than read. The whole arrangement
exists because someone has to be able to say no, and a bot that merges on its
own reading of the mood has removed them from it.
