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


def adjacency(field, labels, radius_mm):
    """Which regions actually touch, read off the field rather than assumed.

    Two regions are adjacent when a mesh edge has one at each end under the current
    posterior. That is a question about beliefs and not about geometry, which is why it
    belongs here and not in the mesh: regions are level sets of a continuous field, so
    "touching" means their territories meet, not that some triangle is shared.
    """
    posterior = field.posterior(radius_mm)
    if posterior.shape[0] == 0:
        return set()
    index = {label: i for i, label in enumerate(field.labels)}
    rows = [index[label] for label in labels if label in index]
    if not rows:
        return set()
    owner = np.argmax(posterior[rows], axis=0)
    claimed = posterior[rows].max(axis=0) > 0
    edges = field.substrate.edges_unique
    a, b = owner[edges[:, 0]], owner[edges[:, 1]]
    both = claimed[edges[:, 0]] & claimed[edges[:, 1]]
    touching = set()
    for left, right in np.unique(np.stack([np.minimum(a, b), np.maximum(a, b)],
                                          axis=1)[both & (a != b)], axis=0):
        touching.add((labels[int(left)], labels[int(right)]))
    return touching


def assign_paints(scheme, palette, touching, policy, distance_mm=None, areas=None):
    """Choose one paint per region: minimise colour error, keep neighbours separable.

    §11 says the palette fit is a CONSTRAINT, not a lookup, and the difference decides
    whether the print reads at all. Fitting each region to its own nearest paint
    independently put all six of the shell's regions onto two filaments -- ribs, rim and
    barnacles all white; rock, cracks and weed all grey -- with orange and black unused
    and every boundary between them gone. Each choice was individually optimal and the
    result was a blank object.

    Solved exactly over the whole assignment rather than region by region, so a region
    accepts a worse colour match when that is what keeps its neighbour distinguishable.
    The search is |palette| ** |regions|, which is small by construction: a scheme with
    more regions than a few dozen has already failed the critic.
    """
    import itertools
    labels = [entry["region"] for entry in scheme]
    wanted = [tuple(entry["lab"]) for entry in scheme]
    cost = np.array([[delta_e(want, paint.lab) for paint in palette] for want in wanted])

    # COLOUR ERROR IS PERCEIVED BY AREA. Summing dE with every region counted equally
    # makes a dragon's eye socket as expensive to get wrong as its whole body, so the
    # optimiser spends its good colours on the large masses and hands the eye whatever is
    # left -- measured, the eye came out grey at dE 32.6 and vanished entirely. Weighting
    # by area states what is actually true: being wrong across a third of the model
    # matters and being wrong across a tenth of a percent of it does not, which leaves
    # small features nearly free to take whatever colour makes them READ.
    if areas is None:
        weight = np.array([float(entry.get("area_mm2", 1.0)) for entry in scheme])
    else:
        weight = np.array([float(areas.get(entry["region"], 1.0)) for entry in scheme])
    weight = weight / max(weight.sum(), 1e-9)
    weight = np.maximum(weight, 0.02)      # a floor, so nothing is wholly ignored
    cost = cost * weight[:, None]
    neighbours = [(labels.index(a), labels.index(b)) for a, b in touching
                  if a in labels and b in labels]

    # A collapsed boundary costs more than any colour error can, so separability wins
    # every trade -- but among assignments that keep neighbours apart, colour decides.
    penalty = float(cost.max()) * len(labels) + 1.0
    # An accent's whole job is to be seen, so losing ITS boundary costs more than losing
    # an ordinary one and ties break in its favour.
    accent = np.array([2.5 if entry.get("role") == "accent" else 1.0
                       for entry in scheme])
    best, best_score = None, np.inf
    if len(labels) > 12:
        order = np.argsort(cost.min(axis=1))
        return {labels[i]: palette[int(np.argmin(cost[i]))] for i in order}, None
    for combination in itertools.product(range(len(palette)), repeat=len(labels)):
        score = float(sum(cost[i, combination[i]] for i in range(len(labels))))
        score += penalty * sum(max(accent[a], accent[b]) for a, b in neighbours
                               if combination[a] == combination[b])
        if score < best_score:
            best, best_score = combination, score
    clashes = [(labels[a], labels[b]) for a, b in neighbours if best[a] == best[b]]
    return ({labels[i]: palette[best[i]] for i in range(len(labels))}, clashes)


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

    touching = adjacency(field, [e["region"] for e in scheme], radius_mm)
    chosen, clashes = assign_paints(scheme, profile.palette, touching, policy,
                                    profile.viewing.distance_mm)
    for entry in scheme:
        paint = chosen[entry["region"]]
        entry["paint"] = paint
        entry["paint_de"] = delta_e(entry["lab"], paint.lab)
        entry["realizable"] = True
    if store is not None and clashes:
        for left, right in clashes:
            store.reject("scheme_entry",
                         "%s and %s touch and could not be given different paints; "
                         "the palette is too small to separate every region"
                         % (left, right), inputs=inputs, count=1)

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


def consolidate(field, owner, claimed, tip_radius_mm, policy, rounds=None):
    """Commit to one label per vertex at a scale the nozzle can actually lay down (§11).

    The label field is continuous, and taking an argmax at each vertex INDEPENDENTLY
    throws that away: where two labels are close in posterior the winner flips from
    vertex to vertex, and the result is salt-and-pepper. On the dragon, twelve labels
    over a sparse field turned a clean mixture render into noise the moment it was
    committed.

    A speckle is not a printing defect to be tidied up afterwards, it is a region below
    the minimum feature size, which §11 already says must merge into its parent. So the
    commitment happens at the brush's own scale: each vertex takes the label holding the
    most AREA within one tip radius of it. Nothing smaller than the nozzle survives,
    because nothing smaller than the nozzle can be printed.
    """
    mesh = field.substrate
    if field._neighbours is None:
        field._build_neighbours()
    indptr, indices = field._neighbours
    if rounds is None:
        rounds = int(np.clip(round(policy.merge_ratio * tip_radius_mm
                                   / max(field._mean_edge, 1e-9)), 1, 24))
    count = int(owner.max()) + 1 if len(owner) else 0
    if count == 0:
        return owner
    area = field.vertex_area
    # One-hot, area weighted, diffused over the surface, then re-committed.
    mass = np.zeros((count, len(mesh.vertices)))
    live = claimed
    mass[owner[live], np.flatnonzero(live)] = area[live]
    degree = np.maximum(np.diff(indptr), 1)
    for _ in range(rounds):
        pooled = np.add.reduceat(mass[:, indices], indptr[:-1], axis=1)
        mass = 0.4 * mass + 0.6 * (pooled / degree)
    out = owner.copy()
    total = mass.sum(axis=0)
    settled = total > 0
    out[settled] = np.argmax(mass[:, settled], axis=0)
    return out


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
