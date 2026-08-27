"""Presentation renders of a finished scheme (spec §11 export, guide renders).

Separate from `render.py` on purpose. Everything in `render.py` exists to MEASURE -- its
buffers feed cues and admission, and a light there is part of an experiment. This module
exists to SHOW, and the only thing it has to be faithful to is what the print will
actually look like: four flat filament colours on a physical surface, read by eye.

So the shading here is deliberately physical rather than diagnostic. Flat colour on a
detailed surface reads as a sticker without ambient occlusion, because on a real print
what separates one rib from the next is the shadow between them, not the pigment.
"""

import numpy as np

from . import render as render_module


def lab_to_srgb(lab):
    """CIE Lab to sRGB, via colour-science, clipped to gamut."""
    from colour import Lab_to_XYZ, XYZ_to_sRGB
    rgb = XYZ_to_sRGB(Lab_to_XYZ(np.asarray(lab, dtype=float)))
    return np.clip(rgb, 0.0, 1.0)


def face_colours(mesh, vertex_lab):
    """Per-face sRGB from per-vertex Lab, averaged in Lab and converted once."""
    lab = np.asarray(vertex_lab, dtype=float)[mesh.faces].mean(axis=1)
    return lab_to_srgb(lab)


def ambient_occlusion(mesh, samples=48, seed=5):
    """How enclosed each face is, by ray casting from its own centre.

    This is the shadow that makes a flat-coloured print look like an object. It is
    computed on the geometry rather than in screen space because it belongs to the model
    and must not swim when the camera moves.
    """
    rng = np.random.default_rng(seed)
    centres = mesh.triangles.mean(axis=1)
    normals = mesh.face_normals
    epsilon = 1e-3 * float(np.ptp(mesh.vertices, axis=0).max())
    reach = float(np.ptp(mesh.vertices, axis=0).max()) * 0.08
    open_count = np.zeros(len(mesh.faces))
    directions = render_module.fibonacci_directions(samples)
    for direction in directions:
        facing = normals @ direction
        live = facing > 0.05
        if not live.any():
            continue
        origins = centres[live] + normals[live] * epsilon
        hit, _index, locations = _hit_within(mesh, origins, direction, reach)
        open_count[live] += (~hit) * facing[live]
    weight = np.maximum((normals @ directions.T).clip(0, None).sum(axis=1), 1e-9)
    return np.clip(open_count / weight, 0.0, 1.0)


def _hit_within(mesh, origins, direction, reach):
    tiled = np.tile(direction, (len(origins), 1))
    locations, ray_ids, _face = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=tiled, multiple_hits=False)
    hit = np.zeros(len(origins), dtype=bool)
    if len(ray_ids):
        travel = np.linalg.norm(locations - origins[ray_ids], axis=1)
        close = travel < reach
        hit[ray_ids[close]] = True
    return hit, ray_ids, locations


def render_asset(mesh, face_rgb, direction, size=640, occlusion=None, up=(0, 0, 1),
                 background=(0.97, 0.965, 0.955), centre=None, zoom=1.0):
    """One presentation view: key, fill, sky, and ambient occlusion over flat colour.

    `centre` and `zoom` frame a detail. A zoom is a real camera move rather than a crop
    of a finished image: the rays are recast at full resolution, so a close view resolves
    detail the wide view never sampled, which is the whole point of looking closer.
    """
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    if centre is None:
        centre = mesh.vertices.mean(axis=0)
    centre = np.asarray(centre, dtype=float)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.08 / max(zoom, 1e-6)
    camera = render_module.Camera(direction, up, centre, radius, size)
    origins, rays = camera.rays()
    hit = mesh.ray.intersects_first(ray_origins=origins,
                                    ray_directions=rays).reshape(size, size)
    visible = hit >= 0
    image = np.tile(np.asarray(background, dtype=float), (size, size, 1))
    if not visible.any():
        return (image * 255).astype(np.uint8)

    normals = mesh.face_normals[hit[visible]]
    facing = np.einsum("ij,j->i", normals, camera.forward)
    normals = np.where((facing > 0)[:, None], -normals, normals)

    key = camera.up * 0.55 + camera.right * 0.35 - camera.forward * 0.75
    key /= np.linalg.norm(key)
    fill = -camera.right * 0.7 + camera.up * 0.1 - camera.forward * 0.45
    fill /= np.linalg.norm(fill)
    sky = np.asarray(up, dtype=float)
    sky = sky / np.linalg.norm(sky)

    diffuse = (0.78 * np.clip(normals @ key, 0.0, 1.0)
               + 0.22 * np.clip(normals @ fill, 0.0, 1.0))
    # A dome term, so upward faces pick up light from above like a print on a desk.
    dome = 0.30 * (0.5 + 0.5 * (normals @ sky))
    shade = diffuse + dome
    if occlusion is not None:
        shade = shade * (0.35 + 0.65 * occlusion[hit[visible]])

    colour = face_rgb[hit[visible]] * shade[:, None]
    # A narrow specular so the surface reads as plastic rather than chalk.
    half = key - camera.forward
    half /= np.linalg.norm(half)
    gloss = np.clip(normals @ half, 0.0, 1.0) ** 32
    colour = colour + gloss[:, None] * 0.12
    image[visible] = np.clip(colour, 0.0, 1.0)
    return (np.clip(image, 0.0, 1.0) * 255).astype(np.uint8)


