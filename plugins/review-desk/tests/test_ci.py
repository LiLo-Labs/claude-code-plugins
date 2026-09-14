"""review-desk's CI is only a signal if its workflow's conclusion is about
review-desk alone and it runs everything. These checks hold that shape, so a
job moved back into the shared tests.yml, a lost paths filter, or a WebKit
run narrowed to one suite fails here instead of passing quietly.

Text checks, not a YAML parse: setup-python's interpreter has no PyYAML, and
the suites here run with the standard library only."""
import json
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
WORKFLOWS = os.path.join(ROOT, "..", "..", ".github", "workflows")
OWN = os.path.join(WORKFLOWS, "review-desk.yml")
SHARED = os.path.join(WORKFLOWS, "tests.yml")
PATHS = ["'plugins/review-desk/**'", "'.github/workflows/review-desk.yml'"]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def jobs(text):
    return re.findall(r"^  ([\w-]+):", text.split("\njobs:\n", 1)[1], re.M)


class Workflow(unittest.TestCase):
    def test_triggers_on_pull_request_and_main_only_for_review_desk_paths(self):
        on = read(OWN).split("\non:\n", 1)[1].split("\njobs:\n", 1)[0]
        push, pull = on.split("  pull_request:\n")
        self.assertIn("  push:\n    branches: [main]\n", push)
        for block in (push, pull):
            listed = re.findall(r"^      - (.+)$", block, re.M)
            self.assertEqual(listed, PATHS)

    def test_holds_only_the_review_desk_jobs(self):
        self.assertEqual(jobs(read(OWN)), ["review-desk", "review-desk-page"])

    def test_shared_workflow_no_longer_runs_review_desk(self):
        self.assertNotIn("review-desk", jobs(read(SHARED)))
        self.assertNotIn("review-desk-page", jobs(read(SHARED)))

    def test_runs_every_python_suite_and_both_engines(self):
        text = read(OWN)
        self.assertIn('for t in tests/test_*.py; do', text)
        self.assertIn("run: npm test\n", text)
        self.assertIn("run: npm run test:webkit\n", text)
        self.assertIn("npx playwright install --with-deps chromium webkit", text)


class Scripts(unittest.TestCase):
    def test_webkit_runs_the_same_suites_as_chromium(self):
        scripts = json.loads(read(os.path.join(ROOT, "package.json")))["scripts"]
        self.assertEqual(scripts["test"], "node --test tests/desk/*.test.mjs")
        self.assertEqual(scripts["test:webkit"], "DESK_BROWSER=webkit " + scripts["test"])


if __name__ == "__main__":
    unittest.main()
