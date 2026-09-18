"""The session lifecycle lives in two command docs a model follows, so CI can
only check that they say the right thing. These tests pin the rules that stop
a decision being collected twice, a revising desk vanishing from the hooks, a
dead session's claim stranding a message, and a publish assuming its watch.
They also hold the docs to the constants the hooks use, so the two cannot
drift apart. No dependencies beyond the standard library."""
import json
import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "hooks"))

import after_push  # noqa: E402
import sweep  # noqa: E402

WORDS = {4: "four", 5: "five"}


def read(name):
    with open(os.path.join(ROOT, "commands", name), encoding="utf-8") as f:
        return f.read()


def section(doc, heading):
    """The text under `heading` up to the next heading at the same or a higher
    level, with line breaks folded so a phrase wrapped across lines is found."""
    m = re.search(r"^(#{2,3}) " + re.escape(heading) + r"\s*$", doc, re.M)
    assert m, f"no heading {heading!r}"
    level = len(m.group(1))
    rest = doc[m.end():]
    end = re.search(r"^#{2,%d} " % level, rest, re.M)
    return rest[:end.start()] if end else rest


def flat(text):
    return " ".join(text.split())


def first_code_block(text):
    """The first run of four-space-indented lines."""
    lines, started = [], False
    for line in text.splitlines():
        if line.startswith("    "):
            lines.append(line.strip())
            started = True
        elif started and line.strip():
            break
    return lines


