"""Read, paint, and write 3MF files without ever disturbing the geometry.

The guarantee this module exists to provide: painting a model changes only
`paint_color` attributes. Vertex coordinates, triangle indices, triangle order,
object transforms, and every unrelated part in the archive survive byte-for-byte.

That is why the paint step is a surgical text edit rather than a parse-and-
reserialize. Round-tripping through an XML DOM would renormalize whitespace,
attribute order, and float formatting -- all harmless in principle, but on an
interlocking flexi model "harmless in principle" is not a claim worth betting a
14-hour print on. Bytes we did not deliberately change are bytes we did not
change at all.
"""

import re
import shutil
import zipfile
from collections import OrderedDict

from .encoding import encode_solid, filaments_used

MODEL_PART_RE = re.compile(r"^3D/.*\.model$", re.IGNORECASE)

_OBJECT_OPEN_RE = re.compile(r"<object\b[^>]*>", re.DOTALL)
_ID_ATTR_RE = re.compile(r'\bid\s*=\s*"([^"]*)"')
_TYPE_ATTR_RE = re.compile(r'\btype\s*=\s*"([^"]*)"')
_TRIANGLES_BLOCK_RE = re.compile(r"<triangles\b[^>]*>(.*?)</triangles>", re.DOTALL)
_VERTICES_BLOCK_RE = re.compile(r"<vertices\b[^>]*>(.*?)</vertices>", re.DOTALL)
_TRIANGLE_RE = re.compile(r"<triangle\b[^>]*?/>", re.DOTALL)
_VERTEX_RE = re.compile(r"<vertex\b[^>]*?/>", re.DOTALL)
_PAINT_ATTR_RE = re.compile(r'\s*paint_color\s*=\s*"[^"]*"')


def _attr(text, name):
    match = re.search(r'\b%s\s*=\s*"([^"]*)"' % re.escape(name), text)
    return match.group(1) if match else None


class MeshObject(object):
    """One `<object>` inside one `.model` part of the archive."""

    def __init__(self, part, object_id, xml_start, xml_end, text):
        self.part = part
        self.object_id = object_id
        self.xml_start = xml_start          # offsets into the part's full text
        self.xml_end = xml_end
        self._text = text                   # just this object's XML
        self.vertices = []                  # list of (x, y, z) floats
        self.triangles = []                 # list of (v1, v2, v3) ints
        self.paint = []                     # list of paint_color strings ('' = unpainted)
        self._triangle_spans = []           # (start, end) offsets within self._text
        self._parse()

    def _parse(self):
        vblock = _VERTICES_BLOCK_RE.search(self._text)
        if vblock:
            for match in _VERTEX_RE.finditer(vblock.group(1)):
                el = match.group(0)
                self.vertices.append((
                    float(_attr(el, "x")), float(_attr(el, "y")), float(_attr(el, "z"))))

        tblock = _TRIANGLES_BLOCK_RE.search(self._text)
        if not tblock:
            return
        base = tblock.start(1)
        for match in _TRIANGLE_RE.finditer(tblock.group(1)):
            el = match.group(0)
            self.triangles.append((
                int(_attr(el, "v1")), int(_attr(el, "v2")), int(_attr(el, "v3"))))
            self.paint.append(_attr(el, "paint_color") or "")
            self._triangle_spans.append((base + match.start(), base + match.end()))

    # -- introspection ----------------------------------------------------

    @property
    def triangle_count(self):
        return len(self.triangles)

    @property
    def is_painted(self):
        return any(self.paint)

    def filament_histogram(self):
        """Triangle counts per filament index; key 0 means unpainted."""
        counts = {}
        for value in self.paint:
            if not value:
                counts[0] = counts.get(0, 0) + 1
                continue
            used = filaments_used(value)
            if not used:
                counts[0] = counts.get(0, 0) + 1
            else:
                # A subdivided triangle can carry several filaments. Credit each
                # once -- this is a summary, not an area measurement.
                for filament in used:
                    counts[filament] = counts.get(filament, 0) + 1
        return counts

    # -- mutation ---------------------------------------------------------

    def apply_paint(self, assignments):
        """Set paint from ``{triangle_index: filament}``; filament 0 clears it.

        Returns the rewritten XML for this object. Triangles absent from
        ``assignments`` keep whatever paint they already had.
        """
        for index in assignments:
            if not 0 <= index < self.triangle_count:
                raise IndexError(
                    "triangle %d out of range (object %s has %d)"
                    % (index, self.object_id, self.triangle_count))

        pieces = []
        cursor = 0
        for index, (start, end) in enumerate(self._triangle_spans):
            if index not in assignments:
                continue
            element = self._text[start:end]
            stripped = _PAINT_ATTR_RE.sub("", element)
            value = encode_solid(assignments[index])
            if value:
                stripped = stripped[:-2].rstrip() + ' paint_color="%s"/>' % value
            pieces.append(self._text[cursor:start])
            pieces.append(stripped)
            cursor = end
        pieces.append(self._text[cursor:])
        return "".join(pieces)


