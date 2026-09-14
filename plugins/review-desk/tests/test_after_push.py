"""The after-push reminder, run as the hook runs it: a subprocess fed the tool
event on stdin, with HOME and a throwaway git repository in a scratch directory.
Nothing is pushed; the hook only reads the command it is shown."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(__file__), "..", "hooks", "after_push.py")


class AfterPush(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.work = os.path.join(self.home, "work")
        self.repo = os.path.join(self.work, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.remote("https://github.com/o/r.git")
        self.ledger([
            {"repo": "o/r", "pr": 7, "url": "https://x/7", "collectedAt": None},
            {"repo": "o/r", "pr": 5, "url": "https://x/5", "collectedAt": "2026-09-01T00:00:00Z"},
            {"repo": "o/other", "pr": 9, "url": "https://x/9", "collectedAt": None},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def remote(self, url):
        subprocess.run(["git", "-C", self.repo, "remote", "remove", "origin"],
                       capture_output=True)
        subprocess.run(["git", "-C", self.repo, "remote", "add", "origin", url], check=True)

    def ledger(self, entries):
        with open(os.path.join(self.home, ".review-desks.json"), "w") as f:
            json.dump(entries, f)

    def run_hook(self, command, cwd=None, event_name="PostToolUse"):
        event = {"hook_event_name": event_name, "tool_name": "Bash",
                 "tool_input": {"command": command}, "cwd": cwd or self.repo}
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event),
                              env=dict(os.environ, HOME=self.home),
                              capture_output=True, text=True, timeout=10)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        return done.stdout

    def said(self, out):
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def test_not_a_push_says_nothing(self):
        for command in [
            "git status",
            "git pull --ff-only",
            # Found by running the hook in a real session: the words alone matched.
            "echo git push",
            'git commit -m "before the git push"',
            'git commit -m "push later"',
            "rtk git status",
            "timeout 60 git fetch",
            "command -v git",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(command), "")

    def test_push_after_other_commands_is_seen(self):
        self.assertIn("#7", self.said(self.run_hook("git add -A && git commit -qm x && git push")))
        self.assertIn("#7", self.said(self.run_hook("GIT_TRACE=0 git push")))
        self.assertIn("#7", self.said(self.run_hook("git add -A\ngit push 2>&1 | tail -3")))

    def test_wrapped_push_is_seen(self):
        # RTK's PreToolUse hook rewrites `git push` before it runs, and PostToolUse
        # is shown the rewritten command.
        for command in [
            "rtk git push",
            "GIT_TRACE=0 rtk git push -q",
            "rtk proxy git push",
            "timeout 60 git push",
            "timeout -s KILL 60 git push",
            'GIT_SSH_COMMAND="ssh -i k" git push',
            "env -u GIT_DIR GIT_TRACE=1 nice -n 5 command git push",
            "git -c core.x=y push",
            "git --no-pager -c a=b push origin HEAD",
        ]:
            with self.subTest(command=command):
                self.assertIn("#7", self.said(self.run_hook(command)))

    def test_push_lists_only_open_desks_for_that_repo(self):
        text = self.said(self.run_hook("git push origin my-branch"))
        self.assertIn("o/r", text)
        self.assertIn("#7 https://x/7", text)
        self.assertNotIn("#5", text)
        self.assertNotIn("#9", text)
        self.assertIn("Changing the desk and the pull request", text)

    def test_instruction_points_at_the_body_not_a_reply(self):
        # The page only draws a session's answer against a message the reviewer
        # sent, and a push from the terminal has none.
        text = self.said(self.run_hook("git push"))
        self.assertIn("context/body", text)
        self.assertIn('"Changed since you opened this"', text)
        self.assertNotIn("reply", text.lower())

    def test_instruction_asks_for_the_head_on_every_push(self):
        # The page stores the head context/body names as decidedOn. A reminder
        # that asked only for the description let a text-only rewrite leave the
        # page on the old commit, and every approval of it was blocked.
        text = self.said(self.run_hook("git push"))
        self.assertIn('context/body as {"text", "head"}', text)
        self.assertIn("--json headRefOid", text)
        self.assertIn("Write head even when the description needs no change", text)
        self.assertNotIn("If this push changed what a desk shows", text)

    def test_push_run_elsewhere_is_resolved_from_cd_and_dash_c(self):
        self.assertIn("#7", self.said(self.run_hook(f"cd {self.repo} && git push", cwd=self.home)))
        self.assertIn("#7", self.said(self.run_hook(f"git -C {self.repo} push", cwd=self.home)))
        self.assertIn("#7", self.said(self.run_hook("cd repo && rtk git push origin HEAD", cwd=self.work)))
        self.assertIn("#7", self.said(self.run_hook("git -c a=b -C repo push", cwd=self.work)))

    def test_cd_after_the_push_does_not_move_it(self):
        self.assertEqual(self.run_hook(f"git push && cd {self.repo}", cwd=self.home), "")

    def test_failed_command_answers_as_the_event_it_came_from(self):
        out = json.loads(self.run_hook("rtk git push && false", event_name="PostToolUseFailure"))
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUseFailure")
        self.assertIn("#7", out["hookSpecificOutput"]["additionalContext"])

    def test_ssh_remote_is_recognised(self):
        self.remote("git@github.com:o/r.git")
        self.assertIn("#7", self.said(self.run_hook("git push")))

    def add_remote(self, name, url):
        subprocess.run(["git", "-C", self.repo, "remote", "add", name, url], check=True)

    def test_fork_push_reaches_the_upstream_desk(self):
        # origin is the fork; the pull request, and so its desk, is upstream's.
        self.remote("https://github.com/MALathon/accrue.git")
        self.add_remote("upstream", "https://github.com/LiLo-Labs/accrue.git")
        self.ledger([{"repo": "LiLo-Labs/accrue", "pr": 3, "url": "https://x/3",
                      "collectedAt": None}])
        text = self.said(self.run_hook("git push origin feature"))
        self.assertIn("LiLo-Labs/accrue#3 https://x/3", text)

    def test_any_remote_matches_in_ssh_and_https_forms(self):
        for origin, upstream in [
            ("git@github.com:fork/r.git", "https://github.com/o/r.git"),
            ("https://github.com/fork/r.git", "git@github.com:o/r.git"),
            ("https://github.com/fork/r", "ssh://git@github.com/o/r.git"),
            ("git@github.com:fork/r.git", "https://github.com/O/R/"),
        ]:
            with self.subTest(origin=origin, upstream=upstream):
                self.remote(origin)
                subprocess.run(["git", "-C", self.repo, "remote", "remove", "upstream"],
                               capture_output=True)
                self.add_remote("upstream", upstream)
                text = self.said(self.run_hook("git push"))
                self.assertIn("o/r#7 https://x/7", text)
                self.assertNotIn("#9", text)

    def test_push_outside_a_repository_says_nothing(self):
        self.assertEqual(self.run_hook("git push", cwd=self.work), "")

    def test_revising_desk_is_listed_as_open(self):
        # A revision's pushes are exactly the ones that make a desk out of date.
        self.ledger([
            {"repo": "o/r", "pr": 3, "url": "https://x/3",
             "collectedAt": "2026-09-01T00:00:00Z", "outcome": "revising"},
            {"repo": "o/r", "pr": 4, "url": "https://x/4",
             "collectedAt": "2026-09-01T00:00:00Z", "outcome": "merged"},
            {"repo": "o/r", "pr": 6, "url": "https://x/6",
             "collectedAt": "2026-09-01T00:00:00Z", "outcome": "closed"},
        ])
        text = self.said(self.run_hook("git push"))
        self.assertIn("#3 https://x/3", text)
        self.assertNotIn("#4", text)
        self.assertNotIn("#6", text)

    def test_repo_without_open_desks_says_nothing(self):
        self.remote("https://github.com/o/quiet.git")
        self.assertEqual(self.run_hook("git push"), "")

    def test_hand_edited_shapes_are_not_listed(self):
        desk = {"repo": "o/r", "url": "https://x/7", "collectedAt": None}
        bad = [
            dict(desk, pr=11, repo=["o", "r"]), dict(desk, pr=12, repo={"o": "r"}),
            dict(desk, pr=13, repo=42), dict(desk, pr=14, repo="no-slash"),
            dict(desk, pr="15"), dict(desk, pr=-16), dict(desk, pr=True),
            dict(desk, pr=18, url=42),
        ]
        self.ledger(bad + [dict(desk, pr=7)])
        for event_name in ("PostToolUse", "PostToolUseFailure"):
            with self.subTest(event_name=event_name):
                text = self.said(self.run_hook("git push", event_name=event_name))
                self.assertEqual([l for l in text.splitlines() if l.startswith("- ")],
                                 ["- o/r#7 https://x/7"])

    def test_no_json_content_raises(self):
        values = [None, True, 0, -1, 1.5, "", "x", "o/r", [], ["o", "r"], {}, {"a": 1}]
        fields = ("repo", "pr", "url", "cwd", "collectedAt", "outcome")
        fields += ("branch", "head")
        entries = [{"repo": "o/r", "pr": 7, "url": "https://x/7", field: v}
                   for field in fields for v in values]
        for ledger in (entries + values, {"repo": "o/r"}, 7, None):
            with self.subTest(ledger=str(ledger)[:60]):
                self.ledger(ledger)
                self.run_hook("git push")
        with open(os.path.join(self.home, ".review-desks.json"), "w") as f:
            f.write("[" * 100000 + "]" * 100000)
        self.assertEqual(self.run_hook("git push"), "")
        for event in ([], "x", {"tool_input": "git push"}, {"tool_input": {"command": 5}},
                      {"tool_input": {"command": "git push"}, "cwd": 5}):
            with self.subTest(event=event):
                done = subprocess.run([sys.executable, HOOK], input=json.dumps(event),
                                      env=dict(os.environ, HOME=self.home),
                                      capture_output=True, text=True, timeout=10)
                self.assertEqual((done.returncode, done.stderr), (0, ""))

    def checkout(self, branch):
        # An unborn branch is enough: the hook reads the name, never a commit.
        subprocess.run(["git", "-C", self.repo, "symbolic-ref", "HEAD",
                        f"refs/heads/{branch}"], check=True)

    def listed(self, out):
        return [l for l in self.said(out).splitlines() if l.startswith("- ")] if out else []

    def desks_on_a_and_b(self, *extra):
        self.ledger([
            {"repo": "o/r", "pr": 1, "url": "https://x/1", "branch": "a",
             "head": "1" * 40, "collectedAt": None},
            {"repo": "o/r", "pr": 2, "url": "https://x/2", "branch": "b",
             "head": "2" * 40, "collectedAt": None},
            *extra,
        ])

    def test_push_lists_only_the_desk_for_the_branch_pushed(self):
        # Two desks in one repository were listed for every push, so a session
        # could write one pull request's commits onto the other's desk.
        self.desks_on_a_and_b()
        only_b = ["- o/r#2 https://x/2"]
        self.checkout("b")
        for command in [
            "git push",
            "rtk git push",
            "git push origin",
            "git push -u origin HEAD",
            "git push 2>&1 | tail -3",
            "git push >/dev/null 2>&1",
            "git -C repo push",
        ]:
            with self.subTest(on="b", command=command):
                self.assertEqual(self.listed(self.run_hook(command, cwd=self.work
                                                           if "-C" in command else None)), only_b)
        # The refspec names the branch, whatever is checked out.
        self.checkout("a")
        for command in [
            "git push origin b",
            "git push origin HEAD:b",
            "rtk git push origin HEAD:b",
            "GIT_TRACE=0 rtk git push -u origin HEAD:refs/heads/b",
            "git push -o ci.skip --force-with-lease origin +b",
            "git push --repo=origin b",
            "git push origin b 2>&1",
        ]:
            with self.subTest(on="a", command=command):
                self.assertEqual(self.listed(self.run_hook(command)), only_b)
        self.assertEqual(self.listed(self.run_hook("git push")), ["- o/r#1 https://x/1"])

    def test_push_of_another_branch_lists_no_desk(self):
        self.desks_on_a_and_b()
        self.checkout("c")
        self.assertEqual(self.run_hook("git push"), "")
        self.assertEqual(self.run_hook("git push origin v1.0 refs/tags/v1.0"), "")

    def test_push_whose_branches_cannot_be_told_lists_every_desk(self):
        self.desks_on_a_and_b()
        both = ["- o/r#1 https://x/1", "- o/r#2 https://x/2"]
        self.checkout("b")
        for command in [
            "git push --all", "git push --mirror origin",
            "git push origin 'refs/heads/*:refs/heads/*'", "git push origin a b",
            # The hook sees a shell expansion unexpanded. Read as a branch name it
            # matched no desk and the push of b went unreminded.
            'git push -u origin "$(git branch --show-current)"',
            "git push -u origin $(git branch --show-current)",
            'rtk git push origin "$BRANCH"',
            "git push origin $BRANCH",
            'git push origin HEAD:"${BRANCH}"',
            "git push origin `git rev-parse --abbrev-ref HEAD`",
            'git push origin "HEAD:`git branch --show-current`"',
            # An empty refspec, and `:`, which pushes every matching branch.
            'git push origin ""',
            "git push origin :",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.listed(self.run_hook(command)), both)
        # A detached HEAD names no branch; `git push` there is left to git.
        with open(os.path.join(self.repo, ".git", "HEAD"), "w") as f:
            f.write("1" * 40 + "\n")
        self.assertEqual(self.listed(self.run_hook("git push")), both)
        self.assertEqual(self.listed(self.run_hook("git push origin b")), ["- o/r#2 https://x/2"])

    def test_every_push_in_one_command_lists_its_desks(self):
        # Only the first push was read, so pushing two stacked branches in one
        # line dropped the second one's desk.
        self.desks_on_a_and_b()
        self.checkout("c")
        both = ["- o/r#1 https://x/1", "- o/r#2 https://x/2"]
        for command in [
            "git push origin a && git push origin b",
            "rtk git push origin b; git checkout a && git push origin HEAD:a",
            "git push origin b\ngit push origin a",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.listed(self.run_hook(command)), both)
        self.assertEqual(self.listed(self.run_hook("git push origin c && git push origin b")),
                         ["- o/r#2 https://x/2"])
        # A second push from a directory with no remote adds nothing and hides nothing.
        self.assertEqual(self.listed(self.run_hook(
            f"git push origin b && cd {self.work} && git push origin a")),
            ["- o/r#2 https://x/2"])

    def test_entry_without_a_branch_is_listed_for_any_push(self):
        # Ledgers written before branch was recorded keep their reminder.
        self.desks_on_a_and_b(
            {"repo": "o/r", "pr": 3, "url": "https://x/3", "collectedAt": None},
            {"repo": "o/r", "pr": 4, "url": "https://x/4", "branch": None, "head": None,
             "collectedAt": None},
        )
        self.checkout("b")
        self.assertEqual(self.listed(self.run_hook("git push")),
                         ["- o/r#2 https://x/2", "- o/r#3 https://x/3", "- o/r#4 https://x/4"])

    def test_entry_with_a_branch_or_head_that_is_not_a_string_is_ignored(self):
        desk = {"repo": "o/r", "url": "https://x", "collectedAt": None}
        self.ledger([
            dict(desk, pr=11, branch=["b"]), dict(desk, pr=12, branch=5),
            dict(desk, pr=13, branch={"b": 1}), dict(desk, pr=14, branch=True),
            dict(desk, pr=15, branch="b", head=7), dict(desk, pr=16, head=["x"]),
            dict(desk, pr=2, url="https://x/2", branch="b", head="2" * 40),
        ])
        self.checkout("b")
        for command in ("git push", "git push origin HEAD:b", "git push --all"):
            with self.subTest(command=command):
                # run_hook asserts exit 0 and an empty stderr, so no traceback.
                self.assertEqual(self.listed(self.run_hook(command)), ["- o/r#2 https://x/2"])

    def test_instruction_computes_the_changelog_from_the_recorded_head(self):
        text = self.said(self.run_hook("git push"))
        self.assertIn("<head>..origin/<branch>", text)
        self.assertIn("as the desk's entry in ~/.review-desks.json records them", text)
        self.assertIn("keep the lines that section already has", text)
        self.assertIn("Once that write has landed, set the entry's head to the headRefOid it wrote",
                      text)

    def test_missing_ledger_says_nothing(self):
        os.remove(os.path.join(self.home, ".review-desks.json"))
        self.assertEqual(self.run_hook("git push"), "")


if __name__ == "__main__":
    unittest.main()