def contact_sheet(mesh, face_rgb, directions, size=640, occlusion=None, columns=3,
                  gap=10, background=(247, 246, 244), frames=None):
    """Several views laid out as one image.

    `frames` optionally pairs each direction with a (centre, zoom) so one sheet can mix
    wide views and details.
    """
    from PIL import Image
    if frames is None:
        frames = [(None, 1.0)] * len(directions)
    tiles = [render_asset(mesh, face_rgb, direction, size=size, occlusion=occlusion,
                          centre=frame[0], zoom=frame[1])
             for direction, frame in zip(directions, frames)]
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * size + (columns + 1) * gap,
                              rows * size + (rows + 1) * gap), background)
    for index, tile in enumerate(tiles):
        x = gap + (index % columns) * (size + gap)
        y = gap + (index // columns) * (size + gap)
        sheet.paste(Image.fromarray(tile), (x, y))
    return sheet


def turntable(count=6, elevation_deg=18.0, up=(0, 0, 1)):
    """Directions around the object at a fixed elevation, for a guide sheet."""
    return orbit(count, elevation_deg, up=up)


def orbit(count=12, elevation_deg=14.0, start_deg=0.0, up=(0, 0, 1)):
    """A full turn around the object's OWN up axis, at one elevation.

    The up axis has to be passed in because the working mesh is expressed in the
    intrinsic frame, whose axes are sorted by extent (§4.2) and therefore have nothing to
    do with which way the object stands. Orbiting around the frame's third axis put the
    rock base at the top of every render -- the piece was upside down in every view, and
    the renders were the only place that showed it.
    """
    up = np.asarray(up, dtype=float)
    up = up / max(np.linalg.norm(up), 1e-12)
    helper = np.array([1.0, 0.0, 0.0])
    if abs(float(up @ helper)) > 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    east = np.cross(up, helper)
    east /= np.linalg.norm(east)
    north = np.cross(up, east)
    elevation = np.radians(elevation_deg)
    out = []
    for index in range(count):
        angle = np.radians(start_deg) + 2.0 * np.pi * index / count
        horizontal = np.cos(angle) * east + np.sin(angle) * north
        # The camera looks DOWN from above the horizon, so the view direction carries a
        # negative component along up.
        out.append(list(horizontal * np.cos(elevation) - up * np.sin(elevation)))
    return out


def up_axis(frame):
    """The file's own +Z, expressed in the intrinsic frame the working mesh lives in.

    A print-ready mesh stands the way it will be printed, so the file's Z is the axis to
    orbit around and to light from -- not the frame's longest extent.
    """
    local = np.array([0.0, 0.0, 1.0]) @ np.asarray(frame.rotation, dtype=float).T
    return local / max(np.linalg.norm(local), 1e-12)


def region_centre(field_posterior, vertices, label_index):
    """Where a region sits, weighted by how strongly it is claimed."""
    weight = np.asarray(field_posterior)[label_index]
    total = weight.sum()
    if total <= 0:
        return vertices.mean(axis=0)
    return (vertices * weight[:, None]).sum(axis=0) / total


def facing_direction(mesh, field_posterior, label_index):
    """The direction to view a region from: its own posterior-weighted normal."""
    weight = np.asarray(field_posterior)[label_index]
    normals = mesh.vertex_normals
    pooled = (normals * weight[:, None]).sum(axis=0)
    norm = np.linalg.norm(pooled)
    if norm < 1e-9:
        return np.array([0.0, -1.0, -0.3])
    return -pooled / norm
