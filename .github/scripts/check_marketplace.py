#!/usr/bin/env python3
"""The marketplace listing must agree with the plugins it lists.

`.claude-plugin/marketplace.json` is what a user's Claude Code reads to install
and update a plugin; each plugin's own `.claude-plugin/plugin.json` is what the
plugin says it is. Nothing keeps the two in step, and both are edited by hand at
the end of a change, so they drift: code-canvas shipped 0.7.0 while the
marketplace advertised 0.6.3, which means an install stayed on 0.6.3 and nothing
anywhere said why.

The plugin's own manifest is the source of truth. Run: python3 this file.
No dependencies beyond the standard library.
"""
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MARKETPLACE = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
PLUGINS = os.path.join(ROOT, "plugins")
SEMVER = re.compile(r"\d+\.\d+\.\d+$")


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def on_disk():
    """Each plugin directory that carries a manifest, by directory name."""
    found = {}
    for name in sorted(os.listdir(PLUGINS)):
        manifest = os.path.join(PLUGINS, name, ".claude-plugin", "plugin.json")
        if os.path.exists(manifest):
            found[name] = read(manifest)
    return found


def problems():
    listed = {}
    for entry in read(MARKETPLACE).get("plugins", []):
        source = entry.get("source")
        if not isinstance(source, str) or not source.startswith("./plugins/"):
            yield "marketplace entry %r has source %r, not ./plugins/<dir>" % (
                entry.get("name"), source)
            continue
        listed[source[len("./plugins/"):]] = entry

    plugins = on_disk()
    for name in sorted(set(listed) | set(plugins)):
        entry, manifest = listed.get(name), plugins.get(name)
        if manifest is None:
            yield "marketplace lists ./plugins/%s, which has no plugin.json" % name
            continue
        if entry is None:
            yield "plugins/%s is not listed in the marketplace" % name
            continue
        version, declared = manifest.get("version"), entry.get("version")
        if not isinstance(version, str) or not SEMVER.fullmatch(version):
            yield "plugins/%s declares version %r, not major.minor.patch" % (name, version)
        elif version != declared:
            yield ("plugins/%s is %s, the marketplace says %s: an install stays on the "
                   "marketplace's version" % (name, version, declared))
        if manifest.get("name") != name:
            yield "plugins/%s calls itself %r" % (name, manifest.get("name"))
        if entry.get("name") != name:
            yield "the marketplace calls ./plugins/%s %r" % (name, entry.get("name"))


def main():
    found = list(problems())
    for line in found:
        print("marketplace: " + line, file=sys.stderr)
    if found:
        print("%d problem%s" % (len(found), "" if len(found) == 1 else "s"), file=sys.stderr)
        return 1
    print("marketplace and %d plugin manifests agree" % len(on_disk()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
