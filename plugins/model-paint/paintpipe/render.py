"""Appearance evidence: cameras, lighting rigs, and render bundles (spec §5).

I1 says appearance is primary and the mesh is a ray target and nothing else. This module
is the boundary where that becomes true: everything above it sees buffers, and nothing
above it is permitted to ask the mesh a question.

`hit_id` is a ROUTING KEY, never evidence. It exists so that a belief formed by looking
at a picture can be written back to the surface point it is about. The moment a cue
reads it as a quantity -- face index as a feature, triangle density as a signal -- I1 is
broken and the pipeline has started describing the tessellation instead of the object.

Antialiasing is disabled and this is not an oversight. AA blends hit ids at silhouettes,
which manufactures confident nonsense on exactly the boundaries that matter most: a
pixel that is 60% rim and 40% background gets written to whichever face wins a coverage
argument. One ray per pixel, and pixels near a depth cut are dropped outright (§7).
"""

import numpy as np

# Rig names are semantic (§5.2). Cues from different rigs are separate evidence
# channels and are never averaged: a cue is a LIGHTING RESPONSE, so the rig is part of
# the measurement, and averaging two rigs measures nothing that exists.
RIGS = {
    # Key from intrinsic up. Reproduces how the object will actually be primed and
    # read, and is the reference rig for shade and highlight reasoning.
    "zenithal": {"key": ("up", 1.0), "fill": ("front", 0.18), "ambient": 0.10},
    # No directional key, for material and albedo reasoning where a key light lies.
    "flat": {"key": None, "fill": None, "ambient": 1.0},
    # Grazing from two orthogonal azimuths; maximises edge and plane-break separation.
    "raking_a": {"key": ("right", 1.0), "fill": None, "ambient": 0.06, "graze": True},
    "raking_b": {"key": ("front", 1.0), "fill": None, "ambient": 0.06, "graze": True},
}


class Camera:
    """An orthographic pose with an explicit pixel footprint.

    Orthographic on purpose: it keeps a part's apparent size honest between views, so
    "this is bigger than that" survives a change of camera, and it makes the pixel
    footprint exact rather than depth-dependent.

    That last point changes how §5.3 is computed. The spec writes GSD for a perspective
    camera (depth * pitch / focal). Under an orthographic projection the footprint does
    not vary with depth at all, so the same quantity is `footprint / cos(incidence)`.
    Same invariant, correct derivation for this camera: still per-pixel, because
    incidence is per-pixel, and that is the part that carries the meaning.
    """

    def __init__(self, direction, up_hint, centre, radius_mm, pixels):
        forward = np.asarray(direction, dtype=float)
        forward /= np.linalg.norm(forward)
        up_hint = np.asarray(up_hint, dtype=float)
        if abs(float(forward @ up_hint)) > 0.999:
            up_hint = np.array([0.0, 1.0, 0.0]) if abs(forward[1]) < 0.9 \
                else np.array([1.0, 0.0, 0.0])
        right = np.cross(forward, up_hint)
        right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        self.forward, self.right, self.up = forward, right, up / np.linalg.norm(up)
        self.centre = np.asarray(centre, dtype=float)
        self.radius_mm = float(radius_mm)
        self.pixels = int(pixels)

    @property
    def footprint_mm(self):
        """Millimetres of surface per pixel, before incidence. The GSD numerator."""
        return 2.0 * self.radius_mm / self.pixels

    def rays(self):
        span = np.linspace(-self.radius_mm, self.radius_mm, self.pixels)
        grid_x, grid_y = np.meshgrid(span, -span)
        origins = (self.centre - self.forward * (self.radius_mm * 4.0)
                   + self.right * grid_x.reshape(-1, 1)
                   + self.up * grid_y.reshape(-1, 1))
        return origins, np.tile(self.forward, (origins.shape[0], 1))

    def params(self):
        return {"forward": self.forward.round(9).tolist(),
                "up": self.up.round(9).tolist(),
                "centre": self.centre.round(6).tolist(),
                "radius_mm": round(self.radius_mm, 6), "pixels": self.pixels}


def rig_directions(camera, rig_name, frame=None):
    """Turn a rig's semantic light names into world directions.

    `up` means the OBJECT's up when a frame is available (§4.2), not the camera's --
    zenithal light is defined by how the model stands on the table, and a camera that
    orbits underneath must not carry the key light around with it.
    """
    rig = RIGS[rig_name]
    basis = {"right": camera.right, "up": camera.up, "front": -camera.forward}
    if frame is not None and frame.axis_names:
        for name, axis in frame.axis_names.items():
            if name in ("up", "front", "right") and axis is not None:
                basis[name] = frame.direction_to_world(axis)
    out = {"ambient": rig["ambient"], "lights": []}
    for slot in ("key", "fill"):
        entry = rig.get(slot)
        if entry is None:
            continue
        name, strength = entry
        direction = np.asarray(basis[name], dtype=float)
        if rig.get("graze"):
            # Grazing: push the light into the surface plane so relief throws shadow.
            direction = direction - camera.forward * float(direction @ camera.forward)
            direction = direction * 0.94 - camera.forward * 0.06
        direction = direction / max(np.linalg.norm(direction), 1e-12)
        out["lights"].append((direction, float(strength)))
    return out


