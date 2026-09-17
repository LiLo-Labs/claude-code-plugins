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

# User settings that allow the merge, so tests about the desk list do not also
# get the unattended-merge line.
ALLOWED = {"permissions": {"allow": ["Bash(gh pr merge *)"]}}
ADVICE = "Unattended merges are not allowed here"


def put(path, content):
    """None: no file; a callable is given the path and makes whatever it likes;
    str: raw text; else JSON."""
    if content is None:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if callable(content):
        content(path)
        return
    with open(path, "w") as f:
        f.write(content if isinstance(content, str) else json.dumps(content))


def run(ledger, origin="https://github.com/o/r.git", remotes=None,
        settings=ALLOWED, project=None, local=None):
    """Run the sweep against `ledger` (None: no file; str: raw text; a callable
    is given the session directory and returns the ledger; else JSON) from a
    repository whose remotes are `remotes`, a name-to-URL dict, or else whose
    origin is `origin` (None for both: not a repository). `settings`,
    `project` and `local` are the user, shared project and local project
    settings files, as `put` takes them."""
    with tempfile.TemporaryDirectory() as home:
        cwd = os.path.join(home, "session")
        os.makedirs(cwd)
        if callable(ledger):
            ledger = ledger(cwd)
        if ledger is not None:
            with open(os.path.join(home, ".review-desks.json"), "w") as f:
                f.write(ledger if isinstance(ledger, str) else json.dumps(ledger))
        put(os.path.join(home, ".claude", "settings.json"), settings)
        put(os.path.join(cwd, ".claude", "settings.json"), project)
        put(os.path.join(cwd, ".claude", "settings.local.json"), local)
        if remotes is None:
            remotes = {"origin": origin} if origin else {}
        if remotes:
            subprocess.run(["git", "init", "-q", cwd], check=True)
            for name, url in remotes.items():
                subprocess.run(["git", "-C", cwd, "remote", "add", name, url], check=True)
        event = {"hook_event_name": "SessionStart", "source": "startup", "cwd": cwd}
        env = dict(os.environ, HOME=home)
        env.pop("CLAUDE_CONFIG_DIR", None)
        done = subprocess.run([sys.executable, SWEEP], input=json.dumps(event),
                              env=env, capture_output=True, text=True, timeout=10)
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
    def test_every_desk_read_is_stamped_in_the_same_batch(self):
        # The stamp is the only thing the reviewer sees, and a session whose
        # context never held /review-desk cannot follow a pointer to it: the
        # write itself has to be here. Desks accrue#9 and accrue-scratch#4 were
        # both collected and merged with an empty presence collection, so their
        # pages showed nobody home while the merge was going through.
        text = " ".join(said(run([desk(2)])).split())
        self.assertIn('collection "review/pr-<number>/presence"', text)
        self.assertIn('data {"resume": "cd <this session\'s directory> && '
                      "claude --resume <this session's id>\"}", text)
        self.assertIn("before you know whether anything is waiting", text)
        self.assertNotIn('as /review-desk describes under "Whenever a ring arrives"', text)
        # It goes out with the reads, not after the collect instruction.
        self.assertLess(text.index("/presence"), text.index("Only then collect"))

    def test_desk_work_runs_on_the_first_turn_and_says_so_before_a_merge(self):
        # SessionStart only adds context; a resumed session does nothing until
        # someone types, and what they type may be about something else.
        text = " ".join(said(run([desk(2)])).split())
        self.assertNotIn("Before the user's first request", text)
        self.assertIn("this runs on the session's first turn", text)
        self.assertIn("Before any merge, tell the user in one line which pull request", text)
        self.assertLess(text.index("Before any merge"), text.index("Say in one line what you found"))

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
                   ((1, "revising"), (2, "blocked"), (3, "merged"), (4, "closed"), (5, None),
                    (6, "revised"))]
        text = said(run(entries))
        self.assertIn("o/r#1 https://x/1", text)
        self.assertIn("o/r#2 https://x/2", text)
        # A revision pushed and reported waits for the reviewer's next decision.
        self.assertIn("o/r#6 https://x/6", text)
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


