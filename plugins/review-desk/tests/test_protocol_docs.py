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
        write = flat(section(self.doc, "Write it into the request"))
        self.assertIn("gh pr view <n> --repo <owner/repo> --json state,mergeCommit,comments,commits", write)
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


if __name__ == "__main__":
    unittest.main()
