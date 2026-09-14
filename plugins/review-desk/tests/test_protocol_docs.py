"""The session lifecycle lives in two command docs a model follows, so CI can
only check that they say the right thing. These tests pin the rules that stop
a decision being collected twice, a revising desk vanishing from the hooks, a
dead session's claim stranding a message, and a publish assuming its watch.
They also hold the docs to the constants the hooks use, so the two cannot
drift apart. No dependencies beyond the standard library."""
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
        self.assertIn("For `revising` and `blocked`, leave `collectedAt` null", text)
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


class Desk(unittest.TestCase):
    doc = read("review-desk.md")

    def test_ring_reads_pickup_and_skips_a_handled_decision(self):
        waiting = flat(section(self.doc, "When they ask the working session"))
        self.assertIn("get `review/pr-<number>/context/pickup`", waiting)
        decide = flat(section(self.doc, "When they decide"))
        self.assertIn("the pickup holds the same `decision` and `decidedAt` and an `outcome`", decide)
        self.assertIn("so the decision was handled", decide)
        # A matching pickup with no outcome is a claim, judged like a reply claim.
        self.assertIn("A matching pickup with no `outcome` is a claim on the decision", decide)
        self.assertIn('"session": "<this session\'s id>"', decide)
        self.assertIn("Pin it with `if_version` from the pickup you read", decide)

    def test_stale_claim_rule_has_an_age_and_a_marker(self):
        text = section(self.doc, "When they ask the working session")
        age = re.search(r"more than \*\*(\d+) minutes\*\* old", flat(text))
        self.assertTrue(age, "no concrete age for a stale claim")
        self.assertEqual(int(age.group(1)), sweep.STALE_CLAIM_MINUTES)
        claim = "\n".join(l for l in text.splitlines() if l.startswith("    "))
        self.assertIn('"status": "working"', claim)
        self.assertIn('"session": "<this session\'s id>"', claim)
        body = flat(text)
        self.assertIn("`session` is the claim marker", body)
        self.assertIn("$CLAUDE_CODE_SESSION_ID", body)
        self.assertIn("its `session` is not this session's id, or it has no `session`", body)
        # claude --resume keeps the id, so an own claim cannot be exempt by id alone.
        self.assertIn("that you are not answering in this turn, whatever its age", body)
        self.assertIn("`claude --resume` keeps the session id", body)
        self.assertNotIn("that carries your own `session`, is not waiting", body)
        self.assertIn("pinned with `if_version`", body)
        # A progress rewrite renews the claim, or a long answer looks abandoned.
        self.assertIn('keeping `"status": "working"` and setting `at` to now', body)

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

    def test_sweep_leaves_a_watch_slot_free(self):
        self.assertLess(sweep.WATCH_CAP, 5)
        self.assertIn(f"sweep asks for at most {WORDS[sweep.WATCH_CAP]}",
                      flat(section(self.doc, "When they decide")))

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

    def test_ring_answers_waiting_messages_before_collecting(self):
        decide = flat(section(self.doc, "When they decide"))
        steps = re.findall(r"(\d)\. \*\*(.*?)\*\*", decide)
        names = [s[1] for s in steps]
        answer = next(i for i, n in enumerate(names) if "answer every waiting message" in n)
        collect = next(i for i, n in enumerate(names) if "/review-collect" in n)
        self.assertLess(answer, collect, names)
        ask = flat(section(self.doc, "When they ask the working session"))
        self.assertNotIn("after checking for a decision", ask)
        self.assertIn("before collecting any decision", ask)
        # A pickup is a claim that goes stale; a long answer must not let it.
        self.assertIn("renews the pickup", decide)

    def test_ring_names_the_request_by_repo_and_pr_from_the_ledger(self):
        full = "/review-collect <owner/repo>#<number>"
        for heading in ("Whenever a ring arrives", "When they decide"):
            text = flat(section(self.doc, heading))
            self.assertIn(full, text, heading)
        ring = flat(section(self.doc, "Whenever a ring arrives"))
        self.assertIn("`~/.review-desks.json` whose `url` matches the notice", ring)
        # No bare-number collect anywhere in the doc a ring follows.
        self.assertEqual(re.findall(r"/review-collect <(?:number|n|pr)>|/review-collect \d+", self.doc), [])
        self.assertEqual(re.findall(r"/review-collect <(?!owner/repo>#<number>)", self.doc), [])

    def test_desk_lookup_goes_through_the_ledger_and_checks_the_stored_repo(self):
        publish = flat(section(self.doc, "Publish"))
        self.assertLess(publish.index("~/.review-desks.json"), publish.index('action: "list"'))
        self.assertIn("whose `repo` and `pr` match", publish)
        self.assertIn("`repo` field", publish)
        self.assertIn("must equal", publish)
        self.assertIn("has none", publish)
        decide = flat(section(self.doc, "When they decide"))
        self.assertIn("`repo` field", decide)

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

    def test_a_pushed_revision_writes_the_head_the_page_shows(self):
        text = flat(section(self.doc, "Changing the desk and the pull request"))
        self.assertIn('{"text": "<the description>", "head": "<the pull request\'s head commit>"}', text)
        self.assertIn("Rewrite `context/body` after every push", text)
        self.assertIn("gh pr view <n> --repo <owner/repo> --json headRefOid", text)
        self.assertIn("stores it as `decidedOn`", text)
        self.assertIn("A push after **Approve** therefore blocks the merge", text)
        publish = flat(section(self.doc, "Publish"))
        self.assertIn('"head": "<the payload\'s headRefOid>"', publish)
        decide = flat(section(self.doc, "When they decide"))
        self.assertIn("an approval whose `decidedOn` is not the pull request's head", decide)

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


if __name__ == "__main__":
    unittest.main()
