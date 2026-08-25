"""Apply an approved paint plan to a model and prove the geometry survived it.

This is the step that hands the user a file they will feed to a 14-hour print of
an interlocking flexi model, so it is built to be checkable rather than merely
correct. Three habits do that work:

  Never touch the input. An STL is converted into a fresh 3MF and a 3MF is
  copied; every edit happens to that copy. The file the user pointed at is
  opened read-only and closed unchanged.

  Refuse to guess. A plan naming a segment that is not in the segments file, a
  filament that is not in the plan's own filament list, or a face index past the
  end of an object is an error with a message saying which one -- not a silently
  skipped assignment that shows up as bare plastic six hours into the print.

  Verify, then declare. After saving, the output is compared against the source
  with threemf.geometry_matches and reloaded to confirm the paint decodes back to
  exactly the triangles the plan implied. If either check fails the output is
  deleted, because a file that exists is a file someone will eventually print.

Unpainted triangles are left unpainted rather than painted with the default
filament: in Orca they fall back to the object's own extruder, which this script
sets from `default_filament`. That keeps the paint data to what the plan actually
decided and makes the unpainted count in the summary mean something.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import build, orca
from paintlib.encoding import MAX_FILAMENT, filaments_used
from paintlib.threemf import ThreeMF, geometry_matches

SEGMENT_ID_KEYS = ("id", "segment_id", "name", "label")
FACE_KEYS = ("face_indices", "faces", "facets", "triangles", "triangle_indices")

CONFLICTS_SHOWN = 5

# The zip stamps in an archive built here would otherwise be the wall clock, and
# two runs of the same plan would differ byte for byte. Only archives this run
# created are normalized; a 3MF the user brought keeps its own stamps.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class ApplyError(Exception):
    """Anything that should stop the run with an actionable message."""


def _first_key(source, names):
    for name in names:
        if name in source and source[name] is not None:
            return source[name]
    return None


def read_json(path, what):
    if not os.path.exists(path):
        raise ApplyError("no such %s file: %s" % (what, path))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except ValueError as error:
        raise ApplyError("%s is not valid JSON: %s" % (path, error))


# -- inputs -----------------------------------------------------------------

def _segment_entries(data, path):
    """Flatten whatever shape the segmenter wrote into a list of segment dicts."""
    if isinstance(data, dict):
        objects = data.get("objects")
        if isinstance(objects, list):
            entries = []
            for obj in objects:
                if not isinstance(obj, dict):
                    continue
                object_id = obj.get("object_id")
                for segment in obj.get("segments") or []:
                    if not isinstance(segment, dict):
                        continue
                    segment = dict(segment)
                    if segment.get("object_id") is None and object_id is not None:
                        segment["object_id"] = object_id
                    entries.append(segment)
            return entries
        # "parts" is what patch_select.py, resolve_parts.py and scale_ladder.py all
        # write, so leaving it out sent every part map down the fallback branch below
        # and failed with a type error rather than a readable message.
        for key in ("segments", "regions", "features", "parts"):
            if isinstance(data.get(key), list):
                return data[key]
        return [{"id": key, "faces": value} for key, value in data.items()]
    if isinstance(data, list):
        return data
    raise ApplyError("%s: expected a segments document" % path)


def load_segments(path):
    """``{segment_id: {'id', 'object_id', 'faces'}}`` in file order."""
    entries = _segment_entries(read_json(path, "segments"), path)
    segments = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ApplyError("%s: segment %d is not an object" % (path, position))
        identifier = _first_key(entry, SEGMENT_ID_KEYS)
        identifier = str(identifier) if identifier is not None else "segment-%d" % position
        raw_faces = _first_key(entry, FACE_KEYS)
        if raw_faces is None:
            raise ApplyError(
                "%s: segment %r carries no face list (expected one of %s)"
                % (path, identifier, ", ".join(FACE_KEYS)))
        if identifier in segments:
            raise ApplyError("%s: segment id %r appears twice" % (path, identifier))
        object_id = _first_key(entry, ("object_id", "object", "objectid"))
        segments[identifier] = {
            "id": identifier,
            "object_id": None if object_id is None else str(object_id),
            "faces": [int(index) for index in raw_faces],
        }
    if not segments:
        raise ApplyError("%s contains no segments" % path)
    return segments


def load_plan(path):
    """``(filaments_by_index, assignments, default_filament)``."""
    data = read_json(path, "plan")
    if not isinstance(data, dict):
        raise ApplyError("%s: expected a plan object" % path)

    filaments = {}
    for entry in data.get("filaments") or []:
        if not isinstance(entry, dict) or entry.get("index") is None:
            raise ApplyError(
                "%s: every filament needs an index, name and hex" % path)
        index = int(entry["index"])
        if not 1 <= index <= MAX_FILAMENT:
            raise ApplyError(
                "%s: filament index %d is outside 1..%d" % (path, index, MAX_FILAMENT))
        if index in filaments:
            raise ApplyError("%s: filament index %d listed twice" % (path, index))
        colour = _first_key(entry, ("hex", "color", "colour"))
        try:
            colour = orca.normalize_hex(colour or orca.PLACEHOLDER_COLOUR)
        except orca.OrcaError as error:
            raise ApplyError("%s: filament %d: %s" % (path, index, error))
        filaments[index] = {
            "index": index,
            "name": str(entry.get("name") or "filament %d" % index),
            "hex": colour,
            "settings_id": _first_key(entry, ("settings_id", "preset")),
            "type": entry.get("type"),
        }
    if not filaments:
        raise ApplyError("%s lists no filaments" % path)

    known = ", ".join(str(index) for index in sorted(filaments))
    assignments = []
    for position, entry in enumerate(data.get("assignments") or []):
        if not isinstance(entry, dict):
            raise ApplyError("%s: assignment %d is not an object" % (path, position))
        segment_id = _first_key(entry, ("segment_id", "segment", "id"))
        if segment_id is None:
            raise ApplyError(
                "%s: assignment %d names no segment_id" % (path, position))
        if entry.get("filament") is None:
            raise ApplyError(
                "%s: assignment for %r names no filament" % (path, segment_id))
        filament = int(entry["filament"])
        if filament not in filaments:
            raise ApplyError(
                "%s: assignment for %r uses filament %d, which the plan does not "
                "list (it lists %s)" % (path, segment_id, filament, known))
        assignments.append({
            "segment_id": str(segment_id),
            "filament": filament,
            "reason": str(entry.get("reason") or ""),
        })
    if not assignments:
        raise ApplyError("%s makes no assignments; nothing to paint" % path)

    default = data.get("default_filament")
    default = int(default) if default is not None else min(filaments)
    if default not in filaments:
        raise ApplyError(
            "%s: default_filament %d is not one of the listed filaments (%s)"
            % (path, default, known))
    return filaments, assignments, default


# -- resolution -------------------------------------------------------------

def resolve_assignments(threemf, segments, assignments, keep_existing=False):
    """Turn plan assignments into ``{object_key: {triangle: filament}}``.

    Also returns the conflicts -- triangles two assignments both claimed. Last
    assignment wins, which is a defensible rule for overlapping segments, but it
    is never silent -- and the number of triangles whose earlier paint was
    cleared.

    Paint already in the input is cleared unless ``keep_existing``. An input that
    was painted before carries states for filaments this plan never listed, and
    those would print in a color nobody chose. The plan is the whole description
    of the finished model, so the output says exactly what the plan says.
    """
    all_objects = threemf.mesh_objects()
    if not all_objects:
        raise ApplyError("the model contains no mesh objects to paint")

    # Real Bambu and Orca project files use the 3MF production extension, which
    # puts objects in separate 3D/Objects/*.model parts. Object ids are only
    # unique within a part, so keying on the id alone silently paints the wrong
    # body when two parts happen to reuse an id.
    by_key = {(obj.part, obj.object_id): obj for obj in all_objects}
    by_id = {}
    ambiguous = set()
    for obj in all_objects:
        if obj.object_id in by_id:
            ambiguous.add(obj.object_id)
        by_id[obj.object_id] = obj
    objects = by_id
    sole = all_objects[0] if len(all_objects) == 1 else None

    def resolve_object(segment):
        part = segment.get("part")
        if part is not None and (part, segment["object_id"]) in by_key:
            return by_key[(part, segment["object_id"])]
        if segment["object_id"] in ambiguous:
            raise ApplyError(
                "segment %r names object %r, which exists in more than one model "
                "part (%s). Re-run segment.py against this file so the segments "
                "carry the part they came from."
                % (segment["id"], segment["object_id"],
                   ", ".join(sorted(str(key[0]) for key in by_key
                                    if key[1] == segment["object_id"]))))
        if segment["object_id"] in by_id:
            return by_id[segment["object_id"]]
        return None

    unknown = [entry["segment_id"] for entry in assignments
               if entry["segment_id"] not in segments]
    if unknown:
        raise ApplyError(
            "the plan assigns %d segment(s) that the segments file does not "
            "contain (%s); pass the segments.json the plan was written against"
            % (len(unknown), ", ".join(sorted(set(unknown))[:8])))

    painted = {}
    owner = {}
    conflicts = []
    for entry in assignments:
        segment = segments[entry["segment_id"]]
        object_id = segment["object_id"]
        obj = resolve_object(segment)
        if obj is None and sole is not None:
            obj = sole
        if obj is None:
            raise ApplyError(
                "segment %r names object %r, which is not in the model (it has "
                "objects %s)" % (segment["id"], object_id,
                                 ", ".join(sorted(objects))))
        limit = obj.triangle_count
        outside = [index for index in segment["faces"]
                   if not 0 <= index < limit]
        if outside:
            raise ApplyError(
                "segment %r references face index %d, but object %s has %d "
                "triangles; the segments file and the model do not match"
                % (segment["id"], outside[0], obj.object_id, limit))
        if not segment["faces"]:
            sys.stderr.write(
                "warning: segment %r has no faces; assignment ignored\n"
                % segment["id"])
            continue

        key = (obj.part, obj.object_id)
        target = painted.setdefault(key, {})
        claimed = owner.setdefault(key, {})
        for index in segment["faces"]:
            previous = target.get(index)
            if previous is not None and previous != entry["filament"]:
                conflicts.append({
                    "object_id": obj.object_id,
                    "triangle": index,
                    "was": previous,
                    "was_from": claimed[index],
                    "now": entry["filament"],
                    "now_from": segment["id"],
                })
            target[index] = entry["filament"]
            claimed[index] = segment["id"]
    if not painted:
        raise ApplyError("the plan resolved to zero triangles; nothing to paint")

    cleared = 0
    if not keep_existing:
        for obj in objects.values():
            key = (obj.part, obj.object_id)
            target = painted.setdefault(key, {})
            for index, value in enumerate(obj.paint):
                if value and index not in target:
                    target[index] = 0
                    cleared += 1
    return objects, painted, conflicts, cleared


def expected_counts(objects, painted):
    """The per-filament triangle counts the plan implies, before anything is written.

    Mirrors MeshObject.filament_histogram so the post-save reload compares like
    with like: key 0 is unpainted, and a triangle that keeps subdivided paint
    from the input credits each of its filaments once.
    """
    counts = {}
    for obj in objects.values():
        mapping = painted.get((obj.part, obj.object_id), {})
        for index in range(obj.triangle_count):
            if index in mapping:
                used = {mapping[index]} if mapping[index] else {0}
            else:
                value = obj.paint[index]
                used = filaments_used(value) if value else set()
                used = used or {0}
            for filament in used:
                counts[filament] = counts.get(filament, 0) + 1
    return counts


# -- sourcing and verification ----------------------------------------------

def prepare_source(input_path, workdir):
    """A private 3MF to paint: a copy of the input, or one built from the STL."""
    lowered = input_path.lower()
    target = os.path.join(workdir, "source.3mf")
    if lowered.endswith(".3mf"):
        shutil.copyfile(input_path, target)
        return target, False
    if not lowered.endswith((".stl", ".obj", ".ply", ".off")):
        raise ApplyError(
            "unsupported input %s; expected an .stl or a .3mf" % input_path)
    try:
        build.from_stl(input_path, target,
                       name=os.path.splitext(os.path.basename(input_path))[0])
    except Exception as error:
        raise ApplyError("could not convert %s: %s" % (input_path, error))
    _verify_conversion(input_path, target)
    return target, True


def _verify_conversion(mesh_path, threemf_path):
    """The STL -> 3MF step is the one place a mesh is rewritten. Count it."""
    import trimesh

    loaded = trimesh.load(mesh_path, process=False, force="mesh")
    objects = ThreeMF(threemf_path).mesh_objects()
    if len(objects) != 1:
        raise ApplyError(
            "converting %s produced %d objects, expected 1" % (mesh_path, len(objects)))
    obj = objects[0]
    if obj.triangle_count != len(loaded.faces) or len(obj.vertices) != len(loaded.vertices):
        raise ApplyError(
            "converting %s changed the mesh: %d/%d vertices, %d/%d triangles"
            % (mesh_path, len(obj.vertices), len(loaded.vertices),
               obj.triangle_count, len(loaded.faces)))


def verify_output(source, output, expected):
    """Geometry identical, and the paint decodes back to what the plan implied."""
    same, detail = geometry_matches(source, output)
    if not same:
        raise ApplyError("geometry changed: %s" % detail)

    counts = {}
    for obj in ThreeMF(output).mesh_objects():
        for filament, count in obj.filament_histogram().items():
            counts[filament] = counts.get(filament, 0) + count
    counts = {key: value for key, value in counts.items() if value}
    expected = {key: value for key, value in expected.items() if value}
    if counts != expected:
        raise ApplyError(
            "painted triangle counts do not match the plan: expected %s, found %s"
            % (_counts_text(expected), _counts_text(counts)))
    return detail


def _counts_text(counts):
    return "{%s}" % ", ".join(
        "%s: %d" % ("unpainted" if key == 0 else "filament %d" % key, counts[key])
        for key in sorted(counts))


# -- reporting --------------------------------------------------------------

def write_summary(stream, report):
    stream.write("  input      %s%s\n" % (report["input"],
                                          " (converted to 3MF)" if report["converted"] else ""))
    stream.write("  output     %s\n" % report["output"])
    stream.write("  model      %d triangle(s) in %d object(s)\n"
                 % (report["triangle_count"], report["object_count"]))

    counts = report["counts"]
    filaments = report["filaments"]
    rows = []
    for index in sorted(filaments):
        rows.append((str(index), filaments[index]["name"],
                     filaments[index]["hex"], counts.get(index, 0)))
    for index in sorted(counts):
        if index and index not in filaments:
            rows.append((str(index), "(not in the plan)", "", counts[index]))
    width = max([len(row[1]) for row in rows] + [9])
    stream.write("\n  filament  %-*s  %-7s  %9s\n" % (width, "name", "color", "triangles"))
    for index, name, colour, count in rows:
        stream.write("  %-8s  %-*s  %-7s  %9d\n" % (index, width, name, colour, count))
    stream.write("  %-8s  %-*s  %-7s  %9d\n"
                 % ("-", width, "unpainted", "", counts.get(0, 0)))

    default = report["default_filament"]
    stream.write("\n  unpainted triangles print from filament %d (%s)\n"
                 % (default, filaments[default]["name"]))
    if report["cleared"]:
        stream.write("  cleared paint on %d triangle(s) the input already carried\n"
                     % report["cleared"])
    if report["conflicts"]:
        first = report["conflicts"][0]
        stream.write("  %d triangle(s) claimed twice; the last assignment won "
                     "(e.g. triangle %d: %s over %s)\n"
                     % (len(report["conflicts"]), first["triangle"],
                        first["now_from"], first["was_from"]))
    if not report["settings_existed"]:
        stream.write("  wrote a minimal %s (the input had none)\n"
                     % orca.PROJECT_SETTINGS_PART)
    stream.write("  geometry unchanged: %s\n" % report["geometry_detail"])


# -- driver -----------------------------------------------------------------

def run(args):
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    if not os.path.exists(input_path):
        raise ApplyError("no such input file: %s" % input_path)
    # realpath, not abspath: a symlinked models directory (or a symlink to the
    # model itself) makes two different-looking paths the same file, and this
    # guard is the one standing between --force and the user's original.
    if os.path.realpath(output_path) == os.path.realpath(input_path):
        raise ApplyError("--output would overwrite the input model; choose another path")
    if os.path.exists(output_path) and not args.force:
        raise ApplyError("%s already exists; pass --force to replace it" % output_path)

    segments = load_segments(args.segments)
    filaments, assignments, default = load_plan(args.plan)

    workdir = tempfile.mkdtemp(prefix="model-paint-")
    try:
        source, converted = prepare_source(input_path, workdir)
        threemf = ThreeMF(source)
        if converted:
            for info in threemf.infos.values():
                info.date_time = ZIP_EPOCH
        objects, painted, conflicts, cleared = resolve_assignments(
            threemf, segments, assignments, keep_existing=args.keep_existing_paint)
        total = sum(obj.triangle_count for obj in objects.values())
        expected = expected_counts(objects, painted)

        for (part, object_id), mapping in painted.items():
            threemf.paint_object(threemf.objects[(part, object_id)], mapping)
        settings = orca.set_filaments(
            threemf, [filaments[index] for index in sorted(filaments)],
            default_filament=default)

        parent = os.path.dirname(output_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        threemf.save(output_path)

        try:
            detail = verify_output(source, output_path, expected)
        except ApplyError:
            os.remove(output_path)
            raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # Overlapping segments conflict by the hundred, so name a few and count the
    # rest; a screen of identical warnings is a warning nobody reads.
    for conflict in conflicts[:CONFLICTS_SHOWN]:
        sys.stderr.write(
            "warning: object %s triangle %d assigned filament %d by %s, then "
            "filament %d by %s; the later assignment wins\n"
            % (conflict["object_id"], conflict["triangle"], conflict["was"],
               conflict["was_from"], conflict["now"], conflict["now_from"]))
    if len(conflicts) > CONFLICTS_SHOWN:
        sys.stderr.write("warning: %d more triangle(s) resolved the same way\n"
                         % (len(conflicts) - CONFLICTS_SHOWN))

    if not args.quiet:
        write_summary(sys.stdout, {
            "input": input_path,
            "output": output_path,
            "converted": converted,
            "triangle_count": total,
            "object_count": len(objects),
            "counts": expected,
            "filaments": filaments,
            "default_filament": default,
            "conflicts": conflicts,
            "cleared": cleared,
            "settings_existed": settings["part_existed"],
            "geometry_detail": detail,
        })
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Apply an approved paint plan to a model, producing a "
                    "painted 3MF whose geometry is proven unchanged.")
    parser.add_argument("--input", required=True, help="the STL or 3MF the plan was made for")
    parser.add_argument("--segments", required=True, help="segments.json from segment.py")
    parser.add_argument("--plan", required=True, help="the approved plan.json")
    parser.add_argument("--output", required=True, help="path for the painted 3MF")
    parser.add_argument("--force", action="store_true",
                        help="replace --output if it already exists")
    parser.add_argument("--keep-existing-paint", action="store_true",
                        help="leave paint already in the input on triangles the "
                             "plan does not assign (default: clear it)")
    parser.add_argument("--quiet", action="store_true", help="suppress the summary")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ApplyError, orca.OrcaError) as error:
        sys.stderr.write("apply_plan: %s\n" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
