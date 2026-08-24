"""Decide whether a shell command would modify a mesh, and say why.

Everything this plugin promises rests on one property: painting adds
`paint_color` attributes and changes nothing else. The prompt can ask for that
politely; a hook can enforce it. This module holds the matching logic so the
hook scripts stay thin stdin/exit-code wrappers and the rules can be tested
directly.

Two deliberate biases shape the matcher:

  Conservative over clever. A false positive blocks work the user asked for and
  teaches them to route around the guardrail, which costs more than it saves. A
  false negative is still caught downstream, by apply_plan's own verification and
  by the PostToolUse geometry check. So the rules look for real call syntax
  (`.merge_vertices(`, not the bare word), read-only inspection commands are
  skipped outright, and each `&&`/`|`/`;` segment is judged on its own.

  Scoped by path, not by name. Mutating a scratch copy is ordinary work:
  measuring a decimated proxy, regenerating the sample fixture, poking at a
  temp file. What is never acceptable is doing it to the file the user is about
  to print for fourteen hours. So a matched rule is only a block when the
  command is not clearly confined to a temp/scratch path or the bundled sample.
"""

import os
import re
from collections import namedtuple

Finding = namedtuple("Finding", "rule matched why instead")

MESH_SUFFIXES = ("stl", "3mf", "obj", "ply", "off", "glb", "gltf")

# What a mesh file path looks like as a shell/python token.
_PATH_TOKEN_RE = re.compile(
    r"[\w./\\$~{}%+-]*\.(?:%s)\b" % "|".join(MESH_SUFFIXES), re.IGNORECASE)

# A path that is obviously not the user's model: system temp, a scratch dir, the
# repository's own sample fixture, a test tree.
_SAFE_PATH_RE = re.compile(
    r"/tmp/|/var/tmp/|/dev/shm/|/private/var/folders/"
    r"|(?:^|[/\\])(?:tmp|temp|scratch|sample|samples|fixture|fixtures|testdata|test|tests)[/\\]"
    r"|\$\{?TMPDIR\}?|%TEMP%"
    r"|creature\.stl",
    re.IGNORECASE)

# A command that makes its own temp directory is working on a copy by definition.
_TEMP_CONTEXT_RE = re.compile(
    r"\bmkdtemp\b|\bmkstemp\b|TemporaryDirectory|NamedTemporaryFile|\bmktemp\b")

# Commands that only read. They show up here because searching the codebase for
# a dangerous call puts that call's text in the command string.
_READ_ONLY = frozenset((
    "grep", "rg", "egrep", "fgrep", "ag", "ack", "git", "echo", "printf",
    "ls", "find", "wc", "head", "tail", "less", "more", "diff", "jq", "comm",
    "sort", "uniq", "file", "stat", "tree", "column", "cut", "nl",
))

# Token prefixes that precede the command actually being run.
_PREFIXES = frozenset(("sudo", "env", "command", "time", "nohup", "exec", "xargs"))