class Collect(unittest.TestCase):
    doc = read("review-collect.md")

    def test_pickup_is_read_in_the_first_batch(self):
        batch = first_code_block(section(self.doc, "Read it back"))
        self.assertTrue(any('collection: "review", doc_id: "pr-<n>"' in l for l in batch), batch)
        self.assertTrue(any('db_op: "list", collection: "review/pr-<n>/replies"' in l
                            for l in batch), batch)
        self.assertTrue(any('collection: "review/pr-<n>/context", doc_id: "pickup"' in l
                            for l in batch), batch)
        self.assertIn("in one batch", flat(section(self.doc, "Read it back")))

    def test_the_first_batch_stamps_presence_before_anything_is_known(self):
        # The stamp was only ever written on the path that answers a message.
        # A decision ring goes read -> pickup -> here, and this command's own
        # batch had three reads and no write, so accrue#9 and accrue-scratch#4
        # were merged off a ring while their pages still said "waiting".
        batch = first_code_block(section(self.doc, "Read it back"))
        self.assertTrue(any('db_op: "set",  collection: "review/pr-<n>/presence"' in l
                            for l in batch), batch)
        self.assertTrue(any('data: {"resume": "<the resume command>"}' in l for l in batch), batch)
        text = flat(section(self.doc, "Read it back"))
        self.assertIn("the only thing the reviewer can see", text)
        self.assertIn("Stamp it before you know whether there is anything to collect", text)
        self.assertIn("leave it written when there is not", text)
        # Named after the ring when a ring sent us here, so a stamp answers a ring.
        self.assertIn("Name the document after the version in the ring notice", text)
        self.assertIn("current Unix time in seconds when you arrived any other way", text)

    def test_a_matching_pickup_means_already_handled(self):
        text = flat(section(self.doc, "Is it already handled"))
        self.assertIn("The pickup holds the same `decision` and the same `decidedAt`, and an `outcome`",
                      text)
        self.assertIn("already collected", text)
        for forbidden in ("do not write the pickup", "do not post another comment",
                          "do not merge", "do not touch its `outcome`"):
            self.assertIn(forbidden, text.lower())
        self.assertIn('"While they read"', text)
        # The check comes before anything that writes to the pull request.
        order = [self.doc.index("## " + h) for h in
                 ("Read it back", "Is it already handled", "Write it into the request", "Act on it")]
        self.assertEqual(order, sorted(order))

    def test_a_pickup_without_an_outcome_is_a_claim_taken_over_when_stale(self):
        # A session that wrote the pickup and stopped before commenting or
        # merging must not strand the decision.
        text = flat(section(self.doc, "Is it already handled"))
        self.assertIn("The pickup holds the same `decision` and `decidedAt` but no `outcome`", text)
        self.assertIn("**A stale claim**", text)
        self.assertIn("Take it over: write the pickup again", text)
        self.assertIn("pinned with `if_version` from your read", text)

    def test_own_claim_from_this_turn_carries_on(self):
        # /review-desk writes the pickup and then sends the session here, so the
        # most common path meets its own fresh claim. A rule that said "leave it
        # and stop" for that stranded every new decision without an outcome.
        text = flat(section(self.doc, "Is it already handled"))
        own = re.search(r"\*\*Your own claim, written in this turn\.\*\*(.*?)- \*\*", text)
        self.assertTrue(own, text)
        self.assertIn("Do not write the pickup again; carry on below", own.group(1))
        self.assertNotIn("stop", own.group(1))
        other = re.search(r"\*\*Another session's claim that is not stale\*\*(.*?)- \*\*", text)
        self.assertTrue(other, text)
        self.assertIn("Leave it, answer any waiting messages, and stop", other.group(1))
        self.assertIn("your own from an earlier turn", text)

    def test_the_pull_request_is_read_before_commenting_or_merging(self):
        first = flat(section(self.doc, "Answer what is waiting first"))
        self.assertIn("gh pr view <n> --repo <owner/repo> --json state,mergeCommit,comments,commits", first)
        write = flat(section(self.doc, "Write it into the request"))
        self.assertIn('Use the pull request as read under "Answer what is waiting first"', write)
        self.assertIn("**Review desk decision:** <decision>, recorded <decidedAt>", write)
        self.assertIn("If a comment already opens with that exact line", write)
        act = flat(section(self.doc, "Act on it"))
        self.assertIn("already `MERGED`, do not run `gh pr merge` again", act)

    def test_only_merged_or_closed_stamp_collected_at(self):
        text = flat(section(self.doc, "Record it in the ledger"))
        rule = re.search(r"Stamp `collectedAt`[^.]*only when the outcome is ([^.]*)\.", text)
        self.assertTrue(rule, text)
        self.assertEqual(set(re.findall(r"`(\w+)`", rule.group(1))), set(after_push.TERMINAL))
        self.assertIn("For `revising`, `revised` and `blocked`, leave `collectedAt` null", text)
        # No other passage in either doc tells a session to stamp it.
        for name in ("review-collect.md", "review-desk.md"):
            for sentence in re.split(r"(?<=[.;:])\s", flat(read(name))):
                if re.search(r"\b(set|stamp)\b[^.]*`collectedAt`", sentence, re.I) and \
                        not re.search(r"only when|back to null|never stamp|\bnull\b|"
                                      r"records a `merged` or `closed`", sentence, re.I):
                    self.fail(f"{name}: {sentence}")

    def test_collected_desk_is_unwatched(self):
        text = flat(section(self.doc, "Record it in the ledger"))
        self.assertIn('action: "unwatch"', text)

    def test_waiting_messages_are_answered_before_the_pull_request_is_written(self):
        # Collecting first posted a permanent comment calling a question
        # unanswered, and merged before a "hold on" was read.
        order = [self.doc.index("## " + h) for h in
                 ("Is it already handled", "Answer what is waiting first",
                  "Write it into the request", "Act on it")]
        self.assertEqual(order, sorted(order))
        text = flat(section(self.doc, "Answer what is waiting first"))
        self.assertIn("answer every message still waiting", text)
        self.assertIn('"While they read"', text)
        write = flat(section(self.doc, "Write it into the request"))
        self.assertIn("Post the comment only after every waiting reply is written", write)

    def test_a_message_after_the_decision_blocks_the_merge(self):
        text = flat(section(self.doc, "Answer what is waiting first"))
        rule = re.search(r"reviewer's turn whose `at` is later than `decidedAt`(.*?)(?=\n|$)", text)
        self.assertTrue(rule, text)
        self.assertIn("do not merge", text)
        self.assertIn('"result": "blocked"', text)
        self.assertIn("message after deciding", text)
        self.assertIn("decide again", text)
        # The user typing the command does not clear this block; only a new decision does.
        exception = flat(section(self.doc, "Is it already handled"))
        self.assertIn("does not cover a block for a message after deciding", exception)

    def test_github_state_is_read_before_a_later_message_can_block(self):
        # A session that merged and then stopped leaves a pickup with no outcome.
        # Blocking on a later message before reading GitHub would report a merged
        # request as "not merged".
        text = flat(section(self.doc, "Answer what is waiting first"))
        self.assertLess(text.index("gh pr view"), text.index("later than `decidedAt`"))
        self.assertIn("What GitHub shows wins", text)
        self.assertIn("ever reported as `blocked`", text)

    def test_an_approval_merges_only_the_commit_the_reviewer_read(self):
        # Approve used to merge whatever the head was when the ring was handled,
        # so a push after the decision was merged unread.
        first = flat(section(self.doc, "Answer what is waiting first"))
        query = re.search(r"gh pr view <n> --repo <owner/repo> --json (\S+)", first)
        self.assertTrue(query, first)
        self.assertEqual(query.group(0), flat(self.doc)[flat(self.doc).index("gh pr view"):][:len(query.group(0))],
                         "the head is read in the first gh pr view")
        self.assertIn("headRefOid", query.group(1).split(","))
        self.assertIn("state", query.group(1).split(","))
        rule = re.search(r"\*\*Approved, with a `decidedOn` that is not the `headRefOid` you read:\*\*(.*?)- \*\*",
                         first)
        self.assertTrue(rule, first)
        body = rule.group(1)
        self.assertIn("Do not merge", body)
        self.assertIn('"result": "blocked"', body)
        self.assertIn("(<decidedOn, 7 chars>..<headRefOid, 7 chars>)", body)
        self.assertIn("decide again", body)
        self.assertIn("Record `blocked` in the ledger", body)
        # MERGED and CLOSED are read, and win, before the head is compared.
        self.assertLess(first.index("If `state` is `MERGED`"), first.index(rule.group(0)))
        self.assertIn("whatever was pushed after they approved", first)
        act = flat(section(self.doc, "Act on it"))
        self.assertIn("gh pr merge <n> --repo <owner/repo> --match-head-commit <decidedOn>", act)
        self.assertLess(act.index("already `MERGED`, do not run `gh pr merge` again"),
                        act.index("--match-head-commit <decidedOn>"))
        # The flag's meaning is gh's own help text, quoted, not a paraphrase.
        self.assertIn('"Commit SHA that the pull request head must match to allow merge"', act)
        self.assertIn("A refused merge is `blocked`", act)
        self.assertIn("`--match-head-commit` refuses is `blocked`", act)

    def test_a_desk_without_decided_on_merges_as_before_without_asking(self):
        act = flat(section(self.doc, "Act on it"))
        legacy = act[act.index("A desk published before `decidedOn` existed"):]
        self.assertIn("Merge it as before, after the same state and later-message checks", legacy)
        self.assertIn("--match-head-commit <headRefOid>", legacy)
        self.assertIn("Do not stall it and do not ask in the terminal", legacy)
        read_back = flat(section(self.doc, "Read it back"))
        self.assertIn("`decidedOn`, the pull request's head commit the page was showing", read_back)
        self.assertIn("A desk published before `decidedOn` existed stores none", read_back)

    def test_a_later_message_does_not_skip_the_head_sync(self):
        # Both rules can apply at once. The later-message rule says "stop"; if a
        # session stopped there, the page would keep the old head and the next
        # Approve would store the old commit again.
        first = flat(section(self.doc, "Answer what is waiting first"))
        self.assertIn("Check both approval rules below before stopping at either", first)
        self.assertIn("bringing the desk to the head first, then report one `blocked` outcome", first)
        self.assertLess(first.index("Check both approval rules"),
                        first.index("**Approved, with a reviewer's turn whose `at` is later than `decidedAt`:**"))

    def test_a_head_block_brings_the_desk_to_the_head_before_reporting(self):
        # The page stores as decidedOn only the head context/body names. A block
        # that left the desk on the old head made every re-approval store the
        # old commit again and block again, with no way out from the page.
        first = flat(section(self.doc, "Answer what is waiting first"))
        rule = re.search(r"\*\*Approved, with a `decidedOn` that is not the `headRefOid` you read:\*\*(.*?)- \*\*",
                         first).group(1)
        self.assertIn("bring the desk to the head you read, whoever pushed it", rule)
        self.assertIn('set `context/body` to `{"text", "head": "<headRefOid>"}`', rule)
        self.assertIn("## Changed since you opened this", rule)
        self.assertIn("gh api repos/<owner/repo>/compare/<decidedOn>...<headRefOid>", rule)
        self.assertIn("rewrite each carried document whose file those commits changed", rule)
        # The desk write lands before the outcome that asks for a new decision.
        self.assertIn("Report the outcome only once `context/body` has landed with the new `head`, not in the same batch",
                      rule)
        self.assertLess(rule.index("set `context/body`"), rule.index('"result": "blocked"'))
        # A merge --match-head-commit refuses for a moved head does the same.
        act = flat(section(self.doc, "Act on it"))
        refused = act[act.index("A refused merge is `blocked`"):]
        self.assertIn("read `headRefOid` again, bring the desk to it and only then report the outcome", refused)

    def test_a_head_block_moves_the_ledger_head_in_the_same_step(self):
        # The desk was brought to the new head but the ledger entry kept the old
        # one, so the next push's `git log <head>..origin/<branch>` listed the
        # same commits on the desk again.
        first = flat(section(self.doc, "Answer what is waiting first"))
        rule = re.search(r"\*\*Approved, with a `decidedOn` that is not the `headRefOid` you read:\*\*(.*?)- \*\*",
                         first).group(1)
        sync = ("once `context/body` has landed, set the ledger entry's `head` to `headRefOid` "
                "in the same step")
        self.assertIn(sync, rule)
        self.assertLess(rule.index('set `context/body` to `{"text", "head": "<headRefOid>"}`'),
                        rule.index(sync))
        self.assertLess(rule.index(sync), rule.index('"result": "blocked"'))
        self.assertIn('"Changing the desk and the pull request"', rule[rule.index(sync):])

    def test_a_head_block_is_not_cleared_from_the_terminal(self):
        exception = flat(section(self.doc, "Is it already handled"))
        self.assertIn("or for commits pushed after approving: those clear only when the reviewer decides again",
                      exception)

    def test_desk_is_found_through_the_ledger_by_repo_and_pr(self):
        text = flat(section(self.doc, "Read it back"))
        self.assertLess(text.index("~/.review-desks.json"), text.index('action: "list"'))
        self.assertIn("whose `repo` and `pr` match", text)
        self.assertIn("`repo` field", text)
        self.assertIn("must equal", text)
        self.assertIn("has none", text)


    def test_a_merge_refused_by_the_permission_system_is_blocked_naming_the_rule(self):
        # Seen on the real host: auto mode refused `gh pr merge` for an approved
        # desk, and the approval waited on someone running the merge by hand.
        act = flat(section(self.doc, "Act on it"))
        start = act.index("**A merge refused by Claude Code's permission system, not by GitHub.**")
        para = act[start:act.index("A desk published before `decidedOn` existed", start)]
        self.assertIn("this machine has not allowed unattended merges", para)
        self.assertIn("Do not retry it, and never try another route to the merge", para)
        for route in ("`gh api`", "`git merge` and a push", "`command gh`", "`sh -c`"):
            self.assertIn(route, para)
        data = re.search(r'data: (\{"outcome".*?\}\})', para)
        self.assertTrue(data, para)
        outcome = json.loads(data.group(1))["outcome"]
        self.assertEqual(outcome["result"], "blocked")
        self.assertIn(f"allow rule {sweep.MERGE_RULE}", outcome["detail"])
        self.assertIn("has not allowed unattended merges", outcome["detail"])
        self.assertIn(sweep.README_SECTION, outcome["detail"])
        self.assertIn(f"`{sweep.RTK_MERGE_RULE}` beside `{sweep.MERGE_RULE}`", para)
        self.assertIn("Record `blocked` in the ledger", para)
        self.assertIn("tell the user in the terminal the same thing", para)
        self.assertIn("Do not add the rule or change any settings file yourself", para)
        # Adding the rule is what clears the block when the user runs the command.
        exception = flat(section(self.doc, "Is it already handled"))
        self.assertIn("such as adding the allow rule for a merge Claude Code refused", exception)

    def test_readme_names_the_rules_and_where_they_go(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        text = flat(section(readme, sweep.README_SECTION))
        self.assertIn(f'"allow": ["{sweep.MERGE_RULE}"]', text)
        self.assertIn(f'"allow": ["{sweep.MERGE_RULE}", "{sweep.RTK_MERGE_RULE}"]', text)
        self.assertIn("`~/.claude/settings.json`", text)
        self.assertIn("The plugin does not add the rule itself", text)
        self.assertIn("classifyAllShell", text)


# An imperative aimed at whoever reads the text: a sentence that starts by
# telling the reader to change settings or permission rules.
EDIT_SETTINGS = re.compile(
    r"^(?:then |and |so |first |now |please )?(?:you (?:can |should |must |may )?)?"
    r"(?:add|edit|write|update|modify|append|insert|put|set|change|grant|allow)\b"
    r".*(?:settings(?:\.local)?\.json|\bsettings\b|permissions\.(?:allow|ask|deny)|"
    r"allow rule|permission rule|/permissions|update-config)",
    re.I)


def edits_settings(sentence):
    return bool(EDIT_SETTINGS.search(sentence.lstrip("-*> `#0123456789.")))


class NoSettingsEdits(unittest.TestCase):
    """A plugin must not grant itself permissions. Nothing under
    plugins/review-desk may tell the reader, session or person, to edit
    settings or permission rules; the README states the rule and where it
    goes, and the hooks and commands only tell the user about it."""

    def texts(self):
        skip = {"node_modules", "tests", ".git"}
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in skip]
            for name in files:
                path = os.path.join(base, name)
                if name.endswith(".py"):
                    import ast
                    with open(path, encoding="utf-8") as f:
                        tree = ast.parse(f.read())
                    body = " ".join(n.value for n in ast.walk(tree)
                                    if isinstance(n, ast.Constant) and isinstance(n.value, str))
                elif name.endswith((".md", ".html", ".json")):
                    with open(path, encoding="utf-8") as f:
                        body = f.read()
                else:
                    continue
                yield os.path.relpath(path, ROOT), body

    def test_the_check_catches_an_instruction_to_edit_settings(self):
        for bad in ("Add `Bash(gh pr merge *)` to ~/.claude/settings.json.",
                    "Then write the allow rule into .claude/settings.local.json",
                    "You can add the rule to permissions.allow",
                    "- Update the user's settings with the rule"):
            self.assertTrue(edits_settings(bad), bad)
        for fine in ("Tell the user in one line that adding `Bash(gh pr merge *)` to permissions.allow lets it merge",
                     "Do not add the rule or change any settings file yourself",
                     "The place for it is `~/.claude/settings.json`, your user settings"):
            self.assertFalse(edits_settings(fine), fine)

    def test_no_plugin_text_tells_anyone_to_edit_settings(self):
        mentions = 0
        for rel, body in self.texts():
            for sentence in re.split(r"(?<=[.!?;:])\s+|\n\s*\n", body):
                sentence = flat(sentence)
                if re.search(r"settings|permissions\.allow|allow rule", sentence, re.I):
                    mentions += 1
                with self.subTest(file=rel, sentence=sentence[:90]):
                    self.assertFalse(edits_settings(sentence), sentence)
        # Guards against a pass that checked nothing because the files moved.
        self.assertGreaterEqual(mentions, 5)


