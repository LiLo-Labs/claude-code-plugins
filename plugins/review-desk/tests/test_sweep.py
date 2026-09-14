"""The session-start sweep, run as the hook runs it: a subprocess fed the
SessionStart event on stdin, with HOME pointed at a scratch directory and the
session's directory a throwaway git repository. No dependencies beyond the
standard library."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
SWEEP = os.path.join(HERE, "..", "hooks", "sweep.py")
HOOKS_JSON = os.path.join(HERE, "..", "hooks", "hooks.json")


def run(ledger, origin="https://github.com/o/r.git", remotes=None):
    """Run the sweep against `ledger` (None: no file; str: raw text; a callable
    is given the session directory and returns the ledger; else JSON) from a
    repository whose remotes are `remotes`, a name-to-URL dict, or else whose
    origin is `origin` (None for both: not a repository)."""
    with tempfile.TemporaryDirectory() as home:
        cwd = os.path.join(home, "session")
        os.makedirs(cwd)
        if callable(ledger):
            ledger = ledger(cwd)
        if ledger is not None:
            with open(os.path.join(home, ".review-desks.json"), "w") as f:
                f.write(ledger if isinstance(ledger, str) else json.dumps(ledger))
        if remotes is None:
            remotes = {"origin": origin} if origin else {}
        if remotes:
            subprocess.run(["git", "init", "-q", cwd], check=True)
            for name, url in remotes.items():
                subprocess.run(["git", "-C", cwd, "remote", "add", name, url], check=True)
        event = {"hook_event_name": "SessionStart", "source": "startup", "cwd": cwd}
        done = subprocess.run([sys.executable, SWEEP], input=json.dumps(event),
                              env=dict(os.environ, HOME=home),
                              capture_output=True, text=True, timeout=10)
    return done


def desk(n, collected=None, repo="o/r"):
    return {"repo": repo, "pr": n, "url": f"https://x/{n}", "collectedAt": collected}


def said(done):
    return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]


class Sweep(unittest.TestCase):
    def test_no_ledger_says_nothing(self):
        done = run(None)
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_everything_collected_says_nothing(self):
        done = run([desk(1, "2026-09-10T00:00:00Z")])
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def test_lists_only_uncollected(self):
        text = said(run([desk(1, "2026-09-10T00:00:00Z"), desk(2)]))
        self.assertIn("o/r#2 https://x/2", text)
        self.assertNotIn("o/r#1 ", text)
        self.assertIn('doc_id "pr-<number>"', text)
        # Messages left for the working session are answered, not only decisions.
        self.assertIn("While they read", text)
        # A desk watched by a new session gets that session's resume command.
        self.assertIn("Whenever a ring arrives", text)

    def test_this_repository_first_and_other_repositories_counted(self):
        text = said(run([desk(1, repo="o/a"), desk(2), desk(3, repo="o/b"), desk(4, repo="o/a")]))
        lines = text.splitlines()
        self.assertEqual([l for l in lines if l.startswith("- o/")],
                         ["- o/r#2 https://x/2 [watch]"])
        count = [l for l in lines if "other repositories" in l]
        self.assertEqual(len(count), 1)
        self.assertIn("3 more review desks wait", count[0])
        self.assertIn("o/a (2), o/b (1)", count[0])
        self.assertLess(text.index("o/r#2"), text.index(count[0]))
        for n in (1, 3, 4):
            self.assertNotIn(f"https://x/{n}", text)

    def test_outside_a_repository_every_desk_is_only_counted(self):
        text = said(run([desk(1), desk(2, repo="o/a")], origin=None))
        self.assertEqual(len(text.splitlines()), 1)
        self.assertIn("2 more review desks wait", text)
        self.assertNotIn("read_db", text)

    def test_fork_checkout_lists_the_upstream_desk_in_full(self):
        # origin is the fork; the ledger records the pull request's base repo.
        fork = {"origin": "https://github.com/MALathon/accrue.git",
                "upstream": "https://github.com/LiLo-Labs/accrue.git"}
        text = said(run([desk(3, repo="LiLo-Labs/accrue"), desk(4, repo="o/a")], remotes=fork))
        lines = text.splitlines()
        self.assertEqual([l for l in lines if l.startswith("- ") and "https://x/" in l],
                         ["- LiLo-Labs/accrue#3 https://x/3 [watch]"])
        self.assertIn("/review-collect LiLo-Labs/accrue#3", text)
        count = [l for l in lines if "other repositories" in l]
        self.assertEqual(len(count), 1)
        self.assertNotIn("LiLo-Labs/accrue", count[0])
        self.assertIn("o/a (1)", count[0])

    def test_any_remote_matches_in_ssh_and_https_forms(self):
        for remotes in [
            {"origin": "git@github.com:fork/r.git", "upstream": "https://github.com/o/r.git"},
            {"origin": "https://github.com/fork/r.git", "upstream": "git@github.com:o/r.git"},
            {"origin": "https://github.com/fork/r", "upstream": "ssh://git@github.com/O/R.git"},
        ]:
            with self.subTest(remotes=remotes):
                text = said(run([desk(2), desk(5, repo="o/a")], remotes=remotes))
                self.assertIn("- o/r#2 https://x/2 [watch]", text)
                self.assertNotIn("https://x/5", text)

    def test_desk_recorded_as_launched_here_is_listed_outside_a_repository(self):
        # A session launched in ~ published a desk for another repository; after
        # --resume there, the ledger's cwd is the only thing tying them together.
        entries = lambda cwd: [dict(desk(6, repo="o/forge"), cwd=cwd), desk(7, repo="o/a")]
        text = said(run(entries, origin=None))
        self.assertIn("- o/forge#6 https://x/6 [watch]", text)
        self.assertIn("/review-collect o/forge#6", text)
        self.assertIn("read_db", text)
        count = [l for l in text.splitlines() if "other repositories" in l]
        self.assertEqual(len(count), 1)
        self.assertIn("o/a (1)", count[0])
        self.assertNotIn("o/forge", count[0])

    def test_recorded_cwd_is_compared_resolved(self):
        # macOS temp directories live behind a symlink (/var -> /private/var).
        entries = lambda cwd: [dict(desk(6, repo="o/forge"),
                                    cwd=os.path.realpath(cwd) + os.sep)]
        self.assertIn("- o/forge#6", said(run(entries, origin=None)))

    def test_another_or_malformed_cwd_is_only_counted(self):
        entries = lambda cwd: [dict(desk(1, repo="o/a"), cwd=os.path.dirname(cwd)),
                               dict(desk(2, repo="o/a"), cwd=42),
                               dict(desk(3, repo="o/a"), cwd="")]
        text = said(run(entries, origin=None))
        self.assertEqual(len(text.splitlines()), 1)
        self.assertIn("3 more review desks wait", text)

    def test_only_other_repositories_gets_no_read_instructions(self):
        text = said(run([desk(1, repo="o/a")]))
        self.assertIn("1 more review desk waits in other repositories", text)
        self.assertNotIn("read_db", text)

    def test_watch_marks_only_the_newest_four(self):
        # Five is the host's cap, and a watch the session asked for is never
        # evicted, so marking five left no slot for a desk published afterwards.
        text = said(run([desk(n) for n in range(1, 8)]))
        for n in (1, 2, 3):
            self.assertNotIn("[watch]", next(l for l in text.splitlines() if f"#{n} " in l))
        for n in range(4, 8):
            self.assertIn("[watch]", next(l for l in text.splitlines() if f"#{n} " in l))

    def test_six_open_desks_ask_for_at_most_four_watches(self):
        text = said(run([desk(n) for n in range(1, 7)]))
        listed = [l for l in text.splitlines() if l.startswith("- o/r#")]
        self.assertEqual(len(listed), 6)
        self.assertEqual(sum(l.endswith(" [watch]") for l in listed), 4)

    def test_revising_desk_stays_open_even_when_stamped(self):
        # The outcome decides, not the stamp: a stamp next to a revising or
        # blocked outcome (a hand edit, or a session that stamped too early)
        # must not hide a desk still under review. Only merged and closed end a
        # review; a stamp with no outcome predates recorded outcomes and stays
        # closed.
        stamped = "2026-09-10T00:00:00Z"
        entries = [dict(desk(n, stamped), outcome=o) for n, o in
                   ((1, "revising"), (2, "blocked"), (3, "merged"), (4, "closed"), (5, None))]
        text = said(run(entries))
        self.assertIn("o/r#1 https://x/1", text)
        self.assertIn("o/r#2 https://x/2", text)
        for n in (3, 4, 5):
            self.assertNotIn(f"https://x/{n}", text)

    def test_a_handled_decision_is_not_collected_again(self):
        text = said(run([desk(1)]))
        self.assertIn('doc_id "pickup"', text)
        self.assertIn("decidedAt", text)
        self.assertIn("do not collect it again", text)
        self.assertIn("and an outcome", text)

    def test_a_pickup_without_an_outcome_is_a_claim_that_can_go_stale(self):
        # A session that acknowledged a decision and stopped before merging left
        # a matching pickup; treating that as handled stranded the approval.
        text = said(run([desk(1)]))
        self.assertIn("matching pickup with no outcome is a claim", text)
        self.assertIn("take it over", text)

    def test_a_stale_claim_counts_as_waiting(self):
        text = said(run([desk(1)]))
        self.assertIn('"working"', text)
        self.assertIn("more than 5 minutes old", text)
        self.assertIn('"session" is another session\'s', text)

    def test_own_claim_is_waiting_after_resume(self):
        # claude --resume keeps the session id, so a rule that skipped this
        # session's own claims left the resumed session unable to answer them.
        text = said(run([desk(1)]))
        self.assertIn('"session" is this session\'s own, whatever its age', text)
        self.assertIn("claude --resume keeps the session id", text)

    def test_collect_instruction_names_each_desk_by_repo_and_pr(self):
        # A bare number resolves to whichever request the conversation is about,
        # which can be the same number in another repository.
        text = said(run([desk(2), desk(5), desk(7, "2026-09-10T00:00:00Z")]))
        self.assertIn("/review-collect o/r#2", text)
        self.assertIn("/review-collect o/r#5", text)
        self.assertNotIn("/review-collect o/r#7", text)
        mine = text.split("more review desk")[0]
        for arg in re.findall(r"/review-collect (\S+)", mine):
            self.assertRegex(arg, r"^o/r#\d+\b", mine)

    def test_waiting_messages_are_answered_before_collecting(self):
        text = said(run([desk(2)]))
        self.assertLess(text.index("Messages still waiting"), text.index("/review-collect o/r#2"))
        self.assertIn("before collecting any decision", text)

    def test_stored_repo_must_match_the_entry(self):
        text = said(run([desk(2)]))
        self.assertIn('"repo" field', text)

    def test_unreadable_ledger_is_reported_not_swallowed(self):
        done = run("{not json")
        self.assertEqual(done.returncode, 0)
        self.assertIn("could not be read", said(done))

    def test_malformed_entries_are_skipped(self):
        text = said(run(["junk", {"repo": "o/r"}, desk(3)]))
        self.assertIn("o/r#3", text)
        self.assertEqual(sum(l.startswith("- o/r#") for l in text.splitlines()), 1)

    def test_hand_edited_shapes_are_skipped_without_a_traceback(self):
        # A repo that is a list or dict reached sweep.message, which counted it
        # as a dict key and crashed the SessionStart hook with a TypeError.
        def entries(cwd):
            bad = [
                dict(desk(11), repo=["o", "r"]), dict(desk(12), repo={"o": "r"}),
                dict(desk(13), repo=42), dict(desk(14), repo="no-slash"),
                dict(desk(15), pr="12"), dict(desk(16), pr=-1), dict(desk(17), pr=True),
                dict(desk(18), url=42),
                # Launched here, so a well-formed one would be listed in full.
                dict(desk(19), repo=["o", "r"], cwd=cwd),
            ]
            return bad + [desk(3)] + [dict(e, repo="o/a") for e in bad if e["repo"] == "o/r"]
        for origin in ("https://github.com/o/r.git", None):
            with self.subTest(origin=origin):
                done = run(entries, origin=origin)
                self.assertEqual((done.returncode, done.stderr), (0, ""))
                text = said(done)
                if origin:
                    self.assertIn("- o/r#3 https://x/3 [watch]", text)
                    self.assertEqual([l for l in text.splitlines() if l.startswith("- ")
                                      and "https://x/" in l], ["- o/r#3 https://x/3 [watch]"])
                else:
                    self.assertIn("1 more review desk waits", text)
                for n in range(11, 20):
                    self.assertNotIn(f"https://x/{n}", text)
                    self.assertNotIn(f"#{n}", text)

    def test_no_json_ledger_content_raises(self):
        values = [None, True, 0, -1, 1.5, "", "x", "o/r", [], ["o", "r"], {}, {"a": 1}]
        fields = ("repo", "pr", "url", "cwd", "collectedAt", "outcome")
        entries = [dict(desk(2), **{field: v}) for field in fields for v in values]
        texts = [json.dumps(v) for v in (entries, entries + values, {"repo": "o/r"}, 7, "o/r", None)]
        # Valid JSON nested past Python's recursion limit.
        texts.append("[" * 100000 + "]" * 100000)
        for text in texts:
            with self.subTest(ledger=text[:60]):
                done = run(text)
                self.assertEqual((done.returncode, done.stderr), (0, ""))


class HooksJson(unittest.TestCase):
    def test_sweep_runs_on_startup_and_resume_only(self):
        # /clear and /compact also fire SessionStart; a sweep there would send a
        # session back through every desk in the middle of its work.
        with open(HOOKS_JSON, encoding="utf-8") as f:
            hooks = json.load(f)["hooks"]
        self.assertEqual([h.get("matcher") for h in hooks["SessionStart"]], ["startup|resume"])
        self.assertEqual([h.get("matcher") for h in hooks["PostToolUse"]], ["Bash"])

    def test_after_push_also_runs_when_the_command_fails(self):
        # Seen on the real host: a Bash command that exits non-zero fires
        # PostToolUseFailure and not PostToolUse, and `git push && <failing step>`
        # has still pushed.
        with open(HOOKS_JSON, encoding="utf-8") as f:
            hooks = json.load(f)["hooks"]
        self.assertEqual(hooks["PostToolUseFailure"], hooks["PostToolUse"])


if __name__ == "__main__":
    unittest.main()