def advice(done):
    """The unattended-merge lines the sweep said, after checking it exited
    cleanly."""
    assert (done.returncode, done.stderr) == (0, ""), (done.returncode, done.stderr)
    if not done.stdout:
        return []
    return [l for l in said(done).splitlines() if ADVICE in l]


class UnattendedMerges(unittest.TestCase):
    # Seen on the real host: an approval's gh pr merge was refused by auto
    # mode's classifier, and nothing told the user a permission rule allows it.

    def test_an_allow_rule_covering_the_merge_is_silent(self):
        for rule in ("Bash(gh pr merge *)", "Bash(gh pr merge:*)", "Bash(gh pr *)", "Bash(gh *)"):
            with self.subTest(rule=rule):
                self.assertEqual(advice(run([desk(1)], settings={"permissions": {"allow": [rule]}})), [])

    def test_a_rule_in_project_settings_is_silent(self):
        for where in ("project", "local"):
            with self.subTest(where=where):
                done = run([desk(1)], settings=None, **{where: ALLOWED})
                self.assertEqual(advice(done), [])

    def test_no_rule_with_an_open_desk_gives_one_line_naming_the_rule(self):
        for settings in (None, {}, {"permissions": {"allow": ["Bash(gh pr view *)"]}}):
            with self.subTest(settings=settings):
                lines = advice(run([desk(1)], settings=settings))
                self.assertEqual(len(lines), 1)
                self.assertIn("`Bash(gh pr merge *)`", lines[0])
                self.assertNotIn("rtk", lines[0])
                self.assertIn('README section "Unattended merges"', lines[0])
                self.assertIn("Do not add the rule or change any settings file yourself", lines[0])

    def test_an_open_desk_in_another_repository_still_gets_the_line(self):
        self.assertEqual(len(advice(run([desk(1, repo="o/a")], settings=None))), 1)

    def test_rules_auto_mode_drops_or_that_do_not_match_give_the_line(self):
        for rule in ("Bash", "Bash(*)", "Bash(gh pr merge)", "Bash(* --squash)", "Bash(gh pr merge 2 *)",
                     "Bash(git merge *)", "Read", 42):
            with self.subTest(rule=rule):
                lines = advice(run([desk(1)], settings={"permissions": {"allow": [rule]}}))
                self.assertEqual(len(lines), 1)

    def test_rtk_rewriting_hook_needs_the_rewritten_rule(self):
        # Claude Code matches rules against the command the PreToolUse hook
        # returns, and RTK's hook turns `gh pr merge` into `rtk gh pr merge`.
        hooks = {"PreToolUse": [{"matcher": "Bash",
                                 "hooks": [{"type": "command", "command": "rtk hook claude"}]}]}
        lines = advice(run([desk(1)], settings={"hooks": hooks,
                                                "permissions": {"allow": ["Bash(gh pr merge *)"]}}))
        self.assertEqual(len(lines), 1)
        self.assertIn("`Bash(rtk gh pr merge *)`", lines[0])
        self.assertNotIn("`Bash(gh pr merge *)`", lines[0])
        both = {"hooks": hooks, "permissions": {"allow": ["Bash(gh pr merge *)", "Bash(rtk gh pr merge *)"]}}
        self.assertEqual(advice(run([desk(1)], settings=both)), [])
        neither = advice(run([desk(1)], settings={"hooks": hooks}))
        self.assertIn("`Bash(gh pr merge *)` and `Bash(rtk gh pr merge *)`", neither[0])

    def test_classify_all_shell_suspends_the_rule(self):
        settings = dict(ALLOWED, autoMode={"classifyAllShell": True})
        lines = advice(run([desk(1)], settings=settings))
        self.assertEqual(len(lines), 1)
        self.assertIn("classifyAllShell", lines[0])
        # Claude Code reads autoMode only from user settings.
        self.assertEqual(advice(run([desk(1)], project={"autoMode": {"classifyAllShell": True}})), [])

    def test_a_deny_or_ask_rule_is_the_users_choice_and_silent(self):
        for key, rule in (("ask", "Bash(gh pr merge *)"), ("deny", "Bash(gh pr *)"), ("ask", "Bash")):
            with self.subTest(key=key, rule=rule):
                self.assertEqual(advice(run([desk(1)], settings={"permissions": {key: [rule]}})), [])

    def test_a_leading_wildcard_deny_or_ask_rule_counts_only_when_it_matches(self):
        # A deny or ask rule like `Bash(* --force)` does not stop `gh pr merge ...
        # --squash`, so it must not silence the advice as if it did.
        for key, rule in (("deny", "Bash(* --force)"), ("ask", "Bash(*sudo*)"), ("deny", "Bash(*rm -rf*)")):
            with self.subTest(key=key, rule=rule):
                self.assertEqual(len(advice(run([desk(1)], settings={"permissions": {key: [rule]}}))), 1)
        for key, rule in (("deny", "Bash(* --squash)"), ("ask", "Bash(*pr merge*)"), ("ask", "Bash(*)")):
            with self.subTest(key=key, rule=rule):
                self.assertEqual(advice(run([desk(1)], settings={"permissions": {key: [rule]}})), [])

    def test_the_advice_names_claude_config_dir_when_it_is_set(self):
        with tempfile.TemporaryDirectory() as config:
            put(os.path.join(config, "settings.json"), {})
            with tempfile.TemporaryDirectory() as home:
                cwd = os.path.join(home, "s")
                os.makedirs(cwd)
                with open(os.path.join(home, ".review-desks.json"), "w") as f:
                    json.dump([desk(1)], f)
                env = dict(os.environ, HOME=home, CLAUDE_CONFIG_DIR=config)
                done = subprocess.run([sys.executable, SWEEP], env=env, capture_output=True, text=True,
                                      input=json.dumps({"cwd": cwd}), timeout=10)
                lines = advice(done)
        self.assertEqual(len(lines), 1)
        self.assertIn(os.path.join(config, "settings.json"), lines[0])
        self.assertNotIn("~/.claude/settings.json", lines[0])

    def test_no_open_desk_is_silent(self):
        for ledger in (None, [], [desk(1, "2026-09-10T00:00:00Z")]):
            with self.subTest(ledger=ledger):
                done = run(ledger, settings=None)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))

    def test_malformed_or_unreadable_settings_are_silent(self):
        def fifo(path):
            os.mkfifo(path)

        def directory(path):
            os.makedirs(path)

        def huge(path):
            with open(path, "w") as f:
                f.write(json.dumps({"x": "y" * (2 << 20)}))

        cases = {
            "not json": "{nope",
            "not an object": "[]",
            "permissions a list": {"permissions": ["Bash(gh pr merge *)"]},
            "allow a string": {"permissions": {"allow": "Bash(gh pr merge *)"}},
            "deep nesting": "[" * 100000 + "]" * 100000,
            "not utf-8": b"\xff\xfe{}".decode("latin-1"),
            "a directory": directory,
            "over the size cap": huge,
        }
        if hasattr(os, "mkfifo"):
            cases["a fifo"] = fifo
        for name, settings in cases.items():
            with self.subTest(settings=name):
                done = run([desk(1)], settings=settings)
                self.assertEqual(advice(done), [])
                self.assertIn("o/r#1", said(done))
        # A malformed project file silences it even when user settings lack the rule.
        self.assertEqual(advice(run([desk(1)], settings=None, local="{nope")), [])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads a mode-000 file")
    def test_a_settings_file_without_read_permission_is_silent(self):
        def locked(path):
            with open(path, "w") as f:
                f.write("{}")
            os.chmod(path, 0)

        self.assertEqual(advice(run([desk(1)], settings=locked)), [])

    def test_claude_config_dir_is_where_user_settings_are_read(self):
        with tempfile.TemporaryDirectory() as config:
            put(os.path.join(config, "settings.json"), ALLOWED)
            with tempfile.TemporaryDirectory() as home:
                cwd = os.path.join(home, "s")
                os.makedirs(cwd)
                with open(os.path.join(home, ".review-desks.json"), "w") as f:
                    json.dump([desk(1)], f)
                env = dict(os.environ, HOME=home, CLAUDE_CONFIG_DIR=config)
                done = subprocess.run([sys.executable, SWEEP], env=env, capture_output=True, text=True,
                                      input=json.dumps({"cwd": cwd}), timeout=10)
        self.assertEqual(advice(done), [])


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
