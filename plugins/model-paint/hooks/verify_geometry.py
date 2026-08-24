"""PostToolUse hook: re-check the geometry claim with different code.

apply_plan.py already verifies its own output and refuses to leave a file behind
that failed. That is the right design, and it is also exactly why it cannot be
the only check: a bug in paintlib would be shared by the painting and by the
proof, and the summary would read "geometry unchanged" either way.

So this hook re-derives the answer from scratch, on purpose, with an
implementation that shares nothing with the plugin: the 3MF is read with zipfile
and ElementTree instead of paintlib's byte-preserving regex reader, and an STL
input is read straight from its own binary/ASCII layout rather than through
trimesh. Two independent readers agreeing on every vertex of every triangle is a
claim worth printing.

A mismatch exits 2 so Claude sees the stderr even though the command already
ran; a pass is reported through systemMessage, which is how a PostToolUse hook
surfaces anything at all on a successful exit.
"""

import json
import re
import os
import shlex
import struct
import sys
import textwrap
import xml.etree.ElementTree as ElementTree
import zipfile

VERTEX_TOLERANCE = 1e-5     # from_stl formats float32 coordinates as %.6f


class CheckError(Exception):
    """The independent check could not run; that is not the same as a failure."""


# -- reading the command ----------------------------------------------------

def apply_plan_runs(command):
    """Every ``(input, output)`` pair an apply_plan.py invocation names."""
    runs = []
    for segment in _segments(command):
        if "apply_plan.py" not in segment:
            continue
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        values = {}
        index = 0
        while index < len(tokens):
            token = tokens[index]
            for name in ("--input", "--output"):
                if token == name and index + 1 < len(tokens):
                    values[name] = tokens[index + 1]
                    index += 1
                elif token.startswith(name + "="):
                    values[name] = token[len(name) + 1:]
            index += 1
        if "--input" in values and "--output" in values:
            runs.append((values["--input"], values["--output"]))
    return runs


def _segments(command):
    parts, current, quote, index = [], [], None, 0
    while index < len(command):
        char = command[index]
        if quote:
            current.append(char)
            if char == quote and command[index - 1] != "\\":
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char in ";\n|&":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


# -- independent mesh readers -----------------------------------------------

def read_3mf(path):
    """``[(object_id, [(x, y, z), ...], [(v1, v2, v3), ...]), ...]`` via ElementTree."""
    objects = []
    try:
        with zipfile.ZipFile(path, "r") as archive:
            parts = [name for name in archive.namelist()
                     if name.lower().startswith("3d/") and name.lower().endswith(".model")]
            if not parts:
                raise CheckError("%s contains no 3D/*.model part" % path)
            for part in sorted(parts):
                root = ElementTree.fromstring(archive.read(part))
                for element in root.iter():
                    if _tag(element) != "object":
                        continue
                    mesh = [child for child in element if _tag(child) == "mesh"]
                    if not mesh:
                        continue
                    vertices, triangles = [], []
                    for block in mesh[0]:
                        if _tag(block) == "vertices":
                            for vertex in block:
                                vertices.append((float(vertex.get("x")),
                                                 float(vertex.get("y")),
                                                 float(vertex.get("z"))))
                        elif _tag(block) == "triangles":
                            for triangle in block:
                                triangles.append((int(triangle.get("v1")),
                                                  int(triangle.get("v2")),
                                                  int(triangle.get("v3"))))
                    if triangles:
                        objects.append((element.get("id"), vertices, triangles))
    except (zipfile.BadZipFile, ElementTree.ParseError, TypeError, ValueError) as error:
        raise CheckError("could not read %s: %s" % (path, error))
    if not objects:
        raise CheckError("%s contains no mesh objects" % path)
    return objects


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def read_stl(path):
    """Triangles as ``[((x, y, z), (x, y, z), (x, y, z)), ...]``, file order kept."""
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * count:
            return [tuple(tuple(triangle[index:index + 3])
                          for index in (3, 6, 9))
                    for triangle in struct.iter_unpack("<12fH", data[84:])]
    return _read_ascii_stl(data, path)


def _read_ascii_stl(data, path):
    try:
        text = data.decode("utf-8", "replace")
    except UnicodeDecodeError:
        raise CheckError("%s is neither a valid binary nor ASCII STL" % path)
    triangles, current = [], []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("vertex"):
            fields = line.split()
            if len(fields) != 4:
                raise CheckError("malformed vertex line in %s: %s" % (path, line))
            current.append(tuple(float(value) for value in fields[1:]))
            if len(current) == 3:
                triangles.append(tuple(current))
                current = []
    if not triangles:
        raise CheckError("%s is neither a valid binary nor ASCII STL" % path)
    return triangles


# -- the check --------------------------------------------------------------

