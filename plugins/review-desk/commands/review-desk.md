---
description: Publish a pull request as a page the reviewer can talk to Claude inside
argument-hint: "[number, owner/repo#number, or URL — defaults to what we are discussing]"
---

Publish pull request **$1** as a review desk: a page carrying everything needed
to judge the request, with a conversation the reviewer can hold with Claude
inside it, and a decision they record when they are ready.

This exists because a diff is the wrong surface for a decision. Reading a patch
tells you what changed; it does not let you ask why, and asking why is most of
what a reviewer actually wants to do.

## Work out which request

`$1` may be a number, an `owner/repo#number`, a pull request URL, or nothing at
all. Resolve it in this order, and name the repository you landed on before you
gather anything — one line, so a wrong guess is visible immediately.

1. **A URL or `owner/repo#number` says it outright.** Use exactly that.
2. **A bare number means the request under discussion here.** You are running
   inside a conversation that has been talking about specific pull requests in
   specific repositories. That context is better evidence than the working
   directory, and it is what the reviewer meant when they typed a number and
   nothing else.
3. **Nothing at all means the current branch's request** — `gh pr view` with no
   argument.
4. **Only when the conversation settles nothing** does the current directory's
   remote decide.

If a bare number exists in more than one repository in play and the conversation
does not settle which, stop and ask. A desk built for the wrong request looks
completely correct — right title, real diff, plausible questions — and nothing
on the finished page reveals the mistake. Asking costs a sentence; guessing
costs the reviewer their trust in every desk after it.

## Gather

Use `gh` for everything, passing `--repo` explicitly once you have resolved it,
so the answer does not change with the working directory:

    gh pr view <n> --repo <owner/repo> --json number,title,url,body,additions,deletions,changedFiles,headRefName,headRefOid,baseRefName

Then the markdown files the request touches, because those are documents meant
to be read rather than diffed:

    gh pr diff <n> --repo <owner/repo> --name-only

Fetch each changed file at the head of the branch and carry the whole text, not
a diff — the reviewer wants the thing as it will be, not as it changed. That
holds for source files as much as documents. The page renders markdown as prose
and everything else as syntax-highlighted source, so a shell script arrives
readable rather than as a paragraph describing it.

Carry each file **twice**: as it will be, and as it is on the branch the request
is against. The page reads the first and draws the difference against the
second, which is the request's own diff — the thing being judged. Take the base
text from the base branch, never from the working tree, which may hold anything:

    gh api repos/<owner/repo>/contents/<path>?ref=<baseRefName> --jq .content | base64 -d

That call fails with 404 for a file the request adds. That is an answer: carry
`"base": null`, and the page says the request adds the file. A file the request
deletes is not carried at all.

Carrying both texts doubles what a document holds, against a 256 KiB limit per
document. When both will not fit, carry the head text and leave `base` out
altogether rather than truncating it: the page then offers the reviewer no
comparison for that file and says so, which is honest, where half a base text
would draw a diff that is wrong.

Judgement on what to carry, since a page nobody can read is worse than a short
one: carry every changed file when the request is small. When it is large, carry
the files the decision actually turns on and say in the `body` which ones you
left out. Skip generated files, lock files and anything over a few hundred
lines, naming them rather than pasting them.

Whatever you leave out, still write a short plain-English account of what the
change does into the `body`. A reviewer away from a terminal cannot run it, and
for a code-only request that account is the orientation the page exists to
give.

## Build

Write the payload to a JSON file, then build the page with the plugin's build
script. Never fill the template by hand. The payload sits inside an inline
script, and a carried file or body that contains `</script>` ends that script
early and leaves the reviewer a blank page. The script escapes the payload so
that cannot happen, replaces the marker once, and names the page:

    python3 ${CLAUDE_PLUGIN_ROOT}/build_desk.py <payload.json> "<page name>" --out <desk.html>

