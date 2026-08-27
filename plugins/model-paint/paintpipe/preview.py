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
                 background=(0.97, 0.965, 0.955)):
    """One presentation view: key, fill, sky, and ambient occlusion over flat colour."""
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.08
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
                  gap=10, background=(247, 246, 244)):
    """Several views laid out as one image."""
    from PIL import Image
    tiles = [render_asset(mesh, face_rgb, direction, size=size, occlusion=occlusion)
             for direction in directions]
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * size + (columns + 1) * gap,
                              rows * size + (rows + 1) * gap), background)
    for index, tile in enumerate(tiles):
        x = gap + (index % columns) * (size + gap)
        y = gap + (index // columns) * (size + gap)
        sheet.paste(Image.fromarray(tile), (x, y))
    return sheet


def turntable(count=6, elevation_deg=18.0):
    """Directions around the object at a fixed elevation, for a guide sheet."""
    elevation = np.radians(elevation_deg)
    out = []
    for index in range(count):
        angle = 2.0 * np.pi * index / count
        out.append([np.cos(angle) * np.cos(elevation),
                    np.sin(angle) * np.cos(elevation),
                    -np.sin(elevation)])
    return out
