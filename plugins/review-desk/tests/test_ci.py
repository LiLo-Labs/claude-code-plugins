"""review-desk's CI is only a signal if its workflow's conclusion is about
review-desk alone and it runs everything. These checks hold that shape, so a
job moved into another plugin's workflow, a lost paths filter, or a WebKit run
narrowed to one suite fails here instead of passing quietly.

They also hold the shape of the repository's CI, which review-desk's own
conclusion depends on: one workflow per plugin, each filtered to its own paths,
so a review-desk pull request neither waits on another plugin's suite nor is
turned red by it. That is what the shared tests.yml did until it was split up.

Text checks, not a YAML parse: setup-python's interpreter has no PyYAML, and
the suites here run with the standard library only."""
import json
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
WORKFLOWS = os.path.join(ROOT, "..", "..", ".github", "workflows")
OWN = os.path.join(WORKFLOWS, "review-desk.yml")
# Workflows that are about the repository rather than one plugin.
REPO_WIDE = {"repo.yml"}
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

    def test_no_other_workflow_runs_review_desk(self):
        # A job in someone else's workflow would put review-desk's result under
        # a conclusion that is not review-desk's.
        for name in sorted(os.listdir(WORKFLOWS)):
            if name == "review-desk.yml" or not name.endswith(".yml"):
                continue
            text = read(os.path.join(WORKFLOWS, name))
            self.assertNotIn("plugins/review-desk", text, name)
            for job in jobs(text):
                self.assertNotIn("review-desk", job, name)

    def test_every_plugin_workflow_is_one_plugin_and_filtered(self):
        # The shape that keeps each conclusion meaningful: a workflow named for
        # its plugin, triggered only by that plugin's paths and its own file.
        seen = 0
        for name in sorted(os.listdir(WORKFLOWS)):
            if not name.endswith(".yml") or name in REPO_WIDE:
                continue
            seen += 1
            plugin = name[:-len(".yml")]
            text = read(os.path.join(WORKFLOWS, name))
            self.assertTrue(os.path.isdir(os.path.join(ROOT, "..", plugin)),
                            name + " names no plugin directory")
            on = text.split("\non:\n", 1)[1].split("\njobs:\n", 1)[0]
            push, pull = on.split("  pull_request:\n")
            self.assertIn("  push:\n    branches: [main]\n", push, name)
            for block in (push, pull):
                self.assertEqual(re.findall(r"^      - (.+)$", block, re.M),
                                 ["'plugins/%s/**'" % plugin,
                                  "'.github/workflows/%s'" % name], name)
        self.assertGreaterEqual(seen, 6, "every plugin with tests has a workflow")

    def test_every_plugin_with_tests_has_a_workflow(self):
        # A plugin whose suite no job runs is a suite nobody runs: notes and
        # code-canvas both sat like that, passing locally and never in CI.
        plugins = os.path.join(ROOT, "..")
        for plugin in sorted(os.listdir(plugins)):
            tests = os.path.join(plugins, plugin, "tests")
            package = os.path.join(plugins, plugin, "package.json")
            has_tests = os.path.isdir(tests) and any(
                f.startswith("test") or f == "desk" for f in os.listdir(tests))
            if not has_tests and os.path.exists(package):
                has_tests = '"test"' in read(package)
            if has_tests:
                self.assertTrue(os.path.exists(os.path.join(WORKFLOWS, plugin + ".yml")),
                                plugin + " has tests and no workflow")

    def test_the_marketplace_check_runs_on_everything(self):
        # It guards the version a user actually installs, and any change can move
        # a version, so it is not paths-filtered.
        text = read(os.path.join(WORKFLOWS, "repo.yml"))
        self.assertIn("check_marketplace.py", text)
        self.assertNotIn("paths:", text)

    def test_runs_every_python_suite_and_both_engines(self):
        text = read(OWN)
        self.assertIn('for t in tests/test_*.py; do', text)
        self.assertIn("run: npm test\n", text)
        self.assertIn("run: npm run test:webkit\n", text)
        self.assertIn("npx playwright install --with-deps chromium webkit", text)


class Scripts(unittest.TestCase):
    # WebKit skips only the two 270 KiB "too large" storage tests, which time out
    # on ubuntu WebKit (see review-desk.yml). Pinned exactly so the exclusion
    # cannot quietly widen to other tests or files.
    WEBKIT_SKIP = "--test-skip-pattern='too large' "

    def test_page_job_runs_a_node_that_has_test_skip_pattern(self):
        version = re.search(r'node-version: "(\d+)"', read(OWN)).group(1)
        self.assertGreaterEqual(int(version), 22)

    def test_webkit_runs_the_same_suites_as_chromium(self):
        scripts = json.loads(read(os.path.join(ROOT, "package.json")))["scripts"]
        self.assertEqual(scripts["test"], "node --test tests/desk/*.test.mjs")
        self.assertEqual(
            scripts["test:webkit"],
            "DESK_BROWSER=webkit node --test " + self.WEBKIT_SKIP + "tests/desk/*.test.mjs")

    def test_webkit_skip_names_only_the_two_oversized_storage_tests(self):
        titles = []
        desk = os.path.join(ROOT, "tests", "desk")
        for name in sorted(os.listdir(desk)):
            if name.endswith(".test.mjs"):
                titles += [(name, t) for t in re.findall(r"^test\('([^']+)'", read(os.path.join(desk, name)), re.M)]
        skipped = [(f, t) for f, t in titles if re.search("too large", t)]
        self.assertEqual([f for f, _ in skipped], ["storage.test.mjs", "storage.test.mjs"])
        self.assertGreater(len(titles), 60)


if __name__ == "__main__":
    unittest.main()
