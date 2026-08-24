"""Render PNG previews of a model's segmentation or its paint plan.

The point of this script is approval: before a 14-hour print, the user should be
able to look at six pictures and say "yes, those are the horns" or "no, you
painted the tail". Claude uses the same images to check its own work.

Rendering is a small orthographic z-buffer rasterizer built on numpy rather than
a 3D toolkit, for three reasons. It needs no GPU, no display, and no GL context,
so it runs anywhere the rest of the plugin runs. It resolves hidden surfaces per
pixel, where matplotlib's Poly3DCollection sorts whole triangles by average depth
and visibly tears interlocking flexi joints apart. And it stays workable on the
meshes this plugin actually sees -- a detailed flexi dragon runs to several
hundred thousand triangles -- by culling back faces whenever the mesh proves
itself closed, and by batching the sub-pixel triangles that dense models are
mostly made of.

This script only ever reads geometry. It never writes a mesh.
"""

import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Camera directions as (azimuth, elevation) in degrees, describing where the eye
# sits relative to the model. Z is up, +X right, -Y toward the viewer, matching
# how a slicer shows a print bed.
VIEWS = {
    "front": (-90.0, 0.0),
    "back": (90.0, 0.0),
    "left": (180.0, 0.0),
    "right": (0.0, 0.0),
    "top": (-90.0, 89.9),
    "bottom": (-90.0, -89.9),
    "iso": (-55.0, 25.0),
}

DEFAULT_VIEWS = ["front", "back", "left", "right", "top", "iso"]

# Cycled by segment order so the same segmentation always gets the same colors.
# Chosen to stay distinguishable against the neutral background and each other.
SEGMENT_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4",
    "#f032e6", "#bfef45", "#fabed4", "#469990", "#dcbeff", "#9a6324",
    "#800000", "#aaffc3", "#808000", "#ffd8b1", "#000075", "#a9a9a9",
]

BACKGROUND = (0.93, 0.93, 0.94)
UNASSIGNED = (0.72, 0.72, 0.74)
INK = (0.13, 0.13, 0.15)

AMBIENT = 0.34
SUPERSAMPLE = 2

# Light fixed in camera space, up and to the left of the eye. A world-fixed light
# would leave whichever view faces away from it a flat unreadable silhouette.
LIGHT_CAMERA = (-0.40, 0.55, 0.80)

# Diffuse shading alone is multiplicative, so it vanishes on the dark filaments
# this plugin paints with constantly: black horns on a black body come out as one
# flat silhouette. These two terms are added rather than multiplied, so form
# still reads at #1a1a1a.
SPECULAR = 0.20
SPECULAR_POWER = 6.0
RIM = 0.13


class PreviewError(Exception):
    """Anything the user can fix by changing the command line or the inputs."""


# -- input ------------------------------------------------------------------

def load_mesh(path):
    """Load an STL or 3MF as (vertices, faces, objects).

    ``objects`` is ``[(name, base_face_index, face_count), ...]`` so that
    segment face indices scoped to one object of a multi-object 3MF can be
    mapped into the concatenated face array.
    """
    if not os.path.exists(path):
        raise PreviewError("no such file: %s" % path)

    if path.lower().endswith(".3mf"):
        from paintlib.threemf import ThreeMF

        archive = ThreeMF(path)
        meshes = archive.mesh_objects()
        if not meshes:
            raise PreviewError("no mesh objects found in %s" % path)
        vertices, faces, objects = [], [], []
        vertex_base = 0
        face_base = 0
        for obj in meshes:
            vertices.extend(obj.vertices)
            faces.extend((a + vertex_base, b + vertex_base, c + vertex_base)
                         for a, b, c in obj.triangles)
            objects.append((obj.object_id, face_base, obj.triangle_count))
            vertex_base += len(obj.vertices)
            face_base += obj.triangle_count
        return (np.asarray(vertices, dtype=np.float64),
                np.asarray(faces, dtype=np.int64), objects)

    import trimesh

    # process=False is not optional anywhere in this plugin: trimesh's default
    # merges vertices, which silently renumbers the faces the segmentation and
    # the plan refer to.
    loaded = trimesh.load(path, process=False, force="mesh")
    vertices = np.asarray(loaded.vertices, dtype=np.float64)
    faces = np.asarray(loaded.faces, dtype=np.int64)
    if not len(faces):
        raise PreviewError("%s contains no triangles" % path)
    # "1" rather than the file name: build.from_stl gives the converted 3MF's
    # single object id 1, and segment.py labels an STL's faces the same way.
    return vertices, faces, [("1", 0, len(faces))]


