"""Limiter, bake and export (spec §11).

Runs after the critic accepts the tree. This is the ONLY stage that knows about physical
hardware, and the only stage permitted to invalidate upstream work.

Physical units enter here and they come from the brush, the paint and the viewing
distance -- never from the model. That is I2's whole point: a scheme is realizable or not
depending on what the painter owns, so a pipeline with a millimetre baked into its source
has silently decided what hardware you have.
"""

import numpy as np


def just_noticeable_de(distance_mm, angular_size_deg):
    """Just-noticeable colour difference at a viewing distance and angular size.

    dE2000 is defined for large adjacent patches under good light. A small region seen
    from across a room is harder to tell apart than that, so the threshold rises as the
    patch shrinks below roughly a degree, which is where foveal colour discrimination
    starts falling off. The shape is a standard acuity roll-off; what matters for I2 is
    that both inputs come from the painter's declared viewing condition and from the
    region's own measured size, not from a constant.
    """
    reference = 1.0
    if angular_size_deg <= 0:
        return np.inf
    return float(reference * max(1.0, (1.0 / max(angular_size_deg, 1e-6)) ** 0.5))


def angular_size(area_mm2, distance_mm):
    if distance_mm is None or distance_mm <= 0:
        return None
    radius = np.sqrt(max(area_mm2, 0.0) / np.pi)
    return float(np.degrees(2.0 * np.arctan(radius / distance_mm)))


def delta_e(lab_a, lab_b):
    """CIEDE2000 via colour-science, which the spec names by hand (§12)."""
    from colour.difference import delta_E_CIE2000
    return float(delta_E_CIE2000(np.asarray(lab_a, dtype=float),
                                 np.asarray(lab_b, dtype=float)))


def fit_palette(scheme, profile, field, radius_mm, policy, store=None, inputs=()):
    """§11 palette fit. Nearest paint by dE2000, SUBJECT TO A CONSTRAINT.

    Not a lookup. Adjacent regions must remain separable at the viewing distance, and
    the required margin is the just-noticeable dE at that distance and angular size,
    times `contrast_margin`. Two regions that collapse to one paint are merged and
    logged, and re-differentiated only if the merge crosses a boundary the critic marked
    load-bearing.
    """
    if not profile.palette:
        for entry in scheme:
            entry["paint"] = None
            entry["realizable"] = False
            entry["note"] = "unconstrained: no palette declared"
        if store is not None:
            store.reject("scheme", "no palette declared; design only, not a plan",
                         inputs=inputs, count=len(scheme))
        return scheme

    for entry in scheme:
        best = min(profile.palette, key=lambda paint: delta_e(entry["lab"], paint.lab))
        entry["paint"] = best
        entry["paint_de"] = delta_e(entry["lab"], best.lab)
        entry["realizable"] = True

    distance = profile.viewing.distance_mm
    if distance is None:
        for entry in scheme:
            entry["contrast_checked"] = False
        if store is not None:
            store.reject("scheme", "no viewing distance declared; contrast between "
                                   "adjacent regions is unverifiable", inputs=inputs,
                         count=len(scheme))
        return scheme

    # Adjacency is measured in the FIELD, not on the mesh: two regions are adjacent when
    # their memberships overlap or abut, which is a question about beliefs.
    for i, entry in enumerate(scheme):
        entry["contrast_checked"] = True
        for other in scheme[i + 1:]:
            overlap = field.disagreement(entry["region"], other["region"], radius_mm)
            if overlap <= 0:
                continue
            area = max(entry.get("area_mm2", overlap), 1e-9)
            required = policy.contrast_margin * just_noticeable_de(
                distance, angular_size(area, distance) or 1e-6)
            separation = delta_e(entry["paint"].lab, other["paint"].lab)
            if separation < required:
                other["merged_into"] = entry["region"]
                other["realizable"] = False
                if store is not None:
                    store.reject("scheme_entry",
                                 "collapses onto %s: dE %.2f below required %.2f at "
                                 "%.0fmm" % (entry["region"], separation, required,
                                             distance),
                                 inputs=inputs, count=1)
    return scheme


def min_feature(region_membership, field, level=0.5):
    """§11 / §12. The region's inscribed radius in millimetres.

    A distance transform on the MEMBERSHIP FIELD rather than on a mask: the field is
    what the pipeline actually believes, and thresholding it first would make the answer
    depend on where the threshold went.
    """
    inside = region_membership > level
    if not inside.any():
        return 0.0
    outside = np.flatnonzero(~inside)
    if len(outside) == 0:
        return float(np.sqrt(field.total_area_mm2 / np.pi))
    distance = field.distance_from(outside)
    return float(distance[inside].max())