class ThreeMF(object):
    """An open 3MF archive, held in memory."""

    def __init__(self, path):
        self.path = str(path)
        self.entries = OrderedDict()        # name -> bytes
        self.infos = OrderedDict()          # name -> ZipInfo
        with zipfile.ZipFile(self.path, "r") as archive:
            for info in archive.infolist():
                self.infos[info.filename] = info
                self.entries[info.filename] = archive.read(info.filename)
        self._texts = {}                    # part name -> decoded text
        self.objects = OrderedDict()        # (part, object_id) -> MeshObject
        self._load_objects()

    # -- loading ----------------------------------------------------------

    @property
    def model_parts(self):
        return [name for name in self.entries if MODEL_PART_RE.match(name)]

    def _text_for(self, part):
        if part not in self._texts:
            self._texts[part] = self.entries[part].decode("utf-8")
        return self._texts[part]

    def _load_objects(self):
        for part in self.model_parts:
            text = self._text_for(part)
            for match in _OBJECT_OPEN_RE.finditer(text):
                object_id = _ID_ATTR_RE.search(match.group(0))
                if not object_id:
                    continue
                close = text.find("</object>", match.end())
                if close == -1:
                    continue
                end = close + len("</object>")
                obj = MeshObject(part, object_id.group(1), match.start(), end,
                                 text[match.start():end])
                if obj.triangle_count:
                    self.objects[(part, obj.object_id)] = obj

    def mesh_objects(self):
        """Objects that actually carry geometry, in archive order."""
        return list(self.objects.values())

    # -- mutation ---------------------------------------------------------

    def paint_object(self, obj, assignments):
        """Apply ``{triangle_index: filament}`` to one object, in memory."""
        new_xml = obj.apply_paint(assignments)
        text = self._text_for(obj.part)
        updated = text[:obj.xml_start] + new_xml + text[obj.xml_end:]
        delta = len(new_xml) - (obj.xml_end - obj.xml_start)
        self._texts[obj.part] = updated
        self.entries[obj.part] = updated.encode("utf-8")

        # Keep sibling objects in the same part addressable after the edit.
        for other in self.objects.values():
            if other.part == obj.part and other.xml_start > obj.xml_start:
                other.xml_start += delta
                other.xml_end += delta
        obj.xml_end = obj.xml_start + len(new_xml)
        obj._text = new_xml
        obj._triangle_spans = []
        obj.paint = []
        obj.triangles = []
        obj.vertices = []
        obj._parse()

    def replace_entry(self, name, data):
        """Replace or add a non-geometry part (settings, thumbnails, ...)."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.entries[name] = data
        self._texts.pop(name, None)

    # -- writing ----------------------------------------------------------

    def save(self, path):
        """Write the archive out, preserving entry order and compression."""
        path = str(path)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in self.entries.items():
                info = self.infos.get(name)
                if info is not None:
                    out = zipfile.ZipInfo(name, date_time=info.date_time)
                    out.compress_type = info.compress_type
                    out.external_attr = info.external_attr
                    out.internal_attr = info.internal_attr
                    out.create_system = info.create_system
                else:
                    out = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    out.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(out, data)
        return path

    def save_beside(self, suffix="-painted"):
        """Save next to the source file, never over it."""
        if self.path.lower().endswith(".3mf"):
            target = self.path[:-4] + suffix + ".3mf"
        else:
            target = self.path + suffix + ".3mf"
        return self.save(target)


def geometry_matches(path_a, path_b):
    """True when two 3MFs carry identical meshes, paint aside.

    This is the safety assertion behind every paint operation: same objects,
    same vertices, same triangle indices, same order.
    """
    a, b = ThreeMF(path_a), ThreeMF(path_b)
    objects_a, objects_b = a.mesh_objects(), b.mesh_objects()
    if len(objects_a) != len(objects_b):
        return False, "object count %d != %d" % (len(objects_a), len(objects_b))
    for oa, ob in zip(objects_a, objects_b):
        if oa.object_id != ob.object_id:
            return False, "object id %s != %s" % (oa.object_id, ob.object_id)
        if oa.vertices != ob.vertices:
            return False, "vertices differ on object %s" % oa.object_id
        if oa.triangles != ob.triangles:
            return False, "triangle indices differ on object %s" % oa.object_id
    return True, "%d object(s), geometry identical" % len(objects_a)