def _read_json(path, what):
    if not os.path.exists(path):
        raise PreviewError("no such %s file: %s" % (what, path))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except ValueError as error:
        raise PreviewError("%s is not valid JSON: %s" % (path, error))


def _first_key(source, names):
    for name in names:
        if name in source:
            return source[name]
    return None


def _segment_entries(data):
    """Pull the segment records out of whatever shape the file arrived in."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return None

    entries = _first_key(data, ("segments", "regions", "features"))
    if entries is not None:
        return entries

    # segment.py's own layout: segments live per object, and only the object
    # carries the id that scopes their face numbering.
    objects = data.get("objects")
    if isinstance(objects, list):
        flattened = []
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            for entry in obj.get("segments") or []:
                if isinstance(entry, dict):
                    entry = dict(entry)
                    entry.setdefault("object_id", obj.get("object_id"))
                    flattened.append(entry)
        return flattened
    return data


def _label_for(entry, identifier, limit=52):
    """What to call a segment in the legend.

    An id like 's01' tells the user nothing, so fall back to the shape
    description the segmentation wrote, which is the whole point of looking at
    the picture: it says what the segmenter thinks it found.
    """
    label = _first_key(entry, ("label", "name"))
    if label is None:
        hint = entry.get("shape_hint")
        label = "%s  %s" % (identifier, hint) if hint else str(identifier)
    label = str(label)
    return label if len(label) <= limit else label[:limit - 3].rstrip() + "..."


def read_segments(path):
    """Parse segments.json into ``[{id, label, faces, object_id}, ...]``.

    Deliberately tolerant about shape, because the segmentation step is a
    separate tool: segments nested under objects, a flat list, or a mapping of
    id to face list all read the same way. Segment order is preserved, which is
    what makes the palette assignment stable.
    """
    data = _read_json(path, "segments")
    entries = _segment_entries(data)

    if isinstance(entries, dict):
        entries = [{"id": key, "faces": value} for key, value in entries.items()]
    if not isinstance(entries, list):
        raise PreviewError("%s: expected a list of segments" % path)

    segments = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise PreviewError("%s: segment %d is not an object" % (path, position))
        identifier = _first_key(entry, ("id", "segment_id", "name", "label"))
        if identifier is None:
            identifier = "segment-%d" % position
        raw_faces = _first_key(
            entry, ("faces", "face_indices", "facets", "triangles",
                    "triangle_indices"))
        if raw_faces is None:
            raise PreviewError(
                "%s: segment %r has no face list (expected one of faces, "
                "face_indices, triangles)" % (path, identifier))
        faces = np.asarray(raw_faces, dtype=np.int64).ravel()
        object_id = _first_key(entry, ("object_id", "object", "objectid"))
        segments.append({
            "id": str(identifier),
            "label": _label_for(entry, identifier),
            "faces": faces,
            "object_id": None if object_id is None else str(object_id),
        })
    if not segments:
        raise PreviewError("%s contains no segments" % path)
    return segments


def read_plan(path):
    """Parse plan.json into (filaments, assignments, default_filament)."""
    data = _read_json(path, "plan")
    if not isinstance(data, dict):
        raise PreviewError("%s: expected a plan object" % path)

    filaments = {}
    for entry in data.get("filaments") or []:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if index is None:
            continue
        filaments[int(index)] = {
            "index": int(index),
            "name": str(entry.get("name") or "filament %s" % index),
            "hex": str(_first_key(entry, ("hex", "color", "colour")) or "#808080"),
        }
    if not filaments:
        raise PreviewError("%s lists no filaments" % path)

    assignments = []
    for entry in data.get("assignments") or []:
        if not isinstance(entry, dict):
            continue
        segment_id = _first_key(entry, ("segment_id", "segment", "id"))
        if segment_id is None:
            continue
        assignments.append({
            "segment_id": str(segment_id),
            "filament": int(entry.get("filament") or 0),
            "faces": entry.get("faces"),
        })

    default = data.get("default_filament")
    default = int(default) if default is not None else min(filaments)
    return filaments, assignments, default


def parse_hex(text):
    """'#1a1a1a' or 'f80' -> (r, g, b) floats in 0..1."""
    value = str(text).strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise PreviewError("cannot read %r as a hex color" % text)
    try:
        return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        raise PreviewError("cannot read %r as a hex color" % text)


# -- face colors ------------------------------------------------------------

def _face_slots(segments, objects, face_count):
    """Resolve each segment's face indices into the concatenated face array."""
    bases = {name: base for name, base, _count in objects}
    resolved = []
    for segment in segments:
        faces = segment["faces"]
        base = 0
        # With one object there is nothing to disambiguate, so an id that does
        # not match is a naming difference, not a mistake worth failing over.
        if segment["object_id"] is not None and len(objects) > 1:
            if segment["object_id"] not in bases:
                raise PreviewError(
                    "segment %r names object %r, which is not in the model"
                    % (segment["id"], segment["object_id"]))
            base = bases[segment["object_id"]]
        faces = faces + base
        inside = (faces >= 0) & (faces < face_count)
        if not inside.all():
            sys.stderr.write(
                "warning: segment %r references %d face index/indices outside "
                "the model's %d faces; ignoring them\n"
                % (segment["id"], int((~inside).sum()), face_count))
        resolved.append(faces[inside])
    return resolved