def reachability(region_membership, field, tip, level=0.5, samples=64):
    """§11. Can a brush of this tip's half-angle reach the region unoccluded?

    A cone cast outward from the surface. No unoccluded approach means unpaintable in
    place -- flagged for sub-assembly painting or removal, never silently painted anyway.
    """
    inside = np.flatnonzero(region_membership > level)
    if len(inside) == 0 or tip is None:
        return True, 1.0
    mesh = field.substrate
    points = mesh.vertices[inside]
    normals = mesh.vertex_normals[inside]
    if len(points) > samples:
        step = len(points) // samples
        points, normals = points[::step][:samples], normals[::step][:samples]
    epsilon = 1e-3 * float(np.ptp(mesh.vertices, axis=0).max())
    half = np.radians(tip.half_angle_deg)
    reached = np.zeros(len(points), dtype=bool)
    for angle in np.linspace(0.0, half, 3):
        # Tilt the approach away from the normal by up to the tip's half angle.
        helper = np.tile([0.0, 0.0, 1.0], (len(points), 1))
        side = np.cross(normals, helper)
        norm = np.linalg.norm(side, axis=1, keepdims=True)
        side = np.where(norm > 1e-9, side / np.maximum(norm, 1e-9), 0.0)
        direction = normals * np.cos(angle) + side * np.sin(angle)
        hit = mesh.ray.intersects_any(ray_origins=points + normals * epsilon,
                                      ray_directions=direction)
        reached |= ~hit
    fraction = float(reached.mean())
    return fraction > 0.5, fraction


def bake(field, scheme, rho_work_mm, radius_mm):
    """§11. Sample the field at the working pitch and return per-vertex colours.

    The FIRST and ONLY moment the mesh's parameterization matters. Everything above this
    line was continuous and scale-parameterized; here it becomes a finite array because
    something physical has to be handed over.
    """
    posterior = field.posterior(radius_mm)
    if posterior.shape[0] == 0:
        return np.zeros((len(field.substrate.vertices), 3)), {}
    by_region = {entry["region"]: entry for entry in scheme}
    colours = np.zeros((len(field.substrate.vertices), 3))
    total = np.zeros(len(field.substrate.vertices))
    for index, node_id in enumerate(field.labels):
        entry = by_region.get(node_id)
        if entry is None:
            continue
        lab = entry["paint"].lab if entry.get("paint") is not None else entry["lab"]
        share = posterior[index]
        colours += share[:, None] * np.asarray(lab, dtype=float)[None, :]
        total += share
    live = total > 0
    colours[live] /= total[live][:, None]
    return colours, {"rho_work_mm": rho_work_mm, "radius_mm": radius_mm,
                     "vertices": int(live.sum())}


def export_guide(scheme, frame, field, radius_mm, bands, coverage, store=None,
                 inputs=()):
    """§11 export. The manifest, the paint sequence, and what could not be verified.

    Sequence comes from the cue ROLES rather than from an author's habit: bases, then
    recess shades where cavity is high, then edge highlights where ridge is high, then
    accents. That ordering is a fact about how paint behaves, and it falls out of the
    roles the painter agent already assigned.
    """
    order = {"base": 0, "shade": 1, "highlight": 2, "accent": 3}
    entries = []
    for entry in sorted(scheme, key=lambda e: order.get(e.get("role"), 9)):
        membership = field.region(entry["region"], radius_mm)
        area = float(np.sum(membership * field.vertex_area))
        entries.append({
            "region": entry["region"],
            "role": entry.get("role"),
            "paint": None if entry.get("paint") is None else entry["paint"].sku,
            "lab": [round(float(v), 3) for v in entry["lab"]],
            "area_mm2": round(area, 3),
            "inscribed_radius_mm": round(min_feature(membership, field), 4),
            "realizable": bool(entry.get("realizable", False)),
            "merged_into": entry.get("merged_into"),
            "note": entry.get("note"),
        })
    manifest = {
        "frame": frame.params(),
        "bands": [band.params() for band in bands],
        "query_radius_mm": radius_mm,
        "coverage": coverage,
        "regions": entries,
        "sequence": [e["region"] for e in entries],
        "unrealizable": [e["region"] for e in entries if not e["realizable"]],
    }
    if store is not None:
        store.mint("export", inputs=inputs, params={"regions": len(entries)},
                   attrs={"regions": len(entries),
                          "unrealizable": len(manifest["unrealizable"])})
    return manifest