class Desk(unittest.TestCase):
    doc = read("review-desk.md")

    def test_each_file_is_carried_at_the_head_and_at_the_base(self):
        # The page's third view is the request's own diff, which it can only draw
        # from a text it was given: the page cannot reach GitHub.
        text = flat(section(self.doc, "Gather"))
        self.assertIn("Carry each file **twice**", text)
        self.assertIn("contents/<path>?ref=<baseRefName>", text)
        self.assertIn('carry `"base": null`', text)
        self.assertIn("leave `base` out altogether rather than truncating it", text)
        build = flat(section(self.doc, "Build"))
        self.assertIn('"base": "the same file on baseRefName, or null if the request adds it"', build)
        self.assertIn('"baseRefName": "main"', build)
        # And a rewrite has to carry it too, or the view goes away mid-review.
        self.assertIn("Carry `base` on a rewritten document too",
                      flat(section(self.doc, "Changing the desk and the pull request")))

    def test_publish_checks_the_watch_line(self):
        publish = section(self.doc, "Publish")
        self.assertIn("### Check the watch line", publish)
        text = flat(section(self.doc, "Check the watch line"))
        self.assertIn("watch line", text)
        self.assertIn("Skipped at the watch limit", text)
        self.assertIn('action: "status"', text)
        self.assertIn('action: "unwatch"', text)
        self.assertIn("`collectedAt` set", text)
        self.assertIn("say so at handover", text)

    def test_republishing_rewrites_the_store(self):
        text = flat(section(self.doc, "Publish"))
        self.assertIn("Publishing into an existing desk also rewrites what its store shows", text)
        self.assertIn("set `context/body`", text)
        self.assertIn("set each carried file's document", text)
        self.assertIn("delete, pinned with `if_version`", text)
        self.assertGreaterEqual(text.count("if_version"), 3)

    def test_revising_desk_stays_in_the_ledger(self):
        text = flat(section(self.doc, "Write it down"))
        self.assertIn("a desk being revised stays open", text)
        self.assertIn("set `collectedAt` and `outcome` back to null", text)

    def test_ledger_entry_records_the_launch_directory(self):
        # The sweep lists an entry whose cwd is the SessionStart directory, so a
        # desk published from ~ is picked up again after --resume there.
        text = flat(section(self.doc, "Write it down"))
        self.assertIn('"cwd": "<launch directory>"', text)
        self.assertIn("the directory this session was launched in", text)
        self.assertIn("not a directory you later ran `cd` into", text)
        self.assertIn("set its `cwd` to this session's launch directory", text)
        self.assertIn("any remote of its directory", text)
        self.assertIn("even when it is not a git repository", text)
        self.assertIn("written before `cwd` was recorded", text)

    def test_resume_is_built_from_the_launch_directory_and_an_unsafe_path_is_told_in_the_terminal(self):
        # claude --resume finds a session by the directory it was launched from,
        # and the page's RESUME_SHAPE shows only a path of [\w.~/-].
        build = flat(section(self.doc, "Build"))
        self.assertIn('"resume": "cd <launch directory> && claude --resume', build)
        self.assertNotIn("<repository path>", build)
        self.assertIn("Build it from the directory this session was launched in", build)
        self.assertIn("Not the directory you run git in", build)
        self.assertNotIn("Build it from the directory you run git in", build)
        self.assertIn("letters, digits and `_ . ~ / -`", build)
        self.assertIn("cannot be offered: leave `resume` out, and tell the user in the terminal", build)
        down = flat(section(self.doc, "Write it down"))
        self.assertIn("a resumed session does nothing until someone types", down)

    def test_ledger_records_the_published_head_and_branch(self):
        # "Changed since you opened this" lists commits pushed since the desk was
        # published, and nothing recorded which commit that was, so a later
        # session listed every commit on the pull request or guessed.
        down = flat(section(self.doc, "Write it down"))
        self.assertIn('"cwd": "<launch directory>", "head": "<headRefOid>", '
                      '"branch": "<headRefName>", "collectedAt": null}', down)
        self.assertIn("its `head` and `branch` to this publish's", down)
        self.assertIn("Every later head sync, whether a rewrite of `context/body` for a push, a republish, or `/review-collect` bringing the desk to a moved head, sets the entry's `head`",
                      down)
        self.assertIn("An entry written before these fields were recorded has neither and still works",
                      down)

    def test_changelog_is_computed_from_the_recorded_head(self):
        change = flat(section(self.doc, "Changing the desk and the pull request"))
        self.assertIn("Compute those commits from the ledger; never recall or guess them", change)
        self.assertIn("git log --reverse --format='%h %s' <head>..origin/<branch>", change)
        self.assertIn("gh api repos/<owner/repo>/compare/<head>...<headRefOid>", change)
        self.assertIn("start from the `head` in the stored `context/body` instead", change)
        # A second rewrite used to drop the lines the first one wrote.
        self.assertIn("read it first and keep the lines its section already has", change)
        # The push rewrite moves the ledger head, and only once the body has landed.
        rule = "Once the write has landed, set the entry's `head` to the `headRefOid` it wrote"
        self.assertIn(rule, change)
        self.assertLess(change.index("<head>..origin/<branch>"), change.index(rule))
        self.assertLess(change.index("Rewrite `context/body` after every push"), change.index(rule))
        self.assertIn("a desk whose entry records a `branch` is listed only when the push updates that branch",
                      change)
        publish = flat(section(self.doc, "Publish"))
        self.assertIn("When the ledger entry's `head` is not the payload's, open the text with the "
                      "`## Changed since you opened this` section", publish)

    def test_every_head_sync_moves_the_ledger_head_in_the_same_step(self):
        change = flat(section(self.doc, "Changing the desk and the pull request"))
        rule = "**Every head sync moves the ledger entry's `head` in the same step.**"
        self.assertIn(rule, change)
        para = change[change.index(rule):]
        for sync in ("this rewrite after a push", 'a republish under "Publish"',
                     "`/review-collect` bringing the desk to a head"):
            self.assertIn(sync, para)
        self.assertIn("as soon as that write lands, before its reply, its outcome or anything else", para)
        self.assertIn("list the same commits again", para)
        self.assertLess(change.index("Rewrite `context/body` after every push"), change.index(rule))
        publish = flat(section(self.doc, "Publish"))
        self.assertIn("This is a head sync: once it lands, set the ledger entry's `head` to the "
                      "payload's `headRefOid` in the same step", publish)

    def test_invalid_argument_is_diagnosed_before_blaming_ownership(self):
        # The same code covers bad ids and oversize documents, and "not the
        # owner, do not retry" silently abandoned a desk the session did own.
        text = flat(section(self.doc, "Publish"))
        start = text.index("A write refused with `invalid_argument` has three possible causes")
        para = text[start:text.index("Pass a `favicon`", start)]
        self.assertNotIn("`invalid_argument`, this session is not the desk's owner", text)
        causes = [para.index(p) for p in (
            "**A bad path or document id:**", "over 200 bytes",
            "**A document over 256 KiB**",
            "**This session is not the desk's owner:**")]
        self.assertEqual(causes, sorted(causes))
        check = [para.index(p) for p in (
            "its document id is at most 200 bytes",
            "serialized as JSON, escapes included, is under 256 KiB",
            "prove ownership with a small presence write",
            "Only when the presence write is refused too is this session not the desk's owner",
            "rather than retrying")]
        self.assertEqual(check, sorted(check))
        self.assertGreater(check[0], causes[-1])
        self.assertIn("`set` under `review/pr-<number>/presence`", para)

    def test_document_id_is_capped_and_oversize_text_is_excerpted(self):
        text = flat(section(self.doc, "Changing the desk and the pull request"))
        self.assertIn("An id is at most 200 bytes", text)
        cap = re.search(r"keep its first (\d+) characters and append `-` and the first "
                        r"(\d+) hex characters of the SHA-256 of the full path", text)
        self.assertTrue(cap, text)
        keep, digest = int(cap.group(1)), int(cap.group(2))
        # The stated split must add up to the cap, or the rule yields refused ids.
        self.assertEqual(keep + 1 + digest, 200)
        self.assertIn(f"cut -c1-{digest}", text)
        self.assertIn("A document holds at most 256 KiB serialized as JSON", text)
        self.assertIn("carry an excerpt instead", text)
        self.assertIn("a line saying the text was cut", text)
        # The limit the refusal paragraph checks is the one this section applies.
        publish = flat(section(self.doc, "Publish"))
        self.assertIn("cap the id or carry an excerpt", publish)