def colors_from_segments(segments, objects, face_count):
    """Distinct palette color per segment; unassigned faces stay neutral."""
    colors = np.tile(np.asarray(UNASSIGNED, dtype=np.float64), (face_count, 1))
    slots = _face_slots(segments, objects, face_count)
    legend = []
    for position, (segment, faces) in enumerate(zip(segments, slots)):
        rgb = parse_hex(SEGMENT_PALETTE[position % len(SEGMENT_PALETTE)])
        colors[faces] = rgb
        legend.append((segment["label"], rgb, len(faces)))
    covered = int(sum(len(faces) for faces in slots))
    if covered < face_count:
        legend.append(("unsegmented", UNASSIGNED, face_count - covered))
    return colors, legend


def colors_from_plan(segments, objects, face_count, plan):
    """Color every face with its assigned filament's real hex color."""
    filaments, assignments, default = plan
    if default not in filaments:
        raise PreviewError(
            "plan default_filament %d is not one of the listed filaments (%s)"
            % (default, ", ".join(str(i) for i in sorted(filaments))))

    by_id = {}
    if segments is not None:
        slots = _face_slots(segments, objects, face_count)
        by_id = {segment["id"]: faces for segment, faces in zip(segments, slots)}

    assigned = np.full(face_count, default, dtype=np.int64)
    for entry in assignments:
        if entry["filament"] not in filaments:
            sys.stderr.write(
                "warning: assignment for %r names filament %d, which the plan "
                "does not list; leaving those faces on the default\n"
                % (entry["segment_id"], entry["filament"]))
            continue
        if entry["faces"] is not None:
            faces = np.asarray(entry["faces"], dtype=np.int64).ravel()
            faces = faces[(faces >= 0) & (faces < face_count)]
        elif entry["segment_id"] in by_id:
            faces = by_id[entry["segment_id"]]
        else:
            raise PreviewError(
                "plan assigns segment %r, which is not in the segments file "
                "(pass the segments.json the plan was written against)"
                % entry["segment_id"])
        assigned[faces] = entry["filament"]

    colors = np.zeros((face_count, 3), dtype=np.float64)
    legend = []
    for index in sorted(filaments):
        rgb = parse_hex(filaments[index]["hex"])
        mask = assigned == index
        colors[mask] = rgb
        if mask.any():
            legend.append(("%d  %s" % (index, filaments[index]["name"]),
                           rgb, int(mask.sum())))
    return colors, legend


