"""The hooks send sessions to sections of /review-desk by name. The hook tests
only check the hooks' own strings, so a renamed heading would leave a session
pointed at a section that no longer exists while every other test passed."""
import ast
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
DOC = os.path.join(ROOT, "commands", "review-desk.md")
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
        headings = set(re.findall(r"^#{2,3} (.+?)\s*$", read(DOC), re.M))
        missing = sorted(set(phrases) - headings)
        self.assertEqual(missing, [], f"{source} names sections commands/review-desk.md lacks")

    def test_sweep_names_real_sections(self):
        self.assert_sections_exist(strings(os.path.join(ROOT, "hooks", "sweep.py")),
                                   "hooks/sweep.py", 2)

    def test_after_push_names_real_sections(self):
        self.assert_sections_exist(strings(os.path.join(ROOT, "hooks", "after_push.py")),
                                   "hooks/after_push.py", 1)

    def test_command_doc_names_its_own_sections(self):
        self.assert_sections_exist([" ".join(read(DOC).split())],
                                   "commands/review-desk.md", 1)


if __name__ == "__main__":
    unittest.main()