def render_bundle(mesh, camera, rig_name, frame=None, cavity_taps=12):
    """One camera x one rig -> the buffer set of §5.1.

    Returns depth as distance along the view axis from the camera plane, normals in
    world space, hit ids and barycentric coordinates for routing, the lit image the
    VLM will read, and a screen-space cavity map.
    """
    origins, directions = camera.rays()
    locations, ray_ids, face_ids = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=directions, multiple_hits=False)

    n = camera.pixels
    total = n * n
    hit_id = np.full(total, -1, dtype=np.int64)
    depth = np.full(total, np.nan)
    point = np.full((total, 3), np.nan)
    if len(ray_ids):
        hit_id[ray_ids] = face_ids
        point[ray_ids] = locations
        depth[ray_ids] = np.einsum("ij,j->i", locations - camera.centre, camera.forward)

    hit_id = hit_id.reshape(n, n)
    depth = depth.reshape(n, n)
    point = point.reshape(n, n, 3)
    visible = hit_id >= 0

    normal = np.zeros((n, n, 3))
    if visible.any():
        normal[visible] = mesh.face_normals[hit_id[visible]]
        # Face normals can point away from the camera on a mesh whose winding is not
        # consistent. The camera cannot see a back face, so orient toward the viewer;
        # this is a fact about visibility, not an edit to the mesh.
        facing = np.einsum("ij,j->i", normal[visible], camera.forward)
        normal[visible] = np.where((facing > 0)[:, None], -normal[visible],
                                   normal[visible])

    barycentric = np.full((n, n, 3), np.nan)
    if visible.any():
        import trimesh as _tm
        tris = mesh.triangles[hit_id[visible]]
        barycentric[visible] = _tm.triangles.points_to_barycentric(
            tris, point[visible], method="cross")

    incidence = np.full((n, n), np.nan)
    if visible.any():
        incidence[visible] = np.clip(
            -np.einsum("ij,j->i", normal[visible], camera.forward), 0.0, 1.0)

    lighting = rig_directions(camera, rig_name, frame)
    lit = np.zeros((n, n))
    if visible.any():
        value = np.full(int(visible.sum()), lighting["ambient"])
        for direction, strength in lighting["lights"]:
            value = value + strength * np.clip(
                np.einsum("ij,j->i", normal[visible], -direction), 0.0, 1.0)
        lit[visible] = value

    cavity = screen_cavity(depth, visible, camera, taps=cavity_taps)

    return {"hit_id": hit_id, "depth": depth, "normal": normal, "point": point,
            "barycentric": barycentric, "visible": visible, "incidence": incidence,
            "rgb_lit": lit, "cavity": cavity, "camera": camera, "rig": rig_name}


def screen_cavity(depth, visible, camera, taps=12, radius_px=None):
    """Screen-space ambient occlusion from the depth buffer -- the painter's shade map.

    Computed from DEPTH rather than from mesh curvature, which is the whole point: a
    crevice reads as a crevice because it is closer to its surroundings in the image,
    and that is true whether the surface is ten triangles or ten thousand.
    """
    n = depth.shape[0]
    if radius_px is None:
        radius_px = max(2, n // 64)
    filled = np.where(visible, depth, np.nan)
    occlusion = np.zeros((n, n))
    counted = np.zeros((n, n))
    rng = np.random.default_rng(11)
    angles = rng.uniform(0, 2 * np.pi, taps)
    steps = radius_px * np.sqrt(rng.uniform(0.15, 1.0, taps))
    for angle, step in zip(angles, steps):
        dy, dx = int(round(np.sin(angle) * step)), int(round(np.cos(angle) * step))
        if dx == 0 and dy == 0:
            continue
        shifted = np.roll(np.roll(filled, dy, axis=0), dx, axis=1)
        both = visible & np.isfinite(shifted)
        # A neighbour nearer to the camera than this pixel occludes it.
        nearer = np.zeros((n, n))
        nearer[both] = np.clip(filled[both] - shifted[both], 0.0, None)
        occlusion += nearer
        counted += both
    scale = camera.footprint_mm * max(radius_px, 1)
    out = np.zeros((n, n))
    live = counted > 0
    out[live] = np.clip(occlusion[live] / counted[live] / max(scale, 1e-9), 0.0, 1.0)
    return np.where(visible, out, np.nan)


def fibonacci_directions(count):
    """Evenly spread view directions on the sphere; the base round of §4.5."""
    index = np.arange(count) + 0.5
    phi = np.arccos(1.0 - 2.0 * index / count)
    theta = np.pi * (1.0 + 5.0 ** 0.5) * index
    return np.stack([np.cos(theta) * np.sin(phi),
                     np.sin(theta) * np.sin(phi),
                     np.cos(phi)], axis=1)
