#!/usr/bin/env python3
"""Build a review desk page from the template and a payload file.

    python3 build_desk.py payload.json "Design 0001 Review" --out desk.html

It prints the page's path, then the capabilities object to publish it with.

The payload goes inside an inline <script>, and the HTML parser ends that
script at the first "</script" it meets -- inside a JSON string too. A carried
file that quotes a script tag used to cut the page's code in half and leave the
reviewer a blank page. Every "<" in the payload is written as \\u003c, which
JSON.parse and JavaScript read back as the same character, so no carried text
can reach the HTML parser. U+2028 and U+2029 are escaped too, for older engines
that do not allow them raw in a string literal.

The marker is replaced exactly once, by position, so a payload that itself
contains the marker text (this plugin's own docs do) is never substituted into.
"""
import argparse
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ROOT, "templates", "review.html")
MARKER = "/*PAYLOAD*/"
# The page says which review-desk built it, in its footer and in every document
# it writes. A desk is a published artifact: its page stays whatever version
# published it, however many have shipped since, and nothing on the page used to
# say which. Taken from the plugin's own manifest rather than the payload, so a
# session cannot forget it or get it wrong.
VERSION_MARKER = "/*VERSION*/"
PLUGIN_JSON = os.path.join(ROOT, ".claude-plugin", "plugin.json")
TEMPLATE_TITLE = "<title>Review Desk</title>"
# The publisher reads the title only from the first 8KB of the page.
TITLE_WINDOW = 8192
REQUIRED = ("repo", "number", "title", "url")


class BuildError(Exception):
    pass


def template():
    with open(TEMPLATE, encoding="utf-8") as f:
        return f.read()


def version():
    """The plugin's version, from its manifest."""
    try:
        with open(PLUGIN_JSON, encoding="utf-8") as f:
            found = json.load(f).get("version")
    except (OSError, ValueError) as e:
        raise BuildError("cannot read the plugin version from %s: %s" % (PLUGIN_JSON, e))
    if not isinstance(found, str) or not re.fullmatch(r"\d+\.\d+\.\d+", found):
        raise BuildError("the plugin version must be major.minor.patch, found %r" % (found,))
    return found


def script_json(payload):
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (text.replace("<", "\\u003c")
                .replace(" ", "\\u2028")
                .replace(" ", "\\u2029"))


def render(tpl, payload, title):
    if tpl.count(MARKER) != 1:
        raise BuildError("the template must contain %s exactly once, found %d"
                         % (MARKER, tpl.count(MARKER)))
    if tpl.count(TEMPLATE_TITLE) != 1:
        raise BuildError("the template must contain %s exactly once" % TEMPLATE_TITLE)
    if tpl.count(VERSION_MARKER) != 1:
        raise BuildError("the template must contain %s exactly once, found %d"
                         % (VERSION_MARKER, tpl.count(VERSION_MARKER)))
    if not title or not title.strip():
        raise BuildError("the page needs a title")
    # The version first: the payload is substituted by position, and a carried
    # file that quotes the version marker must not be rewritten.
    tpl = tpl.replace(VERSION_MARKER, version(), 1)
    before, after = tpl.split(MARKER)
    page = before + script_json(payload) + after
    page = page.replace(TEMPLATE_TITLE,
                        "<title>%s</title>" % html.escape(title.strip(), quote=False), 1)
    if page.encode("utf-8").find(b"</title>") > TITLE_WINDOW:
        raise BuildError("<title> is not within the first %d bytes" % TITLE_WINDOW)
    return page


def page_script(page):
    """The body of the page's own inline script -- the one holding the payload."""
    start = page.index("const DATA = ")
    open_tag = page.rindex("<script>", 0, start) + len("<script>")
    return page[open_tag:page.index("</script>", start)]


# Who may write where in the desk's store (db.d.ts, ACCESS RULES). Without rules
# every viewer the desk is shared with writes every path, so one could write a
# line the page shows as the session's work, or a pickup reading "Merged". Those
# paths are written only by the session, which writes as the artifact's owner.
# The page itself writes review/pr-N, the decision, at interact. Rules are fixed
# at publish: a desk published before these existed stays open until it is
# republished with them.
SESSION_PATHS = ("progress", "context", "documents")
MAX_RULES = 64


def capabilities(number):
    base = "review/pr-%d" % number
    rules = [{"path": base, "write": "interact"}]
    rules += [{"path": base + "/" + name, "write": "owner"} for name in SESSION_PATHS]
    if len(rules) > MAX_RULES:
        raise BuildError("the store allows at most %d rules" % MAX_RULES)
    # `comments` is the channel a question leaves by, and the page needs the full
    # form: it composes the message itself, so that the quick reply the platform
    # posts is asked for a receipt rather than an answer. `artifact` is gone with
    # the doorbell that used it.
    return {"db": {"rules": rules}, "comments": {}}


def check_payload(payload):
    if not isinstance(payload, dict):
        raise BuildError("the payload must be a JSON object")
    # Each document carries the file twice: as it will be, and as it is on the
    # base branch. A `base` that is neither text nor an explicit null would draw
    # a redline against nothing, so it is refused here rather than on the page.
    for doc in payload.get("documents") or []:
        if isinstance(doc, dict) and "base" in doc and not (
                doc["base"] is None or isinstance(doc["base"], str)):
            raise BuildError("a document's base must be the file's text on the base "
                             "branch, or null when the request adds it: %r" % (doc.get("name"),))
    missing = [k for k in REQUIRED if k not in payload]
    if missing:
        raise BuildError("the payload is missing " + ", ".join(missing))
    if not isinstance(payload["number"], int) or isinstance(payload["number"], bool):
        raise BuildError("number must be an integer: the page stores under review/pr-<number>")
    # The page stores this as decidedOn when the reviewer decides, and
    # /review-collect compares it with GitHub's headRefOid before merging and
    # passes it to --match-head-commit. A value that can never equal a real head
    # would block every approval, so it is refused here rather than on the page.
    if "headRefOid" in payload and not is_head(payload["headRefOid"]):
        raise BuildError("headRefOid must be the 40-character lowercase hex commit "
                         "gh pr view --json headRefOid prints")


def is_head(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("payload", help="the payload JSON file")
    ap.add_argument("title", help="the page's name, two to four words")
    ap.add_argument("--out", required=True, help="where to write the page")
    args = ap.parse_args(argv)
    try:
        with open(args.payload, encoding="utf-8") as f:
            payload = json.load(f)
        check_payload(payload)
        page = render(template(), payload, args.title)
    except (OSError, ValueError, BuildError) as e:
        print("build_desk: " + str(e), file=sys.stderr)
        return 1
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(args.out)
    print("capabilities: " + json.dumps(capabilities(payload["number"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