_MUTATORS = (
    ("decimation",
     r"\.simplify_quad(?:ric|ratic)_decimation\s*\(",
     "decimation rebuilds the mesh with fewer triangles: every face index in a "
     "paint plan then points somewhere else, and an interlocking flexi joint "
     "loses the clearances it was designed with",
     "read the mesh as it is; if you need a cheap proxy for analysis, build it "
     "under a temp path and never write it back"),

    ("subdivision",
     r"\.subdivide(?:_to_size|_loop)?\s*\(",
     "subdivision inserts vertices and renumbers faces, so the model no longer "
     "matches the segments and plan built against it",
     "work at the model's real resolution; paint_color already supports "
     "sub-triangle detail without touching the mesh"),

    ("vertex welding",
     r"\.merge_vertices\s*\(",
     "welding duplicate vertices fuses surfaces that a flexi model keeps "
     "deliberately separate, and renumbers every triangle",
     "load with trimesh.load(path, process=False), which is the only way this "
     "plugin ever reads a mesh"),

    ("face surgery",
     r"\.(?:remove_duplicate_faces|remove_degenerate_faces|"
     r"remove_unreferenced_vertices|update_faces|update_vertices)\s*\(",
     "dropping or renumbering faces invalidates the face indices the whole "
     "paint plan is written in",
     "leave the face list alone; filter indices in your own analysis instead of "
     "editing the mesh"),

    ("hole filling",
     r"\.fill_holes\s*\(",
     "hole filling adds triangles the designer did not put there, which on a "
     "flexi model can weld a joint shut",
     "if the mesh is non-watertight, report it rather than repairing it"),

    ("repair",
     r"trimesh\.repair\.|\.fix_normals\s*\(",
     "repair rewrites winding order and topology, so triangle indices and "
     "orientation stop matching the file the user modelled",
     "report what is wrong and let the user fix it in their modelling tool"),

    ("transform",
     r"\.apply_(?:scale|transform|translation|obb)\s*\(",
     "scaling, moving or reorienting the mesh changes the coordinates that get "
     "printed, and the user's plate setup already assumes the original",
     "compute in the model's own coordinates; if you need a transformed copy "
     "for measurement, keep it in memory or under a temp path"),

    ("boolean",
     r"boolean_(?:union|difference|intersection)\s*\(|trimesh\.boolean\.|"
     # Only on a mesh-looking receiver: set.union() is ordinary Python.
     r"\b(?:m|mesh\w*|model\w*|body\w*|part\w*)\.(?:union|difference|intersection)\s*\(",
     "boolean operations re-mesh both operands, which destroys the interlocking "
     "fit that makes a flexi model move",
     "select triangles by geometry (normals, connectivity, position) instead of "
     "cutting the mesh"),
)

_EXPORT_RE = re.compile(
    r"\.export\s*\(\s*[\"']([^\"']+\.(?:%s))[\"']" % "|".join(MESH_SUFFIXES),
    re.IGNORECASE)

_CONVEX_HULL_RE = re.compile(r"(\w+)\s*=\s*([\w.]*?)([\w]+)\.convex_hull\b")
_MESH_NAME_RE = re.compile(r"^(?:m|mesh\w*|model\w*|obj\w*|body\w*|part\w*|tm)$", re.I)

_LOAD_RE = re.compile(r"\btrimesh\.(load|load_mesh|load_scene)\s*\(")


def split_segments(command):
    """Split a shell command on `;`, `&&`, `||`, `|` and newlines, quotes aside.

    Quote tracking is best-effort: a heredoc full of apostrophes can confuse it.
    The failure mode is deliberately safe -- text stays glued to the segment that
    started it, so a dangerous call is still scanned, just possibly under a
    different leading command.
    """
    segments, current, quote, index = [], [], None, 0
    while index < len(command):
        char = command[index]
        if quote:
            current.append(char)
            if char == quote and command[index - 1] != "\\":
                quote = None
            index += 1
            continue
        if char in "\"'":
            quote = char
            current.append(char)
            index += 1
            continue
        if command[index:index + 2] in ("&&", "||"):
            segments.append("".join(current))
            current = []
            index += 2
            continue
        if char in ";\n|&":
            segments.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    segments.append("".join(current))
    return [segment.strip() for segment in segments if segment.strip()]


def leading_command(segment):
    """The program a segment actually runs, past `VAR=x`, `sudo`, `time`, ..."""
    for token in segment.split():
        token = token.strip("\"'()")
        if not token or re.match(r"^\w+=", token) or token.startswith("-"):
            continue
        name = os.path.basename(token)
        if name in _PREFIXES:
            continue
        return name
    return ""


def is_read_only(segment):
    return leading_command(segment) in _READ_ONLY


def mesh_paths(segment):
    """Every mesh-file path token in the segment, in order."""
    return [match.group(0) for match in _PATH_TOKEN_RE.finditer(segment)]