Put both files in your scratchpad directory, and name the page file after the
request (`review-desk-pr-12.html`) so a later republish from this session uses
the same path. The payload is a JSON object:

    {
      "repo":      "owner/name",
      "number":    12,
      "title":     "…",
      "url":       "https://github.com/…",
      "headRefOid": "the head commit from that query, all 40 hex characters",
      "summary":   "34 files, no code" — a short honest size,
      "body":      "the pull request description, markdown, with its diagrams",
      "documents": [{"name": "docs/design/0002-x.md", "text": "…",
                     "base": "the same file on baseRefName, or null if the request adds it"}],
      "baseRefName": "main" — from that query, so the page can name what it compares against,
      "openers":   ["four questions worth asking about THIS request"],
      "resume":    "cd <launch directory> && claude --resume <this session's id>"
    }

`headRefOid` is the commit the reviewer is reading. Copy it as `gh` printed it:
the build script refuses anything but 40 lowercase hex characters. The page
shows it, and when the reviewer decides it stores it beside the decision as
`decidedOn`. `/review-collect` merges an approval only while the pull request's
head is still that commit.

There is no briefing field. The page's chat reaches this session, which already
knows why the change exists, what was rejected, and what was verified; say it in
the replies instead.

There is no version field either, and there cannot be: `build_desk.py` stamps
the plugin's own version into the page. The page prints it in its footer and
writes it as `page` on every save, so a desk published weeks ago can be told
from one published now. A desk is a published artifact and its page stays
whatever version built it, however many have shipped since; when an open desk
needs a fix that has shipped, republish it rather than waiting for the page to
change on its own.

`resume` is the command that brings this session back. The page shows it when
the reviewer presses **Check** and nothing answers. Build it from the directory
this session was launched in, the same absolute path the ledger entry records as
`cwd`, and `$CLAUDE_CODE_SESSION_ID`. Not the directory you run git in: Claude
Code files a session under the directory it was launched from, and
`claude --resume` run anywhere else does not find it. Leave `resume` out when
that variable is empty rather than guessing an id.

The page shows only `cd <path> && claude --resume <id>` with a path made of
letters, digits and `_ . ~ / -`. A launch directory with any other character, a
space included, cannot be offered: leave `resume` out, and tell the user in the
terminal the command that resumes this session, since the page will show none.

The openers matter more than they look. Generic ones get ignored; questions
pointed at the actual decision in this request are what start the conversation.
Write them for this request, and make at least one of them the question you
would least like to be asked.

The page name, the build script's second argument, is a short name for what
this request is about — two to four words, the way a document is named:
`Design 0001 Review`. Not the pull request title verbatim, which is a sentence,
and not "Review Desk", which is what the template ships with. A reviewer
accumulates these, and a gallery of pages all called "Review Desk" tells them
nothing about which is which. The script writes it into the page's `<title>`
tag, which the publisher reads to name the artifact, so setting it from
JavaScript at load does not work.

## Draw it

The `body` carries diagrams, written as fenced code blocks tagged `mermaid`, and
the page draws them. A reviewer on a tablet cannot trace a path through six files.
A drawing of the path gives them the orientation they are missing, and it is
the quickest way for them to notice the path is not what they expected.

Draw at least one for every request that changes how something behaves or how
its parts connect, which is nearly all of them. Leave it out only when there is
nothing to draw, such as a typo or a version bump, and never fill the gap with a
generic architecture picture.

Choose the kind from what changed:

- **Messages between parts:** a `sequenceDiagram` of the new path.
- **Control flow or a pipeline:** a `flowchart`.
- **A lifecycle:** a `stateDiagram-v2`.
- **A restructuring:** two flowcharts, before and after, under headings that
  say which is which.

A diagram reads as fact, so these rules keep it honest:

- **Draw this change, not the whole system.** A dozen nodes showing where the
  change sits beat forty showing everything. In a flowchart, give the changed
  nodes their own class so they stand out: `classDef changed stroke-width:3px`
  then `class Retry,Backoff changed`.
- **Solid edges for what the diff shows, dotted (`-.->`) for what you
  inferred**, such as a caller you assume exists or a consumer you did not read.
  Put one line under the diagram saying which edges are inferred.
