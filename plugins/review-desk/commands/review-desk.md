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

    gh pr view <n> --repo <owner/repo> --json number,title,url,body,additions,deletions,changedFiles,headRefName,baseRefName

Then the markdown files the request touches, because those are documents meant
to be read rather than diffed:

    gh pr diff <n> --repo <owner/repo> --name-only

Fetch each changed file at the head of the branch and carry the whole text, not
a diff — the reviewer wants the thing as it will be, not as it changed. That
holds for source files as much as documents. The page renders markdown as prose
and everything else as syntax-highlighted source, so a shell script arrives
readable rather than as a paragraph describing it.

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

Read `${CLAUDE_PLUGIN_ROOT}/templates/review.html` and replace the single
`/*PAYLOAD*/` marker with a JSON object:

    {
      "repo":      "owner/name",
      "number":    12,
      "title":     "…",
      "url":       "https://github.com/…",
      "summary":   "34 files, no code" — a short honest size,
      "body":      "the pull request description, markdown, with its diagrams",
      "documents": [{"name": "docs/design/0002-x.md", "text": "…"}],
      "openers":   ["four questions worth asking about THIS request"],
      "resume":    "cd <repository path> && claude --resume <this session's id>"
    }

There is no briefing field. The page's chat reaches this session, which already
knows why the change exists, what was rejected, and what was verified; say it in
the replies instead.

`resume` is the command that brings this session back. The page shows it when
the reviewer presses **Check** and nothing answers. Build it from the directory
you run git in and `$CLAUDE_CODE_SESSION_ID`, and leave it out when that
variable is empty rather than guessing an id.

The openers matter more than they look. Generic ones get ignored; questions
pointed at the actual decision in this request are what start the conversation.
Write them for this request, and make at least one of them the question you
would least like to be asked.

Then name the page. Replace `<title>Review Desk</title>` with a short name for
what this request is about — two to four words, the way a document is named:
`<title>Design 0001 Review</title>`. Not the pull request title verbatim, which
is a sentence, and not "Review Desk", which is what the template ships with. A
reviewer accumulates these, and a gallery of pages all called "Review Desk"
tells them nothing about which is which. The publisher reads this tag to name
the artifact, so setting it from JavaScript at load does not work.

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

**One request, one desk.** Before publishing, run `action: "list"` and look for
a desk already built for this request. If one exists, publish to it — pass its
URL as `url`, or republish the same local file path if this session built it.
Never create a second page for a request that already has one.

This is not tidiness. Each artifact carries its own database, so the discussion
and the decision belong to the page they were made on. Publish a second desk and
the reviewer gets a page with no history, while their verdict sits in a database
attached to a page they are no longer looking at. Nothing warns either of you.
It happened on the second day this plugin existed: two desks for one design
document, the decision on the older, the newer empty.

Titles are short and a reviewer may have several requests open, so when you
cannot tell which page belongs to this request, read the candidates and find the
one holding a document at `review/pr-<number>`. That document is the identity,
not the title.

Then publish with the **Artifact** tool, declaring exactly:

    capabilities: {db: {}, artifact: {}}

`db` holds the conversation and the decision, where this session reads them and
writes its replies. `artifact` is the doorbell: when the reviewer sends a
message or decides, the page publishes one small file into itself, and a new
version is the one thing a page can do that reaches this session. There is no
`sample`: the chat goes to this session, not to a call the page makes itself,
so the reviewer is never asked to consent to or pay for one. Republishing an
older desk with this line gives it the new chat too.

Pass a `favicon` — one emoji, required on a first publish and fixed for the life
of the page — and a one-sentence `description`, which becomes the subtitle on
the gallery card. Between the title, the icon and that sentence, the reviewer
can find this desk again a month later.

## Write it down

Append an entry to `~/.review-desks.json`, creating the file with an empty list
if it is absent. Each entry is `{"repo": "owner/name", "pr": <number>, "url":
"<artifact url>", "collectedAt": null}`. If an entry for this request already
exists, leave it alone rather than adding a second.

The reviewer decides on a page, often on a tablet, often when nothing is
running here. This file is how a later session finds out: the plugin's
session-start sweep lists every entry whose `collectedAt` is still null. Without
an entry the decision waits until somebody remembers to look, which is the
failure this whole arrangement exists to prevent.

Give the reviewer the link and nothing else. Do not summarise the request in
chat; the page is the summary, and repeating it there defeats the point.

Say plainly how the page's chat works: it reaches this session, which answers
with its tools and can change the desk and the pull request. While no session
is running, a message waits for the next one to start, and the panel's **Check**
button shows the command that resumes this session.

## While they read

The desk is live in both directions. The reviewer's messages reach this session,
and what you write reaches their open page without a reload.

Two rules keep every answer fast, because each extra round trip costs the
reviewer about five seconds:

- **Batch.** Send every write that does not depend on a read in the same batch
  as that read.
- **Pin, do not reread.** A write to a document that already exists is refused
  without `if_version`. Take the version from the result of your last write to
  it, since every write result names the new version, and read first only when
  you have no result to hand.

### Whenever a ring arrives