# -- camera -----------------------------------------------------------------

def view_basis(azimuth, elevation):
    """(right, up, eye) for a view, as a right-handed screen basis.

    ``eye`` points from the model toward the camera, so a larger dot product
    with it means closer to the viewer.
    """
    az = math.radians(azimuth)
    el = math.radians(elevation)
    eye = np.array([math.cos(el) * math.cos(az),
                    math.cos(el) * math.sin(az),
                    math.sin(el)])
    eye /= np.linalg.norm(eye)
    right = np.cross([0.0, 0.0, 1.0], eye)
    norm = np.linalg.norm(right)
    if norm < 1e-9:                       # straight up or down: pick a fixed roll
        right = np.array([1.0, 0.0, 0.0])
    else:
        right /= norm
    up = np.cross(eye, right)
    return right, up, eye


def fit_scale(vertices, views, size, margin):
    """One pixels-per-mm scale that fits every requested view.

    Shared across views so the model does not change size between pictures,
    which is what makes a contact sheet comparable.
    """
    span = size - 2 * margin
    scale = None
    for name in views:
        right, up, _eye = view_basis(*VIEWS[name])
        x = vertices @ right
        y = vertices @ up
        extent = max(x.max() - x.min(), y.max() - y.min())
        if extent < 1e-9:
            continue
        candidate = span / extent
        scale = candidate if scale is None else min(scale, candidate)
    if scale is None:
        raise PreviewError("the model has zero extent; nothing to render")
    return scale


# -- rasterizer -------------------------------------------------------------

def can_backface_cull(vertices, faces):
    """True when every edge is shared by exactly two oppositely-wound triangles.

    Only such a mesh can be back-face culled safely, and culling halves the
    rasterizer's work on the several-hundred-thousand-triangle models this
    plugin is aimed at. A mesh that fails the test -- an open shell, or one with
    the flipped normals STL exporters sometimes leave behind -- gets rendered
    two-sided instead, which is slower but never punches holes in the preview.

    Vertices are matched by position for the test, because an STL read the only
    way this plugin ever reads one (process=False, no vertex merging) stores
    every triangle's corners separately and shares no indices at all. The
    matching happens in a throwaway array: the mesh that gets rendered, and the
    face numbering the segments refer to, are untouched.
    """
    grid = np.ascontiguousarray(np.where(vertices == 0.0, 0.0, vertices))
    packed = grid.view([("x", grid.dtype), ("y", grid.dtype), ("z", grid.dtype)])
    _unique, canonical = np.unique(packed.ravel(), return_inverse=True)
    faces = canonical.ravel()[faces]

    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    low = np.minimum(edges[:, 0], edges[:, 1])
    high = np.maximum(edges[:, 0], edges[:, 1])
    forward = edges[:, 0] < edges[:, 1]

    keys = low * (int(faces.max()) + 1) + high
    order = np.argsort(keys, kind="stable")
    keys = keys[order]
    forward = forward[order]

    if len(keys) % 2:
        return False
    # After sorting, a closed mesh pairs the shared edges up two by two.
    if not np.array_equal(keys[0::2], keys[1::2]):
        return False
    return bool(np.all(forward[0::2] != forward[1::2]))


def _light_for(right, up, eye):
    light = (LIGHT_CAMERA[0] * right + LIGHT_CAMERA[1] * up
             + LIGHT_CAMERA[2] * eye)
    return light / np.linalg.norm(light)


def _shade(colors, normals, light, eye):
    """Diffuse plus a white specular and a silhouette rim, all fixed."""
    diffuse = np.clip(normals @ light, 0.0, 1.0)
    lit = colors * (AMBIENT + (1.0 - AMBIENT) * diffuse)[:, None]

    half = light + eye
    half /= np.linalg.norm(half)
    highlight = np.clip(normals @ half, 0.0, 1.0) ** SPECULAR_POWER
    rim = (1.0 - np.clip(normals @ eye, 0.0, 1.0)) ** 3

    return np.clip(lit + (SPECULAR * highlight + RIM * rim)[:, None], 0.0, 1.0)


