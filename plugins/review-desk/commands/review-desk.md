---
description: Publish a pull request as a page the reviewer can talk to Claude inside
argument-hint: "[pr number] (defaults to the PR for the current branch)"
---

Publish pull request **$1** as a review desk: a page carrying everything needed
to judge the request, with a conversation the reviewer can hold with Claude
inside it, and a decision they record when they are ready.

This exists because a diff is the wrong surface for a decision. Reading a patch
tells you what changed; it does not let you ask why, and asking why is most of
what a reviewer actually wants to do.

## Gather

Use `gh` for everything. If no number was given, take the pull request for the
current branch.

    gh pr view <n> --json number,title,url,body,additions,deletions,changedFiles,headRefName,baseRefName

Then the markdown files the request touches, because those are documents meant
to be read rather than diffed:

    gh pr diff <n> --name-only

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

Write the filled template to a file, then publish it with the **Artifact** tool,
declaring exactly:

    capabilities: {sample: {}, db: {}}

`sample` is what lets the page ask Claude. `db` is what makes the conversation
and the decision readable afterwards — without it the discussion evaporates and
this is just a nicer diff.

Pass a `favicon` — one emoji, required on a first publish and fixed for the life
of the page — and a one-sentence `description`, which becomes the subtitle on
the gallery card. Between the title, the icon and that sentence, the reviewer
can find this desk again a month later.

Give the reviewer the link and nothing else. Do not summarise the request in
chat; the page is the summary, and repeating it there defeats the point.

Say plainly that the Claude inside the page is a fresh call which can see the
request and the conversation and nothing more — it cannot run tests or read the
wider repository.

## Afterwards

When they have decided, `/review-collect <n>` reads the discussion back, writes
it into the pull request, and merges on approval.