def is_safe_path(path):
    return bool(_SAFE_PATH_RE.search(path))


def scoped_to_scratch(segment):
    """True when the segment clearly only touches temp/scratch/sample files.

    No mesh path at all is not scratch: a command that reads its target from a
    variable or argv could be pointed at anything, and that is exactly the case
    worth stopping.
    """
    paths = mesh_paths(segment)
    if paths:
        return all(is_safe_path(path) for path in paths)
    return bool(_TEMP_CONTEXT_RE.search(segment))


def _load_call_args(segment):
    """Argument text of each trimesh.load(...) call, parentheses balanced."""
    for match in _LOAD_RE.finditer(segment):
        depth, index = 1, match.end()
        while index < len(segment) and depth:
            if segment[index] == "(":
                depth += 1
            elif segment[index] == ")":
                depth -= 1
            index += 1
        yield segment[match.end():index - 1] if not depth else segment[match.end():]


def scan_segment(segment):
    """Findings for one shell segment, ignoring where it points."""
    findings = []
    for rule, pattern, why, instead in _MUTATORS:
        match = re.search(pattern, segment)
        if match:
            findings.append(Finding(rule, match.group(0).strip(), why, instead))

    for args in _load_call_args(segment):
        if not re.search(r"process\s*=\s*False", args):
            findings.append(Finding(
                "unprocessed load",
                "trimesh.load(%s)" % args.strip(),
                "trimesh.load defaults to process=True, which merges vertices and "
                "drops duplicate faces while loading -- the mesh in memory is then "
                "already not the mesh in the file",
                "pass process=False explicitly: trimesh.load(path, process=False, "
                "force=\"mesh\")"))

    match = _CONVEX_HULL_RE.search(segment)
    if match and (_MESH_NAME_RE.match(match.group(1)) or match.group(1) == match.group(3)):
        findings.append(Finding(
            "convex hull",
            match.group(0).strip(),
            "assigning a convex hull back onto the mesh variable replaces the "
            "model with its shrink-wrap, and everything downstream then paints "
            "the wrong surface",
            "keep the hull in a separate variable if you need it for orientation "
            "or bounding, and never write it out"))

    for match in _EXPORT_RE.finditer(segment):
        target = match.group(1)
        if not is_safe_path(target):
            findings.append(Finding(
                "mesh export",
                match.group(0).strip(),
                "exporting over %s rewrites the user's model through trimesh's "
                "writer, which reorders and reformats the mesh even when nothing "
                "was edited" % target,
                "never write a mesh format over an input; painted output goes to "
                "a new 3MF via apply_plan.py"))

    return findings


def evaluate(command):
    """Findings that should block ``command``, most specific first.

    An empty list means allow. Each finding already carries the reason and the
    remedy, so the caller only has to format them.
    """
    blocking = []
    for segment in split_segments(command):
        if is_read_only(segment):
            continue
        findings = scan_segment(segment)
        if findings and not scoped_to_scratch(segment):
            blocking.extend(findings)
    return blocking


def format_block(command, findings):
    """The message the user and Claude see when a command is refused."""
    lines = ["model-paint: blocked a command that would modify mesh geometry.",
             "", "  command   %s" % command.strip(), ""]
    for finding in findings:
        lines.append("  rule      %s" % finding.rule)
        lines.append("  matched   %s" % finding.matched)
        lines.extend(_wrap("why", finding.why))
        lines.extend(_wrap("instead", finding.instead))
        lines.append("")
    lines.append("Geometry must survive painting byte-for-byte: these are "
                 "interlocking flexi prints, and a silent re-mesh is a wasted "
                 "multi-hour print. If this really is scratch work, run it on a "
                 "copy under /tmp and the same command is allowed.")
    return "\n".join(lines)


def _wrap(label, text, width=68):
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return ["  %-9s %s" % (label if index == 0 else "", line)
            for index, line in enumerate(lines)]
