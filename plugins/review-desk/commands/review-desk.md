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

For each `.md` file among them, fetch its content at the head of the branch and
carry the whole text. Do not carry diffs of them — the reviewer wants the
document as it will be, not as it changed.

For a request with no markdown in it, carry a short plain-English account of
what the code does instead, written by you, in the `body` you pass through.

## Build

Read `${CLAUDE_PLUGIN_ROOT}/templates/review.html` and replace the single
`/*PAYLOAD*/` marker with a JSON object:

    {
      "repo":      "owner/name",
      "number":    12,
      "title":     "…",
      "url":       "https://github.com/…",
      "summary":   "34 files, no code" — a short honest size,
      "body":      "the pull request description, markdown",
      "documents": [{"name": "docs/design/0002-x.md", "text": "…"}],
      "openers":   ["four questions worth asking about THIS request"]
    }

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

    capabilities: {sample: {}, db: {}}

`sample` is what lets the page ask Claude. `db` is what makes the conversation
and the decision readable afterwards — without it the discussion evaporates and
this is just a nicer diff.

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
running here. This file is how a later session finds out. Without it the
decision waits until somebody remembers to look, which is the failure this
whole arrangement exists to prevent.

Give the reviewer the link and nothing else. Do not summarise the request in
chat; the page is the summary, and repeating it there defeats the point.

Say plainly that the Claude inside the page is a fresh call which can see the
request and the conversation and nothing more — it cannot run tests or read the
wider repository.

## Afterwards

When they have decided, `/review-collect <n>` reads the discussion back, writes
it into the pull request, and merges on approval.
