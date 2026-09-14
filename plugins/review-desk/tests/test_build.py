"""The desk build: the template's marker and title, and a payload built from text
that used to break the page. The page itself is exercised in tests/desk."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import build_desk  # noqa: E402

HOSTILE = {
    "repo": "LiLo-Labs/claude-code-plugins", "number": 7, "title": "Hostile text",
    "url": "https://github.com/LiLo-Labs/claude-code-plugins/pull/7",
    "summary": "3 files </script>",
    "body": "Quotes `</script>` and `/*PAYLOAD*/` in prose.",
    "documents": [
        {"name": "templates/page.html", "text": "<script>x()</script>\n</SCRIPT >"},
        {"name": "docs/old.md", "text": "<!--<script>\nstill a comment\n"},
        {"name": "docs/marker.md", "text": "const DATA = /*PAYLOAD*/;\n"},
        {"name": "docs/separators.md", "text": "line sep para"},
    ],
    "openers": ["Why </script>?"],
}


def node_check(source):
    return subprocess.run(["node", "--check"], input=source, text=True,
                          capture_output=True)


class Template(unittest.TestCase):
    def setUp(self):
        self.tpl = build_desk.template()

    def test_marker_appears_exactly_once(self):
        self.assertEqual(self.tpl.count("/*PAYLOAD*/"), 1)

    def test_title_within_first_8kb(self):
        head = self.tpl.encode("utf-8")[:8192]
        self.assertIn(b"<title>Review Desk</title>", head)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_script_parses_with_empty_payload(self):
        page = self.tpl.replace("/*PAYLOAD*/", "{}")
        result = node_check(build_desk.page_script(page))
        self.assertEqual(result.returncode, 0, result.stderr)


class Render(unittest.TestCase):
    def setUp(self):
        self.page = build_desk.render(build_desk.template(), HOSTILE, "Hostile Text Review")
        self.script = build_desk.page_script(self.page)

    def test_no_carried_text_reaches_the_html_parser(self):
        lowered = self.script.lower()
        self.assertNotIn("</script", lowered)
        self.assertNotIn("<!--", lowered)

    def test_payload_round_trips_exactly(self):
        line = next(l for l in self.script.splitlines() if l.startswith("const DATA = "))
        self.assertEqual(json.loads(line[len("const DATA = "):-1]), HOSTILE)

    def test_marker_inside_payload_is_not_substituted(self):
        # The template's marker is gone; the only copies left are the payload's own.
        in_payload = build_desk.script_json(HOSTILE).count("/*PAYLOAD*/")
        self.assertEqual(in_payload, 2)
        self.assertEqual(self.page.count("/*PAYLOAD*/"), in_payload)
        self.assertTrue(self.script.lstrip().startswith("const DATA = {"))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_inline_script_parses(self):
        result = node_check(self.script)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_title_is_named_escaped_and_early(self):
        page = build_desk.render(build_desk.template(), HOSTILE, "A </title> <b>")
        self.assertTrue(page.startswith("<title>A &lt;/title&gt; &lt;b&gt;</title>"))
        self.assertNotIn("<title>Review Desk</title>", page)
        self.assertLess(page.encode("utf-8").find(b"</title>"), 8192)

    def test_template_with_two_markers_is_refused(self):
        with self.assertRaises(build_desk.BuildError):
            build_desk.render(build_desk.template() + "/*PAYLOAD*/", HOSTILE, "T")


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def run_build(self, payload, title="Hostile Text Review"):
        src = os.path.join(self.tmp.name, "payload.json")
        out = os.path.join(self.tmp.name, "desk.html")
        with open(src, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        result = subprocess.run(
            [sys.executable, os.path.join(HERE, "..", "build_desk.py"), src, title, "--out", out],
            capture_output=True, text=True)
        return result, out

    def test_writes_the_page(self):
        result, out = self.run_build(HOSTILE)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(out, encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("<title>Hostile Text Review</title>"))

    def test_payload_without_a_number_is_refused(self):
        payload = dict(HOSTILE)
        del payload["number"]
        result, out = self.run_build(payload)
        self.assertEqual(result.returncode, 1)
        self.assertIn("number", result.stderr)
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
