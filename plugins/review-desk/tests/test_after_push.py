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
        self.repo = os.path.join(self.home, "work", "plugins")
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

    def run_hook(self, command, cwd=None):
        event = {"tool_name": "Bash", "tool_input": {"command": command},
                 "cwd": cwd or self.repo}
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event),
                              env=dict(os.environ, HOME=self.home),
                              capture_output=True, text=True, timeout=10)
        self.assertEqual(done.returncode, 0)
        return done.stdout

    def said(self, out):
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def test_not_a_push_says_nothing(self):
        self.assertEqual(self.run_hook("git status"), "")
        self.assertEqual(self.run_hook("git pull --ff-only"), "")
        # Found by running the hook in a real session: the words alone matched.
        self.assertEqual(self.run_hook("echo git push"), "")
        self.assertEqual(self.run_hook('git commit -m "before the git push"'), "")

    def test_push_after_other_commands_is_seen(self):
        self.assertIn("#7", self.said(self.run_hook("git add -A && git commit -qm x && git push")))
        self.assertIn("#7", self.said(self.run_hook("GIT_TRACE=0 git push")))

    def test_push_lists_only_open_desks_for_that_repo(self):
        text = self.said(self.run_hook("git push origin my-branch"))
        self.assertIn("o/r", text)
        self.assertIn("#7 https://x/7", text)
        self.assertNotIn("#5", text)
        self.assertNotIn("#9", text)
        self.assertIn("Changing the desk and the pull request", text)

    def test_push_run_elsewhere_is_resolved_from_cd_and_dash_c(self):
        self.assertIn("#7", self.said(self.run_hook(f"cd {self.repo} && git push", cwd=self.home)))
        self.assertIn("#7", self.said(self.run_hook(f"git -C {self.repo} push", cwd=self.home)))

    def test_ssh_remote_is_recognised(self):
        self.remote("git@github.com:o/r.git")
        self.assertIn("#7", self.said(self.run_hook("git push")))

    def test_repo_without_open_desks_says_nothing(self):
        self.remote("https://github.com/o/quiet.git")
        self.assertEqual(self.run_hook("git push"), "")

    def test_missing_ledger_says_nothing(self):
        os.remove(os.path.join(self.home, ".review-desks.json"))
        self.assertEqual(self.run_hook("git push"), "")


if __name__ == "__main__":
    unittest.main()