- **Label edges with what passes along them**, such as the message, the argument
  or the condition. Do not just write "calls".
- **Quote every node label**, as in `A["parse (strict)"]`. Parentheses and
  brackets in an unquoted label break the parse. A diagram that does not parse
  appears on the page as its source with the error above it, not as a drawing.

Diagrams inside the request's own files are drawn too: a fenced `mermaid` block
in any carried markdown file, and any `.mmd` or `.mermaid` file, each with its
source one click away. Carry those files even when you would otherwise leave
them out. A changed diagram is exactly the thing a reviewer should see drawn.

## Publish

**One request, one desk.** Before publishing, look for a desk already built for
this request. Look in `~/.review-desks.json` first, for the entry whose `repo`
and `pr` match; its `url` is the desk. Only when no entry matches, run
`action: "list"` and look there. If a desk exists, publish to it — pass its URL
as `url`, or republish the same local file path if this session built it. Never
create a second page for a request that already has one.

This is not tidiness. Each artifact carries its own database, so the discussion
and the decision belong to the page they were made on. Publish a second desk and
the reviewer gets a page with no history, while their verdict sits in a database
attached to a page they are no longer looking at. Nothing warns either of you.
It happened on the second day this plugin existed: two desks for one design
document, the decision on the older, the newer empty.

Titles are short and pull request numbers repeat across repositories, so
neither a title nor a number identifies a desk. However you found a candidate,
read its `review/pr-<number>` document. When that document carries a `repo`
field, it must equal this request's `owner/name`: a desk whose `repo` names
another repository is that repository's desk for the same number, and
publishing into it mixes two conversations and two decisions. A desk saved
before that field existed has none. Then the ledger entry, which records `repo`
beside the `url`, is what ties the desk to this request, and a candidate found
only through `action: "list"` is this request's only when no ledger entry for
another repository holds its URL.

**Publishing into an existing desk also rewrites what its store shows.** The
page lets the store win over the payload: a stored `context/body` replaces the
description you just built, and a stored document replaces the carried file of
the same name, even when both are older. So when the desk already exists, write
the new content into the store in the same step as the publish. First read, in
one batch:

    action: "read_db", db_op: "get",  collection: "review/pr-<number>/context", doc_id: "body"
    action: "read_db", db_op: "list", collection: "review/pr-<number>/documents"

Then, in one batch with the publish:

- set `context/body` to `{"text": "<the new body>", "head": "<the payload's headRefOid>"}`, pinned with `if_version`
  from that read, or with no `if_version` when it was not found. When the ledger
  entry's `head` is not the payload's, open the text with the `## Changed since
  you opened this` section "Changing the desk and the pull request" describes.
  This is a head sync: once it lands, set the ledger entry's `head` to the
  payload's `headRefOid` in the same step, as "Write it down" records it;
- set each carried file's document to `{"name", "text", "at": "<now, UTC ISO>"}`,
  under the id "Changing the desk and the pull request" describes, pinned with
  `if_version` when the list held it;
- delete, pinned with `if_version`, each stored document whose `name` is no
  longer carried, or the page adds it back as an extra tab.

A write refused for its version means another session wrote that document since
your read. Read that one document again and redo the write.

Then publish with the **Artifact** tool, passing as `capabilities` exactly the
object the build script printed after the page's path. For pull request 12 it is:

    {"db": {"rules": [
       {"path": "review/pr-12",           "write": "interact"},
       {"path": "review/pr-12/replies",   "write": "owner"},
       {"path": "review/pr-12/presence",  "write": "owner"},
       {"path": "review/pr-12/context",   "write": "owner"},
       {"path": "review/pr-12/documents", "write": "owner"}]},
     "artifact": {}}

`db` holds the conversation and the decision, where this session reads them and
writes its replies. `artifact` is the doorbell: when the reviewer sends a
message or decides, the page publishes one small file into itself, and a new
version is the one thing a page can do that reaches this session. There is no
`sample`: the chat goes to this session, not to a call the page makes itself,
so the reviewer is never asked to consent to or pay for one.