def triangle_points(objects):
    """Flatten 3MF objects into per-triangle coordinate triples."""
    points = []
    for object_id, vertices, triangles in objects:
        for v1, v2, v3 in triangles:
            try:
                points.append((vertices[v1], vertices[v2], vertices[v3]))
            except IndexError:
                raise CheckError(
                    "object %s references vertex %d of %d"
                    % (object_id, max(v1, v2, v3), len(vertices)))
    return points


def compare(source, output):
    """(ok, verdict). Raises CheckError when the comparison cannot be made."""
    for path in (source, output):
        if not os.path.exists(path):
            raise CheckError("no such file: %s" % path)

    after = read_3mf(output)
    if source.lower().endswith(".3mf"):
        before = read_3mf(source)
        if len(before) != len(after):
            return False, ("object count changed: %d in the input, %d in the output"
                           % (len(before), len(after)))
        for (id_a, vertices_a, triangles_a), (id_b, vertices_b, triangles_b) in zip(before, after):
            if triangles_a != triangles_b:
                return False, "triangle indices changed on object %s" % id_a
            if vertices_a != vertices_b:
                return False, "vertex coordinates changed on object %s" % id_a
        total = sum(len(item[2]) for item in after)
        return True, ("%d object(s), %d triangle(s): every vertex and every "
                      "triangle index identical to the input" % (len(after), total))

    before = read_stl(source)
    points = triangle_points(after)
    if len(before) != len(points):
        return False, ("triangle count changed: %d in the STL, %d in the output"
                       % (len(before), len(points)))
    for index, (stl_triangle, out_triangle) in enumerate(zip(before, points)):
        for corner in range(3):
            for axis in range(3):
                delta = abs(stl_triangle[corner][axis] - out_triangle[corner][axis])
                if delta > VERTEX_TOLERANCE:
                    return False, ("triangle %d corner %d moved by %g mm"
                                   % (index, corner, delta))
    return True, ("%d object(s), %d triangle(s): every corner matches the source "
                  "STL to within %g mm" % (len(after), len(points), VERTEX_TOLERANCE))


def check_run(source, output, cwd):
    source = source if os.path.isabs(source) else os.path.join(cwd, source)
    output = output if os.path.isabs(output) else os.path.join(cwd, output)
    ok, detail = compare(source, output)
    return ok, "%s: %s" % (os.path.basename(output), detail)


# apply_plan's own error prefix. Its presence in captured stderr means the run
# aborted, whatever the harness reported about exit status.
_FAILURE_PREFIX = re.compile(r"(?m)^\s*apply_plan:")


def run_succeeded(payload):
    """False only on positive evidence that the apply_plan run did not complete.

    A hook that cannot tell should still check the file, so ambiguity resolves to
    True. What must never happen is reporting PASS for a stale file left at the
    --output path by an earlier run, which is what an aborted apply_plan leaves
    behind.
    """
    response = payload.get("tool_response")
    if response is None:
        return True

    if isinstance(response, dict):
        for key in ("exit_code", "exitCode", "returncode", "status_code"):
            code = response.get(key)
            if isinstance(code, int) and code != 0:
                return False
        if response.get("interrupted") or response.get("is_error"):
            return False
        text = " ".join(str(response.get(key) or "")
                        for key in ("stdout", "stderr", "output", "content"))
    else:
        text = str(response)

    return not _FAILURE_PREFIX.search(text)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or "apply_plan.py" not in command:
        return 0
    cwd = payload.get("cwd") or os.getcwd()

    if not run_succeeded(payload):
        # apply_plan failed. Any file sitting at --output is left over from an
        # earlier run, and checking it would report PASS for a file this command
        # did not produce -- the most misleading thing this hook could say.
        return 0

    failures, passes, skipped = [], [], []
    for source, output in apply_plan_runs(command):
        target = output if os.path.isabs(output) else os.path.join(cwd, output)
        if not os.path.exists(target):
            continue                    # the run failed; apply_plan already said so
        try:
            ok, detail = check_run(source, output, cwd)
        except CheckError as error:
            skipped.append(str(error))
            continue
        (passes if ok else failures).append(detail)

    if failures:
        sys.stderr.write(
            "model-paint independent geometry check FAILED.\n\n"
            + "".join("  %s\n" % line for line in failures)
            + "\n" + textwrap.fill(
                "The painted file's mesh does not match the model it was made "
                "from, so its geometry was modified somewhere in the pipeline. Do "
                "not print or hand over this file, and treat apply_plan.py's own "
                "'geometry unchanged' line as unproven until this disagreement is "
                "explained.", width=76) + "\n")
        return 2

    notes = ["model-paint independent geometry check: PASS -- " + line for line in passes]
    notes += ["model-paint could not independently verify geometry: " + line
              for line in skipped]
    if notes:
        json.dump({"systemMessage": "\n".join(notes), "suppressOutput": True}, sys.stdout)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
