"""Ray-traced views that also return which triangle is under every pixel.

The reason this exists rather than a plotting library: an agent that looks at a
render and says "the barnacle cluster on the upper right rib" needs a way to turn
that observation into triangle indices. A picture alone is a dead end. A picture
plus a pick map -- face index per pixel -- closes the loop, so seeing something
becomes selecting it.

Casting one ray per pixel gives both at once, and with a ray engine available it
is faster than rasterising through a plotting stack besides. The camera is
orthographic, which keeps a part's apparent size honest across views and makes
pixel-to-face mapping exact.
"""

import numpy as np

# Elevation and azimuth in degrees, matching the names used in the CLIs.
VIEWS = {
    "front": (14.0, -88.0), "back": (14.0, 92.0),
    "left": (12.0, -2.0), "right": (12.0, 178.0),
    "top": (78.0, -90.0), "bottom": (-70.0, -90.0),
    "iso": (24.0, -50.0), "iso2": (20.0, 130.0),
}


def _camera(elevation, azimuth):
    """Unit vectors (forward, right, up) for a view, matching plot conventions."""
    elevation, azimuth = np.radians(elevation), np.radians(azimuth)
    eye = np.array([
        np.cos(elevation) * np.cos(azimuth),
        np.cos(elevation) * np.sin(azimuth),
        np.sin(elevation),
    ])
    forward = -eye
    world_up = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(forward, world_up)) > 0.999:
        world_up = np.array([0.0, 1.0, 0.0])
    right = np.cross(forward, world_up)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return forward, right, up / np.linalg.norm(up)


def render_view(mesh, colours, elevation, azimuth, size=800, centre=None,
                radius=None, background=(1.0, 1.0, 1.0)):
    """Return ``(image uint8 HxWx3, picks int32 HxW)``; picks is -1 where empty."""
    forward, right, up = _camera(elevation, azimuth)

    if centre is None:
        centre = mesh.vertices.mean(axis=0)
    if radius is None:
        radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.05
    centre = np.asarray(centre, dtype=float)

    span = np.linspace(-radius, radius, size)
    grid_x, grid_y = np.meshgrid(span, -span)
    origins = (centre
               - forward * (radius * 4.0)
               + right * grid_x.reshape(-1, 1)
               + up * grid_y.reshape(-1, 1))
    directions = np.tile(forward, (origins.shape[0], 1))

    hit = mesh.ray.intersects_first(ray_origins=origins, ray_directions=directions)
    picks = hit.reshape(size, size).astype(np.int32)

    image = np.tile(np.asarray(background, dtype=float), (size, size, 1))
    visible = picks >= 0
    if visible.any():
        faces = picks[visible]
        normals = mesh.face_normals[faces]
        # Two lights: a key from over the viewer's shoulder and a weak fill, so
        # concave detail stays legible instead of going flat black.
        key = right * 0.4 + up * 0.5 - forward * 0.75
        key /= np.linalg.norm(key)
        fill = -right * 0.6 + up * 0.2 - forward * 0.5
        fill /= np.linalg.norm(fill)
        lit = (0.72 * np.clip(normals @ key, 0.0, 1.0)
               + 0.20 * np.clip(normals @ fill, 0.0, 1.0) + 0.26)
        image[visible] = np.clip(colours[faces] * lit[:, None], 0.0, 1.0)

    return (image * 255.0).astype(np.uint8), picks


def region_at(mesh, picks, x, y, radius=6):
    """Triangles under a pixel, tolerant of the agent's aim being a few px off."""
    height, width = picks.shape
    x, y = int(x), int(y)
    window = picks[max(0, y - radius):min(height, y + radius + 1),
                   max(0, x - radius):min(width, x + radius + 1)]
    found = window[window >= 0]
    if not found.size:
        return None
    values, counts = np.unique(found, return_counts=True)
    return int(values[np.argmax(counts)])


def save_png(path, image):
    from PIL import Image

    Image.fromarray(image).save(path)
    return path