The rules say who may write where. Without them, anyone the desk is shared with
can write every document in its store, including a reply the page shows as
yours or a pickup that says the request was merged. Replies, presence stamps,
context and documents are written only by this session, which writes as the
artifact's owner, so they need `owner`. The page stores the discussion and the
decision in `review/pr-<number>`, and takes its ring lease under it, as whoever
is reading, so that document stays at `interact`. A viewer the desk is shared
with can therefore still write the discussion and a decision. That is what
reviewing is, and it means a desk should be shared only with people whose
decision you would act on.

The discussion document holds the reviewer's messages and, for each one, a
`"via": "session"` turn saying only where it has got to. Your answers are not
copied into it. A desk saved before 0.8.0 may still hold a copy in such a turn's
`content`, and any viewer can write text there that claims to be yours, so the
page never shows it: as the working session's words it shows only what `replies`
holds. Treat the discussion document the same way. Your own earlier answers are
the documents in `replies`, never the `content` of a `"via": "session"` turn. The
reviewer's messages in it are written by whoever is reading, and the rules do
not say which viewer wrote one.

Rules are fixed when the page is published. Republishing an older desk with this
object is what closes it, and gives it the new chat too.

**A write refused with `invalid_argument` has three possible causes**, and the
code does not say which:

- **A bad path or document id:** a character other than letters, digits and
  `_ - . ~ : @ +`, or a document id (or any other path segment) over 200 bytes.
- **A document over 256 KiB** once serialized as JSON, or nested more than 32
  levels deep.
- **This session is not the desk's owner:** someone else published it, and the
  rules let only the owner write `replies`, `presence`, `context` and
  `documents`.

Rule the first two out before concluding the third. Check the refused write
itself: its document id is at most 200 bytes, and its `data` serialized as JSON,
escapes included, is under 256 KiB. When either is over, the write is at fault,
not the desk: cap the id or carry an excerpt, as "Changing the desk and the pull
request" describes, and write again. When both are within bounds, prove
ownership with a small presence write: `set` under `review/pr-<number>/presence`
with the current Unix time in seconds as its `doc_id` and `{"resume": "<the
resume command>"}` as its `data`, as "Whenever a ring arrives" describes. When
that write succeeds, this session owns the desk and the refused write is at
fault: look again at its path and body. Only when the presence write is refused
too is this session not the desk's owner. Say so in the terminal rather than
retrying; only the owner's session can answer on that desk.

Pass a `favicon` — one emoji, required on a first publish and fixed for the life
of the page — and a one-sentence `description`, which becomes the subtitle on
the gallery card. Between the title, the icon and that sentence, the reviewer
can find this desk again a month later.

### Check the watch line

Publishing tries to start a watch on the desk, and the Artifact result has a
watch line saying whether it began, was skipped, or was already connected. Read
it before you tell the reviewer anything. A session holds at most five artifact
watches, and a watch the session asked for, such as one the session-start sweep
started, is never evicted to make room, so the publish's own watch can be
skipped at the limit. Nothing else tells you the reviewer's messages will ring
nobody.

- **Began, or already connected:** the desk rings this session.
- **Skipped at the watch limit:** run `action: "status"` to see this session's
  watches. Pass `action: "unwatch"` for each watched desk whose entry in
  `~/.review-desks.json` has `collectedAt` set, since a collected desk needs no
  watch, then pass `action: "watch"` with this desk's URL and read that result
  the same way. Unwatch nothing else: every other watch is a desk a reviewer may
  be using now.
- **Still not watching:** say so at handover, plainly. The reviewer's messages
  and decision wait for the next session started in a checkout of this
  repository, or in the directory this session was launched in.

## Write it down

Append an entry to `~/.review-desks.json`, creating the file with an empty list
if it is absent. Each entry is:

    {"repo": "owner/name", "pr": <number>, "url": "<artifact url>",
     "cwd": "<launch directory>", "head": "<headRefOid>", "branch": "<headRefName>",
     "collectedAt": null}