def render_view(vertices, faces, colors, view, scale, size, cull=False):
    """Rasterize one view; returns an (size, size, 3) float image in 0..1."""
    right, up, eye = view_basis(*VIEWS[view])
    work = size * SUPERSAMPLE

    x = vertices @ right
    y = vertices @ up
    z = vertices @ eye
    cx = (x.min() + x.max()) / 2.0
    cy = (y.min() + y.max()) / 2.0
    step = scale * SUPERSAMPLE
    px = (x - cx) * step + work / 2.0
    py = work / 2.0 - (y - cy) * step      # screen y grows downward

    tri_x = px[faces]
    tri_y = py[faces]
    tri_z = z[faces]

    # Flipping normals toward the eye is what makes the two-sided fallback shade
    # correctly: a mesh that failed the cull test keeps its back faces, and they
    # must be lit as the surface the viewer is actually looking at.
    normals = np.cross(vertices[faces][:, 1] - vertices[faces][:, 0],
                       vertices[faces][:, 2] - vertices[faces][:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    normals = normals / np.where(lengths > 1e-12, lengths, 1.0)[:, None]
    normals = np.where((normals @ eye)[:, None] < 0, -normals, normals)
    shaded = _shade(colors, normals, _light_for(right, up, eye), eye)

    image = np.empty((work, work, 3), dtype=np.float64)
    image[:] = BACKGROUND
    depth = np.full((work, work), -np.inf)

    area = ((tri_x[:, 1] - tri_x[:, 0]) * (tri_y[:, 2] - tri_y[:, 0])
            - (tri_x[:, 2] - tri_x[:, 0]) * (tri_y[:, 1] - tri_y[:, 0]))
    alive = np.abs(area) > 1e-12
    if cull:
        # Screen y grows downward, so an outward-facing triangle projects with
        # negative signed area.
        alive &= area < 0

    lo_x = np.floor(tri_x.min(axis=1)).astype(np.int64)
    hi_x = np.floor(tri_x.max(axis=1)).astype(np.int64)
    lo_y = np.floor(tri_y.min(axis=1)).astype(np.int64)
    hi_y = np.floor(tri_y.max(axis=1)).astype(np.int64)
    onscreen = (hi_x >= 0) & (lo_x < work) & (hi_y >= 0) & (lo_y < work)

    # Sub-pixel triangles are common once a model is dense enough, and each one
    # would otherwise cost a handful of numpy calls to fill a single pixel. They
    # go through one batched pass; only the larger ones get a barycentric fill.
    tiny = alive & onscreen & (hi_x - lo_x <= 1) & (hi_y - lo_y <= 1)
    _draw_tiny(image, depth, np.nonzero(tiny)[0], lo_x, lo_y, hi_x, hi_y,
               tri_z, shaded, work)

    big = np.nonzero(alive & onscreen & ~tiny)[0]
    _draw_large(image, depth, big, tri_x, tri_y, tri_z, area, shaded,
                lo_x, lo_y, hi_x, hi_y, work)

    return image.reshape(size, SUPERSAMPLE, size, SUPERSAMPLE, 3).mean(axis=(1, 3))


def _draw_tiny(image, depth, index, lo_x, lo_y, hi_x, hi_y, tri_z, shaded, work):
    """Splat sub-pixel triangles over their (at most 2x2) pixel footprint.

    Painting the whole footprint rather than testing coverage over-inks the
    silhouette by up to a pixel, which is invisible, whereas testing coverage at
    this size drops triangles that miss every pixel center and pinholes the
    surface.
    """
    if not len(index):
        return
    z = tri_z[index].mean(axis=1)
    color = shaded[index]

    xs, ys, zs, cs = [], [], [], []
    for dx in (0, 1):
        for dy in (0, 1):
            px = lo_x[index] + dx
            py = lo_y[index] + dy
            keep = ((px <= hi_x[index]) & (py <= hi_y[index])
                    & (px >= 0) & (px < work) & (py >= 0) & (py < work))
            xs.append(px[keep])
            ys.append(py[keep])
            zs.append(z[keep])
            cs.append(color[keep])

    px = np.concatenate(xs)
    py = np.concatenate(ys)
    pz = np.concatenate(zs)
    pc = np.concatenate(cs)

    # Sorting far-to-near turns plain scattered assignment into a depth test:
    # for pixels written more than once the last (nearest) write survives.
    order = np.argsort(pz, kind="stable")
    px, py, pz, pc = px[order], py[order], pz[order], pc[order]
    depth[py, px] = pz
    image[py, px] = pc


def _draw_large(image, depth, index, tri_x, tri_y, tri_z, area, shaded,
                lo_x, lo_y, hi_x, hi_y, work):
    for i in index:
        x0, x1, x2 = tri_x[i]
        y0, y1, y2 = tri_y[i]
        z0, z1, z2 = tri_z[i]
        min_x = max(int(lo_x[i]), 0)
        max_x = min(int(hi_x[i]), work - 1)
        min_y = max(int(lo_y[i]), 0)
        max_y = min(int(hi_y[i]), work - 1)
        if min_x > max_x or min_y > max_y:
            continue

        gx = np.arange(min_x, max_x + 1) + 0.5
        gy = (np.arange(min_y, max_y + 1) + 0.5)[:, None]
        inv = 1.0 / area[i]
        w0 = ((x1 - gx) * (y2 - gy) - (x2 - gx) * (y1 - gy)) * inv
        w1 = ((x2 - gx) * (y0 - gy) - (x0 - gx) * (y2 - gy)) * inv
        w2 = 1.0 - w0 - w1
        covered = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
        if not covered.any():
            continue

        window = depth[min_y:max_y + 1, min_x:max_x + 1]
        zz = w0 * z0 + w1 * z1 + w2 * z2
        hit = covered & (zz > window)
        if not hit.any():
            continue
        window[hit] = zz[hit]
        image[min_y:max_y + 1, min_x:max_x + 1][hit] = shaded[i]


# -- output -----------------------------------------------------------------

def _pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise PreviewError(
            "preview needs Pillow to write PNGs: pip install pillow")
    return Image, ImageDraw, ImageFont


def _to_uint8(image):
    return (np.clip(image, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def _rgb255(rgb):
    """A 0..1 triple as the int tuple Pillow wants."""
    return tuple(int(round(min(max(c, 0.0), 1.0) * 255)) for c in rgb)


def _font(size):
    _Image, _Draw, ImageFont = _pillow()
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                     # Pillow < 10.1: fixed-size bitmap only
        return ImageFont.load_default()


def write_png(image, path):
    Image, _Draw, _Font = _pillow()
    Image.fromarray(_to_uint8(image)).save(path, "PNG", optimize=True)
    return path


def contact_sheet(views, legend, title, path, size):
    """One sheet with every view labelled, plus the color legend beneath."""
    Image, ImageDraw, _Font = _pillow()

    gutter = 18
    columns = min(3, len(views))
    rows = int(math.ceil(len(views) / float(columns)))
    label = _font(max(22, size // 32))
    heading = _font(max(26, size // 26))

    swatch = max(20, size // 36)
    line_height = swatch + 14
    legend_columns = max(1, min(3, columns))
    legend_rows = int(math.ceil(len(legend) / float(legend_columns)))
    legend_height = (line_height * legend_rows + gutter) if legend else 0
    header = heading.getbbox("Ag")[3] + 2 * gutter

    width = columns * size + (columns + 1) * gutter
    height = header + rows * size + (rows + 1) * gutter + legend_height

    sheet = Image.new("RGB", (width, height), _rgb255(BACKGROUND))
    draw = ImageDraw.Draw(sheet)
    ink = _rgb255(INK)
    draw.text((gutter, gutter), title, font=heading, fill=ink)

    for position, (name, image) in enumerate(views):
        column = position % columns
        row = position // columns
        x = gutter + column * (size + gutter)
        y = header + gutter + row * (size + gutter)
        sheet.paste(Image.fromarray(_to_uint8(image)), (x, y))
        draw.rectangle([x, y, x + size - 1, y + size - 1], outline=(180, 180, 186))
        draw.text((x + 12, y + 8), name, font=label, fill=ink)

    y = header + rows * (size + gutter) + gutter
    column_width = (width - 2 * gutter) // legend_columns
    for position, (name, rgb, count) in enumerate(legend):
        column = position // legend_rows
        row = position % legend_rows
        x = gutter + column * column_width
        top = y + row * line_height
        draw.rectangle([x, top, x + swatch, top + swatch], fill=_rgb255(rgb),
                       outline=(120, 120, 126))
        draw.text((x + swatch + 12, top + 1),
                  "%s  (%d faces)" % (name, count), font=label, fill=ink)

    sheet.save(path, "PNG", optimize=True)
    return path


# -- cli --------------------------------------------------------------------

def parse_views(text):
    names = []
    for raw in text.split(","):
        name = raw.strip().lower()
        if not name:
            continue
        if name not in VIEWS:
            raise PreviewError(
                "unknown view %r; choose from %s"
                % (name, ", ".join(sorted(VIEWS))))
        if name not in names:
            names.append(name)
    if not names:
        raise PreviewError("no views requested")
    return names


def build_parser():
    parser = argparse.ArgumentParser(
        description="Render PNG previews of a model's segmentation or paint plan.")
    parser.add_argument("--input", required=True,
                        help="model to render (.stl or .3mf)")
    parser.add_argument("--segments", help="segments.json to color by segment")
    parser.add_argument("--plan", help="plan.json to color by assigned filament")
    parser.add_argument("--output", required=True,
                        help="directory to write the PNGs into")
    parser.add_argument("--views", default=",".join(DEFAULT_VIEWS),
                        help="comma-separated: %s" % ", ".join(sorted(VIEWS)))
    parser.add_argument("--size", type=int, default=900,
                        help="pixels per view (default 900)")
    return parser


def run(args):
    views = parse_views(args.views)
    if args.size < 200:
        raise PreviewError("--size %d is too small to read; use 800 or more"
                           % args.size)

    vertices, faces, objects = load_mesh(args.input)
    face_count = len(faces)

    segments = read_segments(args.segments) if args.segments else None
    if args.plan:
        plan = read_plan(args.plan)
        colors, legend = colors_from_plan(segments, objects, face_count, plan)
        mode, title = "plan", "paint plan"
    elif segments is not None:
        colors, legend = colors_from_segments(segments, objects, face_count)
        mode, title = "segments", "segmentation"
    else:
        colors = np.tile(np.asarray(UNASSIGNED), (face_count, 1))
        legend = [("unpainted", UNASSIGNED, face_count)]
        mode, title = "model", "model"

    os.makedirs(args.output, exist_ok=True)
    scale = fit_scale(vertices, views, args.size, margin=max(12, args.size // 24))
    cull = can_backface_cull(vertices, faces)

    rendered = []
    written = []
    for name in views:
        image = render_view(vertices, faces, colors, name, scale, args.size, cull)
        path = os.path.join(args.output, "%s-%s.png" % (mode, name))
        write_png(image, path)
        rendered.append((name, image))
        written.append(path)

    label = "%s: %s (%d faces)" % (
        title, os.path.basename(args.input), face_count)
    sheet = contact_sheet(rendered, legend, label,
                          os.path.join(args.output, "%s-contact-sheet.png" % mode),
                          args.size)
    written.append(sheet)

    for name, _rgb, count in legend:
        print("  %-40s %7d faces  %5.1f%%"
              % (name, count, 100.0 * count / face_count))
    for path in written:
        print(path)
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except PreviewError as error:
        sys.stderr.write("preview: %s\n" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
