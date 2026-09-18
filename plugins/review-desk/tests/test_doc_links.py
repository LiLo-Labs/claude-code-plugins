"""The hooks and the command docs send sessions to sections by name. The hook
tests only check the hooks' own strings, so a renamed heading would leave a
session pointed at a section that no longer exists while every other test
passed. The commands cite one another's sections too, so a named section must
exist in one of them, not only in /review-desk."""
import ast
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
COMMANDS = os.path.join(ROOT, "commands")
DOC = os.path.join(COMMANDS, "review-desk.md")
UNDER = re.compile(r'under "([^"]+)"')


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def strings(path):
    """Every string constant in a Python file. Adjacent literals arrive joined,
    so a phrase wrapped across two source lines is still found whole."""
    tree = ast.parse(read(path))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)]


class DocLinks(unittest.TestCase):
    def assert_sections_exist(self, texts, source, at_least):
        phrases = [p for text in texts for p in UNDER.findall(text)]
        # Guards against a pass that checked nothing because the wording moved.
        self.assertGreaterEqual(len(phrases), at_least, f"{source}: {phrases}")
        headings = set()
        for name in sorted(os.listdir(COMMANDS)):
            if name.endswith(".md"):
                headings |= set(re.findall(r"^#{2,3} (.+?)\s*$", read(os.path.join(COMMANDS, name)), re.M))
        missing = sorted(set(phrases) - headings)
        self.assertEqual(missing, [], f"{source} names sections no command doc has")

    def test_sweep_names_real_sections(self):
        # One, not two: the sweep used to send a session to the ring protocol as
        # well, and there is no ring protocol.
        self.assert_sections_exist(strings(os.path.join(ROOT, "hooks", "sweep.py")),
                                   "hooks/sweep.py", 1)

    def test_after_push_names_real_sections(self):
        self.assert_sections_exist(strings(os.path.join(ROOT, "hooks", "after_push.py")),
                                   "hooks/after_push.py", 1)

    def test_command_docs_name_real_sections(self):
        for name in sorted(os.listdir(COMMANDS)):
            if not name.endswith(".md"):
                continue
            with self.subTest(doc=name):
                text = " ".join(read(os.path.join(COMMANDS, name)).split())
                # Only /review-desk is long enough to guarantee a citation.
                self.assert_sections_exist([text], "commands/" + name,
                                           1 if name == "review-desk.md" else 0)


README = os.path.join(ROOT, "README.md")
SKILL = os.path.join(ROOT, "skills", "review-desk", "SKILL.md")


def flat(path):
    return " ".join(read(path).split())


class ReaderDocs(unittest.TestCase):
    """README.md and SKILL.md are what a person and a model read first. They
    restated behaviour the command docs and hooks later changed, so they are
    held to the parts a reader acts on."""

    def test_collect_is_always_shown_with_its_repository(self):
        # A bare number resolves to whatever request the conversation is about,
        # and the same number in another repository then gets the comment and
        # the merge.
        for path in (README, SKILL):
            with self.subTest(path=os.path.basename(path)):
                args = re.findall(r"/review-collect\s+(\S+)", read(path))
                self.assertTrue(args, path)
                for arg in args:
                    self.assertRegex(arg, r"^`?<?[\w.-]*owner/repo>?#|^[\w.-]+/[\w.-]+#\d+", arg)
                self.assertEqual(re.findall(r"/review-collect\s+<?(?:\d+|n|pr|number)\b", read(path)), [])
                self.assertIn("bare number", flat(path))

    def test_hooks_are_described_as_matching_any_git_remote_and_the_launch_directory(self):
        text = flat(README)
        self.assertGreaterEqual(text.count("any git remote"), 2, "after-push and session-start")
        self.assertIn("launch directory", text)
        for stale in ("for that repository", "for the repository a session starts"):
            self.assertNotIn(stale, text)
        self.assertIn("any git remote", flat(SKILL))

    def test_lifecycle_matches_the_command_docs(self):
        for path in (README, SKILL):
            with self.subTest(path=os.path.basename(path)):
                text = flat(path)
                stamps = [s for s in re.split(r"(?<=[.;:])\s", text) if "collectedAt" in s]
                self.assertTrue(stamps, path)
                for sentence in stamps:
                    self.assertRegex(sentence, r"only when [^.]*merged or closed", sentence)
                self.assertIn("every message still waiting before", text)


if __name__ == "__main__":
    unittest.main()