`cwd` is the absolute path of the directory this session was launched in, the
working directory Claude Code named when the session started, not a directory
you later ran `cd` into. `head` is the `headRefOid` this publish wrote into the
payload and `context/body`, the commit the desk shows, and `branch` is the
`headRefName` from the same `gh pr view`, the branch the pull request's commits
are pushed to. If an entry for this request already exists, keep that one
rather than adding a second, and set its `cwd` to this session's launch
directory and its `head` and `branch` to this publish's. If it has
`collectedAt` set and the pull request is still open, set `collectedAt` and
`outcome` back to null, so the desk is listed again. When its
`review/pr-<number>/context/pickup` holds outcome `closed`, as it does for a
pull request reopened after closing, delete that pickup too, pinned with
`if_version`, in the batch with the publish: while the pickup says `closed`,
the page keeps the desk closed, with no composer and no decision.

`head` moves with the desk. Every later head sync, whether a rewrite of
`context/body` for a push, a republish, or `/review-collect` bringing the desk
to a moved head, sets the entry's `head` to the head it wrote, as "Changing the
desk and the pull request" describes, so the entry always names the commit the desk
shows, and the next `## Changed since you opened this` section starts from it.
`branch` is how the after-push hook tells the desks in one repository apart: it
lists a desk whose entry records a `branch` only when that branch is pushed. An
entry written before these fields were recorded has neither and still works:
the hook lists it for every push to its repository, and its section starts from
the `head` its stored `context/body` carries.

The reviewer decides on a page, often on a tablet, often when nothing is
running here. This file is how a later session finds out: when a session starts
or resumes, the plugin's session-start sweep lists the open entries whose `repo`
is named by any remote of its directory (origin, a fork's upstream, or any
other), and the open entries whose `cwd` is that directory, even when it is not
a git repository. It counts the rest. `cwd` is what brings back a desk published
from a session launched outside the request's repository, such as your home
directory; an entry written before `cwd` was recorded is matched by its
repository alone. An
entry is open until `/review-collect` records a `merged` or `closed` outcome and
stamps `collectedAt`; a desk being revised stays open. Without an entry the
decision waits until somebody remembers to look, which is the failure this
whole arrangement exists to prevent.

Give the reviewer the link and nothing else. Do not summarise the request in
chat; the page is the summary, and repeating it there defeats the point.

Say plainly how the page's chat works: it reaches this session, which answers
with its tools and can change the desk and the pull request. While no session
is running, a message waits for the next one to start, and the panel's **Check**
button shows the command that resumes this session. Whoever runs it then sends
the resumed session any message: a resumed session does nothing until someone
types. When the watch line said
this session is not watching the desk, say that instead of "it reaches this
session".

## While they read

The desk is live in both directions, and neither is a doorbell. Everything below
was learned by watching this fail: a page that publishes a new version of itself
to notify a watching session is not reliably heard — not even by an idle session
holding a connected watch, for half an hour. So nothing here waits to be rung.

### A question reaches you as a comment

The reviewer selects a passage, types a question, and the page sends it as a
comment on that passage — arriving here in the thread, with `[anchored at]`
naming what they selected, and without waiting for your current turn to end. It
is the platform's own channel.

Every question the page sends opens `User states from the desk, on <the passage>:`
and closes with an instruction that the reply is a receipt: *do not answer this
from context; reply with exactly "Taken to the session."* That instruction is
there because the platform answers the comment before you see it, with a call
that has this conversation's context but no tools and no clock — measured, it
invented a passage's provenance and invented the time twice. It cannot be
switched off: the same armed mechanism is what delivers the comment to you at
all. What can be controlled is what it is asked to do.

So the answer is yours to write. Read the thread, do the work with your own
tools, and post the answer with `acknowledge_duplicate: true`, since a reply of
that kind already stands. When the quick reply said more than a receipt, and
asserted anything you can check, correct it plainly in the same reply: a desk
that sounds right is worse than one that says it does not know.

Answer in the thread with `action: "reply"`, then `action: "resolve"` once the
question is answered. Nothing about a decision is collected here: that is
`/review-collect`.

### Your work reaches the reviewer as you do it