class Asking(unittest.TestCase):
    """A question from the desk is answered by this session, with tools. The
    platform answers it first, from context alone, and that cannot be switched
    off -- so the desk controls what that reply is asked to do."""
    doc = read("review-desk.md")

    def test_the_quick_reply_is_told_to_be_a_receipt(self):
        text = flat(section(self.doc, "A question reaches you as a comment"))
        self.assertIn("User states from the desk, on <the passage>:", text)
        self.assertIn('reply with exactly "Taken to the session."', text)
        self.assertIn("It cannot be switched off", text)
        self.assertIn("the same armed mechanism is what delivers the comment", text)

    def test_the_session_writes_the_answer_over_it(self):
        text = flat(section(self.doc, "A question reaches you as a comment"))
        self.assertIn("do the work with your own tools", text)
        self.assertIn("acknowledge_duplicate: true", text)
        self.assertIn("correct it plainly", text.lower())

    def test_the_page_carries_that_instruction_itself(self):
        # The doc is not enough: the words are sent by the page, so they live in
        # the template too, and the two must not drift.
        with open(os.path.join(ROOT, "templates", "review.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Do not answer this from context.", page)
        # Wrapped across two source lines in the template, so match the halves.
        self.assertIn('Reply with exactly: "Taken to ', page)
        self.assertIn("the session.\" The session itself answers here", page)
        self.assertIn("User states from the desk, on ", page)

    def test_progress_is_written_as_the_work_happens(self):
        text = flat(section(self.doc, "Your work reaches the reviewer as you do it"))
        self.assertIn('collection: "review/pr-<number>/progress"', text)
        self.assertIn('"kind": "doing" | "found" | "wrong" | "done" | "said"', text)
        self.assertIn("the line you would have written in the terminal", text)
        self.assertIn("nothing to notify", text)


class Outcomes(unittest.TestCase):
    def test_every_enumeration_of_outcomes_includes_closed_with_one_meaning(self):
        # The page renders a `closed` outcome and review-collect reports one, but
        # the list review-desk.md gives a session to report from left it out.
        # v2 has no separate banner: the outcome is read off the pickup and shown
        # under the decision, so that is where `closed` has to be handled.
        with open(os.path.join(ROOT, "templates", "review.html"), encoding="utf-8") as f:
            page = f.read()
        for word in ("'Merged'", "'Closed'", "pickup.outcome"):
            self.assertIn(word, page, "the page reads outcomes off the pickup")
        # Only /review-collect reports an outcome now: the section of
        # /review-desk that listed them was the ring protocol.
        for name in ("review-collect.md",):
            sentences = re.split(r"(?<=\.)\s", flat(read(name)))
            listed = [s for s in sentences
                      if all(f"`{r}`" in s for r in ("merged", "revising", "blocked"))]
            self.assertTrue(listed, name)
            for sentence in listed:
                with self.subTest(doc=name, sentence=sentence[:80]):
                    self.assertIn("`closed`", sentence)
                    self.assertIn("closed without merging", sentence)
        self.assertIn("closed", after_push.TERMINAL)

    def test_a_closed_pickup_is_cleared_when_a_reopened_request_is_republished(self):
        # The page keeps a desk closed while its pickup says closed, so a reopened
        # pull request's republished desk would take no message or decision.
        down = flat(section(read("review-desk.md"), "Write it down"))
        self.assertIn("holds outcome `closed`, as it does for a pull request reopened after closing, "
                      "delete that pickup too", down)


if __name__ == "__main__":
    unittest.main()