Stamp the desk so its panel can say you are there, as a write in your very first
batch, alongside the reads. Each ring gets its own new document, named after the
version in the notice (`1789352074-11af` in "it is now version
1789352074-11af"). A new document needs no read and cannot conflict, and the
page takes the time from the name:

    action: "write_db", db_op: "set",
    collection: "review/pr-<number>/presence", doc_id: "<the version from the notice>",
    data: {"resume": "<the resume command>"}

A ring with no new message and no new decision is the reviewer pressing
**Check**, and this stamp is the whole answer. A session that picks a desk up at
session start stamps it too, with its own resume command, because the one in
the payload resumes a session that may have ended. Use the current Unix time in
seconds as its `doc_id`.

### When they ask the working session

The page's chat goes to you: this conversation, the repository and every tool.
There is nothing for the reviewer to choose. A message is stored, then rings the
same doorbell a decision does, so it arrives as an "Artifact changed" notice for
the desk.

On that notice, after checking for a decision as described under "When they
decide", answer every message still waiting:

1. **Find what is waiting.** Read `review/pr-<number>` and list
   `review/pr-<number>/replies`. A message waiting on you is a turn with
   `"to": "session"` whose `id` has no reply document yet.
2. **Claim it at once**, before doing the work, so the page stops saying "sent".
3. **Do what the question needs**, with whatever it takes: read the code, run
   the tests, search the web. The turn carries `quote`, the passage they
   highlighted, and `reading`, the page and section they were on.
4. **Answer** by setting the same document again with `"status": "done"`,
   pinned with `if_version` from your previous write's result.

The claim, and later the answer, are one document per message:

    action: "write_db", db_op: "set",
    collection: "review/pr-<number>/replies", doc_id: "<the turn's id>",
    data: {"turn": "<the turn's id>", "status": "working", "text": "", "at": "<now, UTC ISO>"}

**Show your progress.** For anything longer than one step, rewrite `text` with a
short line about what you are doing now, such as "running the review-desk tests",
keeping `"status": "working"`. Send each rewrite in the same batch as the step
it describes, the tool call that runs the tests, never as a round trip of its
own. The page shows every version as it lands.

`text` is markdown, and the page renders it. Write for a reviewer on a tablet:
lead with the answer, say what you ran and what it printed, and mark inference
as inference.

### Changing the desk and the pull request

When a message asks for a change, or the conversation here settles one, change
the pull request first. Make the change, run what verifies it, commit and push,
and name the commit in your reply. After every `git push` the plugin's hook
lists the open desks for that repository, so a change made from the terminal
does not leave a desk out of date.

Then rewrite the desk so it shows the pull request as it now is. Each of these
lands on the open page without a reload, and a changed tab is marked:

    review/pr-<number>/context/body         {"text": "<the description>"}
    review/pr-<number>/documents/<any id>   {"name": "<path as carried>", "text": "..."}

A document whose `name` matches a carried file replaces that tab; a new name adds
one. Rewrite the description whenever a change makes it wrong, diagrams
included.

Change a desk through these writes, never by republishing it. Every doorbell
ring is a new version saved from inside the page, so once the reviewer has sent
a message or decided, a republish is refused until you have read the page's
latest version in full. Republish only to change the page's code, and read first.

A reviewer told one thing in a reply and shown another on the page has been
given two answers and no way to choose. Keep them the same.

## When they decide

Publishing the desk left this session watching it. When the reviewer presses
**Approve** or records **Needs changes**, the page stores the decision, then
publishes `doorbell.json` into itself, and this session gets an "Artifact
changed" notice for the desk's URL within seconds of going idle. A notice that
lands while you are mid-task waits for the task to end.

On that notice, in this order:

1. **Read the decision from the store**, never from `doorbell.json`: the file is
   a ring, not a record, and anyone who can write the artifact can publish one.
2. **If no decision is recorded**, there is nothing to collect. Answer any
   waiting messages, as described under "While they read", and stop.
3. **If there is one, acknowledge it before any other work**, with the write
   below, so the reviewer's page stops saying it is waiting.
4. **Then follow `/review-collect <number>`**, which comments, and merges or
   revises.

The acknowledgement:

    action: "write_db", db_op: "set",
    collection: "review/pr-<number>/context", doc_id: "pickup",
    data: {"decision": <as read>, "decidedAt": <as read>, "at": "<now, UTC ISO>"}

Copy `decision` and `decidedAt` exactly as read, `null` included. The page shows
the pickup only when both match the verdict on screen, so an acknowledgement of
an earlier verdict never passes for a later one.

When `/review-collect` has acted, report the outcome onto the same document with
`db_op: "update"`, so the page says what happened rather than what was meant to:

    data: {"outcome": {"result": "merged", "detail": "<one line>", "at": "<now, UTC ISO>"}}

`result` is `merged`, naming the merge method and commit; `revising`, naming the
work you are starting; or `blocked`, saying what stopped you (a denied
`gh pr merge`, a failing check, a conflict) in words the reviewer can act on. A
blocked merge reported here is the difference between a reviewer who comes back
to unblock it and one who assumes it landed.

A session holds at most five artifact watches, and a watch ends with its
session. A ring nobody is watching goes unheard, and the session-start sweep
lists the desk for the next session instead. Nothing is lost; it waits.