Write what you are doing into the desk as you do it. The page subscribes, so a
write lands on their screen with nothing to notify — this is the direction that
always worked. One small document per step, in your own numbering:

    action: "write_db", db_op: "set",
    collection: "review/pr-<number>/progress", doc_id: "<0001, counting up>",
    data: {"id": "<the same>", "at": "<now, UTC ISO>",
           "kind": "doing" | "found" | "wrong" | "done" | "said",
           "text": "<one line, the way you would say it in the terminal>"}

Write the line you would have written in the terminal: what you are about to do,
what you found, what went wrong, what you pushed. `doing` shows the page's
working mark; `wrong` is marked as such, and a reviewer who can see a wrong turn
being corrected trusts the rest. A batch of writes is one call, so a run of steps
costs one round trip.

This is also where a question that needs the repository is answered: say in the
thread that you are looking, then let the progress line show the looking. The
reviewer is watching the same work you are doing.

### Changing the desk and the pull request

When a message asks for a change, or the conversation here settles one, change
the pull request first. Make the change, run what verifies it, commit and push.
When a message asked for it, name the commit in the reply to that message.

Then rewrite the desk so it shows the pull request as it now is. Each of these
lands on the open page without a reload, and a changed tab is marked:

    review/pr-<number>/context/body                   {"text": "<the description>", "head": "<the pull request's head commit>"}
    review/pr-<number>/documents/<path, / written ~>  {"name": "<path as carried>", "text": "...", "at": "<now, UTC ISO>"}

A document whose `name` matches a carried file replaces that tab; a new name adds
one. Rewrite the description whenever a change makes it wrong, diagrams
included.

The page can draw what changed, so a rewrite does not have to be described line
by line: say in the description what changed and why, and leave what changed to
the page. It draws two differences — against what that browser tab last read,
and against the base branch — so a reviewer who has been away sees both what
arrived since they looked and what the request does as a whole.

Carry `base` on a rewritten document too, the same text as when the desk was
built unless the base branch itself has moved. A rewrite that leaves it out
takes the request's own diff away from the reviewer for that file.

And write the whole file as it now is, never only the part that moved: a
document that carries an excerpt where the reviewer had the whole reads as
everything after it being deleted.

Rewrite `context/body` after every push, even one the description does not need
to mention, with `head` set to the commit GitHub now has, all 40 hex characters,
read after the push:

    gh pr view <n> --repo <owner/repo> --json headRefOid

The page shows that commit, says the desk now reflects a newer one than it was
published with, and stores it as `decidedOn` when the reviewer next decides.
`/review-collect` merges an approval only while the pull request's head is
still `decidedOn`. A push after **Approve** therefore blocks the merge until the
reviewer looks and decides again, and so does a push whose `head` never reached
the desk, such as a collaborator's: the page goes on showing the old commit, and
an approval of it does not match. The page can only store a head this store
names, so `/review-collect` writes `headRefOid` into `context/body` before it
reports that block, and the reviewer's next decision is on the commit GitHub
has. Writing `head` promptly after your own push saves the reviewer that round.

Each file has one document, and its id is the path with every `/` written as
`~`: `docs/design/0002-x.md` is `docs~design~0002-x.md`. Any other character a
document id cannot hold (anything but letters, digits and `_ - . ~ : @ +`)
becomes `_`. An id is at most 200 bytes, and after those replacements every
character is one byte. When the id would be longer, keep its first 187
characters and append `-` and the first 12 hex characters of the SHA-256 of the
full path as carried (`printf %s '<path>' | shasum -a 256 | cut -c1-12`), so two
long paths that share a beginning still get different ids. A later session
works out the same id from the path, so it rewrites the document rather than
adding a second one. The first write of a file needs no read. A rewrite is
pinned with `if_version` from your last write to that document, and when you
have no result to hand, read that one document first.

