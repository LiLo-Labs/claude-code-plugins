"""Filament colors and extruder assignments, so a painted 3MF opens as a project.

Paint alone is not enough. A model whose triangles carry `paint_color` states for
filaments 1..4 still opens in OrcaSlicer with whatever filaments the slicer had
loaded last, so the model the user approved is not the model on screen. Two
non-geometry parts carry that state:

  Metadata/project_settings.config  the project config, as JSON, holding the
                                    per-extruder `filament_colour` array
  Metadata/model_settings.config    per-object settings, including the extruder
                                    an object's unpainted triangles fall back to

Everything here is written through ThreeMF.replace_entry, so 3D/*.model -- the
only part that holds geometry -- is never rewritten, or even read.

Array position is the contract tying this module to the paint encoding: a
triangle painted with state n prints from extruder n, whose color is
`filament_colour[n - 1]`. Slots the plan skips are still written, because a short
array leaves the slicer to guess about every slot after the last one given.

On certainty, plainly: `filament_colour` and `filament_settings_id` are the keys
Bambu Studio and OrcaSlicer read for per-extruder color and preset. The rest of
MINIMAL_SETTINGS is a plausible floor for a file built from an STL, which has no
config to copy. When the input 3MF already carries a config, its keys are kept
untouched and only the filament arrays are rewritten -- that is the path worth
trusting, and the one the user's real files will take.
"""

import json
import re

from .encoding import MAX_FILAMENT

PROJECT_SETTINGS_PART = "Metadata/project_settings.config"
MODEL_SETTINGS_PART = "Metadata/model_settings.config"

# Slots the plan never names still need a value. Grey and a generic preset are
# the least surprising thing to show for a filament nobody asked for.
PLACEHOLDER_COLOUR = "#808080"
PLACEHOLDER_PRESET = "Generic PLA"

# Written only when the archive has no config of its own to extend.
MINIMAL_SETTINGS = {
    "from": "project",
    "name": "project_settings",
}

# name -> filament_type, longest match first so "PLA-CF" beats "PLA".
_TYPE_KEYWORDS = [
    "PLA-CF", "PETG-CF", "PAHT-CF", "PA-CF", "PC", "PETG", "PET", "PLA",
    "ABS", "ASA", "TPU", "PVA", "HIPS", "PA", "PPA", "PPS",
]

_OBJECT_BLOCK_RE = re.compile(r"<object\b[^>]*>.*?</object>", re.DOTALL)
_ID_ATTR_RE = re.compile(r'\bid\s*=\s*"([^"]*)"')
_EXTRUDER_META_RE = re.compile(
    r'<metadata\b[^>]*\bkey\s*=\s*"extruder"[^>]*/>')


class OrcaError(Exception):
    """Raised when project settings cannot be read or built."""


def normalize_hex(text):
    """'#1a1a1a', '1a1a1a' or 'f80' -> '#1A1A1A'."""
    value = str(text).strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
        raise OrcaError("cannot read %r as a hex color (want #RRGGBB)" % text)
    return "#" + value.upper()


def filament_type_for(name):
    """Guess the material from the filament's name; PLA when it says nothing."""
    upper = str(name or "").upper()
    for keyword in _TYPE_KEYWORDS:
        if keyword in upper:
            return keyword
    return "PLA"


def read_project_settings(threemf):
    """Existing project config as a dict, or None when the archive has none."""
    data = threemf.entries.get(PROJECT_SETTINGS_PART)
    if data is None:
        return None
    try:
        settings = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise OrcaError(
            "%s exists but is not readable JSON (%s); refusing to overwrite the "
            "print settings in it" % (PROJECT_SETTINGS_PART, error))
    if not isinstance(settings, dict):
        raise OrcaError(
            "%s does not contain a settings object" % PROJECT_SETTINGS_PART)
    return settings


def dumps_settings(settings):
    """Serialize the config the way the slicers write it: 4-space, sorted keys."""
    return json.dumps(settings, indent=4, sort_keys=True, ensure_ascii=False) + "\n"


def _merge(existing, values, placeholder):
    """Overwrite the slots the plan names; leave every other slot as it was.

    A plan that paints with filaments 2 and 4 says nothing about the filament in
    slot 1, and a 3MF that already had one loaded there should keep it. Slots
    that neither the plan nor the file describes get the placeholder, because a
    short array leaves the slicer guessing about the slots after the last one.
    """
    existing = [str(item) for item in existing] if isinstance(existing, list) else []
    merged = []
    for slot in range(max(len(existing), len(values))):
        value = values[slot] if slot < len(values) else None
        if value is None:
            value = existing[slot] if slot < len(existing) else placeholder
        merged.append(value)
    return merged


