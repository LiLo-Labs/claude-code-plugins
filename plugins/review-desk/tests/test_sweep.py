"""The session-start sweep, run as the hook runs it: a subprocess with HOME
pointed at a scratch directory. No dependencies beyond the standard library."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SWEEP = os.path.join(os.path.dirname(__file__), "..", "hooks", "sweep.py")


def run(ledger):
    """Run the sweep against `ledger` (None: no file; str: raw text; else JSON)."""
    with tempfile.TemporaryDirectory() as home:
        if ledger is not None:
            with open(os.path.join(home, ".review-desks.json"), "w") as f:
                f.write(ledger if isinstance(ledger, str) else json.dumps(ledger))
        env = dict(os.environ, HOME=home)
        done = subprocess.run([sys.executable, SWEEP], env=env,
                              capture_output=True, text=True, timeout=10)
    return done


def desk(n, collected=None):
    return {"repo": "o/r", "pr": n, "url": f"https://x/{n}", "collectedAt": collected}


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

    def test_watch_marks_only_the_newest_five(self):
        text = said(run([desk(n) for n in range(1, 8)]))
        self.assertNotIn("[watch]", next(l for l in text.splitlines() if "#2 " in l))
        for n in range(3, 8):
            self.assertIn("[watch]", next(l for l in text.splitlines() if f"#{n} " in l))

    def test_unreadable_ledger_is_reported_not_swallowed(self):
        done = run("{not json")
        self.assertEqual(done.returncode, 0)
        self.assertIn("could not be read", said(done))

    def test_malformed_entries_are_skipped(self):
        text = said(run(["junk", {"repo": "o/r"}, desk(3)]))
        self.assertIn("o/r#3", text)
        self.assertEqual(sum(l.startswith("- o/r#") for l in text.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
