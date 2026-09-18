---
description: Answer every message waiting on a review desk, and nothing else
argument-hint: "[owner/repo#number, or nothing for every open desk here]"
---

Answer what the reviewer has asked on the desk for **$1**, and stop. No comment
is posted, no pull request is merged, no decision is collected.

This command exists because "check the desk" had no command. `/review-collect`
answers waiting messages on its way to collecting a decision, but it is decision
machinery: asked in prose to go and look, a session improvises, and a reviewer
who is sitting there watching gets nothing. One thing, named, doing only that.

It is also the body of the poll. The desk's doorbell — the page republishing
itself to notify a watching session — is lost often enough to be useless, so
what actually serves a desk is this command on a timer, `/loop 1m
/review-answer`, as `/review-attend` sets up. Everything below is written to be
run once a minute: cheap when nothing is waiting, and silent.

## Which desk

`$1` is `owner/repo#number`, or a pull request URL. With no argument, every open
entry in `~/.review-desks.json` whose `repo` is named by a git remote of this
directory, or whose `cwd` is this directory — the same desks the session-start
sweep lists. Name each repository in full as you go: the same number is often a
pull request in another repository too.

Nothing in the ledger and no argument: say so and stop. Do not go looking
through `action: "list"` for a desk nobody named.

## Read it, and say you are here

In one batch per desk — the reads and the stamp together:

    action: "read_db",  db_op: "get",  collection: "review", doc_id: "pr-<n>"
    action: "read_db",  db_op: "list", collection: "review/pr-<n>/replies"
    action: "read_db",  db_op: "get",  collection: "review/pr-<n>/context", doc_id: "pickup"
    action: "write_db", db_op: "set",  collection: "review/pr-<n>/presence",
        doc_id: "<the current Unix time in seconds>",
        data: {"resume": "<the resume command for this session>"}

The stamp is what the reviewer sees. A desk that says nothing while a session
works on it is indistinguishable from a desk nobody heard, and that is the
complaint this plugin keeps earning.

**On a poll, stamp only when it is worth something**: when something was
waiting, or when the newest stamp already there is more than five minutes old.
A stamp a minute is a document a minute in a collection nobody prunes, and it
tells the reviewer no more than one every five minutes does. On a ring, stamp
always, named after the version in the notice.

When `review/pr-<n>` carries a `repo` field that is not the repository you
resolved, this is another repository's desk for the same number: say so and
answer nothing on it.

## Claim everything waiting, before any work

A message waiting on you is a turn with `"to": "session"` that has no reply
document, or one whose `status` is `working` and is a stale claim — another
session's more than 5 minutes old, or your own from an earlier turn.

Write a claim for **every** waiting turn now, in one batch, before reading a
file, running a test or thinking about an answer:

    action: "write_db", db_op: "set",
    collection: "review/pr-<n>/replies", doc_id: "<the turn's id>",
    data: {"turn": "<the turn's id>", "status": "working", "text": "",
           "session": "<this session's id>", "at": "<now, UTC ISO>"}

The page turns each claim into a thread that says the session is writing. Claims
written with the answer, in one write at the end, leave the reviewer watching a
silent desk for as long as the work takes: on `LiLo-Labs/accrue#11` that was
twenty-five minutes, three times over.

## Answer

Each message carries `quote`, the passage they highlighted, and `reading`, the
page and section they were on. Answer the question they asked about that
passage, not the one it resembles.

Answer from what you can reach: this repository, its tests, its history, the
web. When the answer turns on what another session knows — why a thing was built
this way, what was rejected, what was tried and failed — ask that session
without waiting for it, as "Asking the working session" describes in
`/review-attend`.

Set the same document again, `"status": "done"`, with the answer as `text`,
pinned with `if_version` from the claim you just wrote. Markdown, and as long as
it needs to be: the page renders it.

## What this command does not do

- **It never collects a decision.** A recorded decision waiting in the store is
  reported in the terminal, naming the desk in full and pointing at
  `/review-collect <owner/repo>#<number>`. Collecting comments on the pull
  request and can merge it; that is not something to do because someone asked
  whether a desk had anything on it.
- **It writes nothing to the pull request**, and it does not touch
  `~/.review-desks.json`.
- **It does not wait.** Everything waiting when you read is answered; a message
  that arrives afterwards rings whichever session is watching.

Say in one line what you answered, per desk, and name any decision waiting.
**Nothing waiting, nothing to say**: end the turn with no line at all, so a poll
running every minute leaves a terminal someone can still read.
