"""The desk build: the template's marker and title, and a payload built from text
that used to break the page. The page itself is exercised in tests/desk."""
import json
import os
import re
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

    def test_the_built_page_says_which_review_desk_built_it(self):
        # A desk is a published artifact: its page stays whatever version
        # published it, and nothing on the page used to say which, so a fix that
        # had shipped and a fix that had not looked identical from the desk.
        with open(os.path.join(HERE, "..", ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as f:
            declared = json.load(f)["version"]
        self.assertEqual(self.tpl.count("/*VERSION*/"), 1, "the template's stamp")
        page = build_desk.render(self.tpl, dict(HOSTILE), "Hostile Desk")
        self.assertEqual(re.search(r"const STAMP = '([^']*)'", page).group(1), declared)
        self.assertNotIn("/*VERSION*/", page)

    def test_an_unbuilt_template_says_dev_rather_than_its_marker(self):
        # The template is opened directly by the browser harness's own fixtures
        # and by anyone reading it; it must not print a comment marker as a
        # version.
        self.assertIn("const BUILT = /^\\d+\\.\\d+\\.\\d+$/.test(STAMP) ? STAMP : 'dev';",
                      self.tpl)

    def test_a_plugin_version_that_is_not_a_version_is_refused(self):
        real = build_desk.PLUGIN_JSON
        for bad in ('{"version": "0.17"}', '{"version": 17}', '{}', 'not json'):
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "plugin.json")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(bad)
                build_desk.PLUGIN_JSON = path
                try:
                    with self.assertRaises(build_desk.BuildError, msg=bad):
                        build_desk.render(self.tpl, dict(HOSTILE), "Hostile Desk")
                finally:
                    build_desk.PLUGIN_JSON = real

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


class Capabilities(unittest.TestCase):
    def setUp(self):
        self.caps = build_desk.capabilities(12)
        self.rules = self.caps["db"]["rules"]
        self.write = {r["path"]: r["write"] for r in self.rules}

    def test_declares_db_and_comments_only(self):
        # `comments` is how a question leaves the page, in its full form because
        # the page composes the message. `artifact` went with the doorbell: the
        # page no longer republishes itself to notify anyone.
        self.assertEqual(sorted(self.caps), ["comments", "db"])
        self.assertEqual(self.caps["comments"], {})

    def test_the_page_writes_its_own_document_at_interact(self):
        self.assertEqual(self.write["review/pr-12"], "interact")

    def test_session_paths_are_owner_only(self):
        for name in ("progress", "context", "documents"):
            self.assertEqual(self.write["review/pr-12/" + name], "owner", name)

    def test_a_documents_base_must_be_text_or_an_explicit_null(self):
        # The redline against the base branch is drawn from this. Anything else
        # would compare the file with nothing and call the result a diff.
        good = dict(HOSTILE, documents=[{"name": "a.md", "text": "x", "base": None},
                                        {"name": "b.md", "text": "x", "base": "y"},
                                        {"name": "c.md", "text": "x"}])
        build_desk.check_payload(good)
        for bad in (0, [], {}, True):
            with self.subTest(base=bad):
                with self.assertRaises(build_desk.BuildError):
                    build_desk.check_payload(
                        dict(HOSTILE, documents=[{"name": "a.md", "text": "x", "base": bad}]))

    def test_rules_are_well_formed_and_within_the_limit(self):
        self.assertLessEqual(len(self.rules), 64)
        self.assertEqual(len(self.write), len(self.rules), "a path is declared twice")
        for r in self.rules:
            self.assertEqual(set(r), {"path", "write"})
            self.assertRegex(r["path"], r"^[A-Za-z0-9_\-.~:@+]+(/[A-Za-z0-9_\-.~:@+]+)*$")
            self.assertIn(r["write"], ("interact", "admin", "owner"))

    def test_numbered_per_desk(self):
        paths = [r["path"] for r in build_desk.capabilities(7)["db"]["rules"]]
        self.assertTrue(all(p == "review/pr-7" or p.startswith("review/pr-7/") for p in paths))


HEAD = "0123456789abcdef0123456789abcdef01234567"


class Head(unittest.TestCase):
    """The head the reviewer read reaches the page, which stores it as decidedOn;
    /review-collect merges an approval only while GitHub's head is still it."""

    def test_gh_query_and_payload_schema_carry_head_ref_oid(self):
        with open(os.path.join(HERE, "..", "commands", "review-desk.md"), encoding="utf-8") as f:
            doc = f.read()
        query = re.search(r"gh pr view <n> --repo <owner/repo> --json (\S+)", doc)
        self.assertTrue(query, "no gh pr view query in review-desk.md")
        self.assertIn("headRefOid", query.group(1).split(","))
        schema = doc[doc.index("The payload is a JSON object:"):]
        schema = schema[:schema.index("\n    }\n")]
        self.assertRegex(schema, r'\n      "headRefOid": ')

    def test_a_valid_head_reaches_the_page_payload(self):
        payload = dict(HOSTILE, headRefOid=HEAD)
        build_desk.check_payload(payload)
        script = build_desk.page_script(build_desk.render(build_desk.template(), payload, "T"))
        line = next(l for l in script.splitlines() if l.startswith("const DATA = "))
        self.assertEqual(json.loads(line[len("const DATA = "):-1])["headRefOid"], HEAD)

    def test_a_payload_without_a_head_still_builds(self):
        build_desk.check_payload(HOSTILE)

    def test_a_malformed_head_is_refused(self):
        for bad in (HEAD[:7], HEAD + "0", HEAD.upper(), "g" * 40, " " + HEAD[1:], None, 1234, [HEAD]):
            with self.assertRaises(build_desk.BuildError, msg=repr(bad)):
                build_desk.check_payload(dict(HOSTILE, headRefOid=bad))


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
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], out)
        self.assertTrue(lines[1].startswith("capabilities: "))
        self.assertEqual(json.loads(lines[1][len("capabilities: "):]),
                         build_desk.capabilities(HOSTILE["number"]))

    def test_payload_without_a_number_is_refused(self):
        payload = dict(HOSTILE)
        del payload["number"]
        result, out = self.run_build(payload)
        self.assertEqual(result.returncode, 1)
        self.assertIn("number", result.stderr)
        self.assertFalse(os.path.exists(out))

    def test_payload_with_a_short_head_is_refused(self):
        result, out = self.run_build(dict(HOSTILE, headRefOid=HEAD[:7]))
        self.assertEqual(result.returncode, 1)
        self.assertIn("headRefOid", result.stderr)
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