def set_filaments(threemf, filaments, default_filament=None):
    """Write per-extruder colors and presets into ``threemf``, in memory.

    ``filaments`` is the plan's filament list: dicts with ``index`` (1-based),
    ``name`` and ``hex``, optionally ``settings_id`` to name a real slicer preset
    and ``type`` to override the material guessed from the name.

    ``default_filament``, when given, becomes every object's extruder, which is
    what unpainted triangles print with.

    Returns a report describing what was written.
    """
    entries = []
    seen = set()
    for raw in filaments or []:
        index = raw.get("index")
        if index is None:
            raise OrcaError("filament entry %r has no index" % (raw,))
        index = int(index)
        if not 1 <= index <= MAX_FILAMENT:
            raise OrcaError(
                "filament index %d out of range 1..%d" % (index, MAX_FILAMENT))
        if index in seen:
            raise OrcaError("filament index %d listed twice" % index)
        seen.add(index)
        entries.append({
            "index": index,
            "name": str(raw.get("name") or "filament %d" % index),
            "hex": normalize_hex(raw.get("hex") or PLACEHOLDER_COLOUR),
            "settings_id": raw.get("settings_id") or raw.get("preset"),
            "type": raw.get("type"),
        })
    if not entries:
        raise OrcaError("no filaments to write")

    count = max(entry["index"] for entry in entries)
    colours = [None] * count
    presets = [None] * count
    types = [None] * count
    for entry in entries:
        slot = entry["index"] - 1
        colours[slot] = entry["hex"]
        # The user's own label ("Black PLA") is rarely a preset name, and a
        # preset the slicer cannot find raises a dialog on open. Only use it
        # when the plan says outright that it is one.
        presets[slot] = str(entry["settings_id"] or PLACEHOLDER_PRESET)
        types[slot] = str(entry["type"] or filament_type_for(entry["name"]))

    existing = read_project_settings(threemf)
    settings = dict(existing) if existing is not None else dict(MINIMAL_SETTINGS)
    settings["filament_colour"] = _merge(
        settings.get("filament_colour"), colours, PLACEHOLDER_COLOUR)
    settings["filament_settings_id"] = _merge(
        settings.get("filament_settings_id"), presets, PLACEHOLDER_PRESET)
    settings["filament_type"] = _merge(
        settings.get("filament_type"), types, "PLA")
    # Multi-nozzle machines color the toolhead from extruder_colour rather than
    # from the filament; keeping the two in step costs nothing.
    settings["extruder_colour"] = _merge(
        settings.get("extruder_colour"), colours, PLACEHOLDER_COLOUR)

    # Verified against a real OrcaSlicer 2.6.32 project file: it carries a
    # parallel `filament_multi_colour` array holding the same values. Left out of
    # step, the slicer draws the plate in the previous colors even though the
    # paint underneath is correct, which reads as the plugin having failed.
    settings["filament_multi_colour"] = list(settings["filament_colour"])

    # The same file keeps several companion arrays that must stay the same length
    # as filament_colour, or Orca indexes off the end of one of them.
    width = len(settings["filament_colour"])
    for key, filler in (("filament_ids", ""),
                        ("filament_colour_type", "1"),
                        ("default_filament_colour", ""),
                        ("filament_is_support", "0")):
        values = settings.get(key)
        if not isinstance(values, list) or not values:
            continue
        settings[key] = ([str(v) for v in values] + [values[-1]] * width)[:width]

    threemf.replace_entry(PROJECT_SETTINGS_PART, dumps_settings(settings))

    extruders = {}
    if default_filament is not None:
        extruders = {obj.object_id: int(default_filament)
                     for obj in threemf.mesh_objects()}
        set_object_extruders(threemf, extruders)

    return {
        "part_existed": existing is not None,
        "slots": count,
        "filament_colour": list(settings["filament_colour"]),
        "filament_settings_id": list(settings["filament_settings_id"]),
        "filament_type": list(settings["filament_type"]),
        "object_extruders": extruders,
    }


def model_settings_for(object_ids, extruders):
    """A model_settings.config from scratch, for archives that have none."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n<config>\n']
    for object_id in object_ids:
        parts.append('  <object id="%s">\n' % object_id)
        parts.append('    <metadata key="extruder" value="%d"/>\n'
                     % int(extruders.get(object_id, 1)))
        parts.append("  </object>\n")
    parts.append("</config>\n")
    return "".join(parts)


def set_object_extruders(threemf, extruders):
    """Set ``{object_id: extruder}`` in model_settings.config, in memory.

    Objects the mapping does not name keep whatever extruder they had. Objects
    the file does not mention are appended, since an object with no entry is an
    object the slicer assigns by its own defaults.
    """
    data = threemf.entries.get(MODEL_SETTINGS_PART)
    if data is None:
        object_ids = [obj.object_id for obj in threemf.mesh_objects()]
        threemf.replace_entry(
            MODEL_SETTINGS_PART, model_settings_for(object_ids, extruders))
        return set(extruders)

    text = data.decode("utf-8")
    touched = set()
    pieces = []
    cursor = 0
    for match in _OBJECT_BLOCK_RE.finditer(text):
        found = _ID_ATTR_RE.search(match.group(0))
        if not found or found.group(1) not in extruders:
            continue
        object_id = found.group(1)
        block = match.group(0)
        replacement = '<metadata key="extruder" value="%d"/>' % int(
            extruders[object_id])
        if _EXTRUDER_META_RE.search(block):
            block = _EXTRUDER_META_RE.sub(replacement, block, count=1)
        else:
            close = block.rfind("</object>")
            line = block.rfind("\n", 0, close)
            if line == -1:
                block = block[:close] + replacement + block[close:]
            else:
                indent = block[line + 1:close] + "  "
                block = (block[:line + 1] + indent + replacement + "\n"
                         + block[line + 1:])
        pieces.append(text[cursor:match.start()])
        pieces.append(block)
        cursor = match.end()
        touched.add(object_id)
    pieces.append(text[cursor:])
    updated = "".join(pieces)

    missing = [object_id for object_id in extruders if object_id not in touched]
    if missing:
        close = updated.rfind("</config>")
        if close == -1:
            raise OrcaError(
                "%s has no <config> element to extend" % MODEL_SETTINGS_PART)
        added = []
        for object_id in missing:
            added.append('  <object id="%s">\n    <metadata key="extruder" '
                         'value="%d"/>\n  </object>\n'
                         % (object_id, int(extruders[object_id])))
            touched.add(object_id)
        updated = updated[:close] + "".join(added) + updated[close:]

    threemf.replace_entry(MODEL_SETTINGS_PART, updated)
    return touched