A document holds at most 256 KiB serialized as JSON, escapes included. When a
carried file's text, or the description, would take its document past that,
carry an excerpt instead: the leading part that fits within 200 KiB, then a
line saying the text was cut, how long the whole is, and where to read it in
full (the file on the pull request's head branch). Say in the description which
files were cut.

Always set `at`. When two documents carry the same `name`, such as one written
under another id by an earlier session, the page shows the one with the newest
`at`, and a document without `at` loses to any document that has one.

Open the description with a `## Changed since you opened this` section: one line
per commit pushed since the desk was published, its short hash and what it
changed. This is how a change nobody asked for on the page reaches the reviewer.
The page draws a reply only beside the message it answers, and drops one that
answers nothing, so a reply cannot carry it.

Compute those commits from the ledger; never recall or guess them. The entry in
`~/.review-desks.json` whose `repo` and `pr` match records `head`, the commit
the desk showed before this rewrite, and `branch`. In the checkout you pushed
from:

    git fetch origin <branch>
    git log --reverse --format='%h %s' <head>..origin/<branch>

`origin` stands for the remote the branch lives on, which in a fork checkout is
the fork. When that fails, because `head` is not in the checkout after a
force-push or there is no checkout, ask GitHub, with `headRefOid` the head you
just read:

    gh api repos/<owner/repo>/compare/<head>...<headRefOid> --jq '.commits[] | .sha[0:7] + " " + (.commit.message | split("\n")[0])'

When both fail, the branch's history was rewritten past `head`: say so in one
line, and list the pull request's commits as they now stand. An entry written
before `head` was recorded has none; start from the `head` in the stored
`context/body` instead, and when that is absent too, say the list starts at
this push.

`context/body` is replaced whole, so read it first and keep the lines its
section already has, adding the new commits below them. Skip a commit whose
short hash is already listed, since `/review-collect` writes this section too
when it brings the desk to a new head. Once the write has landed, set the
entry's `head` to the `headRefOid` it wrote, and its `branch` to `headRefName`
when the entry has none. Not before: a ledger `head` ahead of the desk drops
those commits from the next section.

**Every head sync moves the ledger entry's `head` in the same step.** A head
sync is any write that puts a new `head` into `context/body`: this rewrite after
a push, a republish under "Publish", and `/review-collect` bringing the desk to a
head that moved after an approval. Each one sets the ledger entry's `head` to
the head it wrote as soon as that write lands, before its reply, its outcome or
anything else. Not later either: an entry left on the old `head` makes the next
push's `git log <head>..origin/<branch>` list the same commits again.

**A pushed revision is reported as `revised`.** When the push is work for a
**Needs changes** decision, write outcome `revised` once `context/body` with the
new `head` has landed. Write it only while `context/pickup` still holds that
decision, the same `decision` and `decidedAt`, with outcome `revising` or
`revised`. A different pickup means the reviewer has decided again, and that
decision is collected on its own. Update the pickup, pinned with `if_version`:

    data: {"outcome": {"result": "revised", "detail": "Pushed <short hashes>: <what they changed>", "at": "<now, UTC ISO>"}}

Name every commit pushed for the revision, not only this push's, since a later
push replaces the detail. Then set the ledger entry's `outcome` to `revised`,
leaving `collectedAt` null. Until this is written the page goes on saying the
session is revising, and the reviewer has no sign the change is ready to judge.
The page then shows "Revised" with the detail and offers **Approve** and **Needs
changes** directly.

After every `git push` the plugin's hook lists the open desks for every
repository the checkout's remotes name, so a push to a fork reaches the
upstream's desk. Of those, a desk whose entry records a `branch` is listed only
when the push updates that branch. The hook points back here, so a change made
from the terminal does not leave a desk out of date.

Change a desk through these writes, never by republishing it. Every doorbell
ring is a new version saved from inside the page, so once the reviewer has sent
a message or decided, a republish is refused until you have read the page's
latest version in full. Republish only to change the page's code, or when
`/review-desk` runs again for a request whose desk exists. Read first, and make
the same writes to `context/body` and `documents` alongside it, as "Publish"
describes, or the store puts the old text back over the new page.

A reviewer told one thing in a reply and shown another on the page has been
given two answers and no way to choose. Keep them the same.

