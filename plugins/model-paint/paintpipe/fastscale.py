"""The scale-space index, multigrid: same ladder, a fraction of the work.

The original builder (scripts/scale_space.py) diffuses the normal field with
explicit neighbour averaging: reaching a radius r costs (r/edge)^2 rounds, and
the top rung of a million-face mesh costs thousands of million-row matvecs --
minutes spent smoothing a field that is, by then, almost constant.

The observation that pays: once the field is smooth at some radius, it no
longer needs the fine graph to keep smoothing. So the face graph is coarsened
into a hierarchy of quotient graphs (edge matching; each level roughly halves
the faces and doubles the radius one step reaches), the field is restricted
down the hierarchy as the ladder climbs, and each rung runs its remaining
rounds on the coarsest level whose step is still finer than the rung needs.
Fine rungs run exactly as before; coarse rungs run on graphs a 64th the size.
Dispersion and offset are read back through the aggregation map, so every
output stays per-fine-face and the API matches the original.

Nothing here touches geometry: the hierarchy is bookkeeping over the face
GRAPH, and the mesh the pipeline paints is the mesh it was given.
"""

import numpy as np


def _operator(pairs, count):
    from scipy import sparse
    left, right = pairs[:, 0], pairs[:, 1]
    rows = np.concatenate([left, right, np.arange(count)])
    cols = np.concatenate([right, left, np.arange(count)])
    data = np.ones(len(rows))
    adjacency = sparse.csr_matrix((data, (rows, cols)), shape=(count, count))
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    inverse = sparse.diags(1.0 / np.maximum(degree, 1.0))
    return (inverse @ adjacency).tocsr()


def _match(pairs, count, seed):
    """One level of aggregation by randomised edge matching."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(pairs))
    owner = np.full(count, -1, dtype=np.int64)
    next_id = 0
    for edge_id in order:
        a, b = pairs[edge_id]
        if owner[a] < 0 and owner[b] < 0:
            owner[a] = next_id
            owner[b] = next_id
            next_id += 1
    lonely = np.flatnonzero(owner < 0)
    owner[lonely] = next_id + np.arange(len(lonely))
    return owner, next_id + len(lonely)


def _quotient_pairs(pairs, owner):
    a = owner[pairs[:, 0]]
    b = owner[pairs[:, 1]]
    cross = a != b
    key = np.stack([np.minimum(a[cross], b[cross]),
                    np.maximum(a[cross], b[cross])], axis=1)
    return np.unique(key, axis=0)


def build(session, radii_mm=None, scales=14, log=None):
    vertices, faces = session["vertices"], session["faces"]
    normals = session["normals"].astype(np.float64)
    triangles = vertices[faces]
    edge = float(np.mean(np.linalg.norm(triangles[:, 1] - triangles[:, 0],
                                        axis=1)))
    count = len(faces)

    diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0)))
    if radii_mm is None:
        radii_mm = np.geomspace(edge * 1.5, diagonal * 0.2, scales)
    rounds = np.maximum(1, np.round((np.asarray(radii_mm) / edge) ** 2)
                        .astype(int))

    # Hierarchy: level 0 is the real face graph; step_owner[l] maps level-l
    # ids to level-(l+1) ids; composite[l] maps FINE faces to level-l ids.
    level_pairs = [np.asarray(session["pairs"], dtype=np.int64)]
    level_count = [count]
    level_area = [session["areas"].astype(np.float64)]
    step_owner = []
    composite = [np.arange(count, dtype=np.int64)]
    while len(level_pairs) < 7 and level_count[-1] > 20000 \
            and len(level_pairs[-1]) > 0:
        owner, coarse = _match(level_pairs[-1], level_count[-1],
                               seed=11 + len(level_pairs))
        step_owner.append(owner)
        level_pairs.append(_quotient_pairs(level_pairs[-1], owner))
        level_area.append(np.bincount(owner, weights=level_area[-1],
                                      minlength=coarse))
        level_count.append(coarse)
        composite.append(owner[composite[-1]])

    operators = {}

    def operator_at(level):
        if level not in operators:
            operators[level] = _operator(level_pairs[level],
                                         level_count[level])
        return operators[level]

    dispersion = np.zeros((len(rounds), count), dtype=np.float32)
    offset = np.zeros((len(rounds), count), dtype=np.float32)
    centres = triangles.mean(axis=1)

    current = 0
    field = normals.copy()
    smoothed = centres.copy()
    weights = level_area[0].copy()
    done_fine = 0
    for index, target in enumerate(rounds):
        pending = max(0, target - done_fine)
        wanted = current
        while (wanted + 1 < len(level_count)
               and pending >> (wanted + 1) >= 32):
            wanted += 1
        while current < wanted:
            owner = step_owner[current]
            coarse = level_count[current + 1]
            mass = np.bincount(owner, weights=weights, minlength=coarse)
            field_next = np.zeros((coarse, 3))
            smoothed_next = np.zeros((coarse, 3))
            np.add.at(field_next, owner, field * weights[:, None])
            np.add.at(smoothed_next, owner, smoothed * weights[:, None])
            field = field_next / np.maximum(mass, 1e-12)[:, None]
            smoothed = smoothed_next / np.maximum(mass, 1e-12)[:, None]
            weights = mass
            current += 1
        step = 1 << current
        applications = (pending + step - 1) // step
        op = operator_at(current)
        for _ in range(applications):
            field = op @ field
            smoothed = op @ smoothed
        done_fine += applications * step

        fine_field = field[composite[current]]
        fine_smoothed = smoothed[composite[current]]
        dispersion[index] = 1.0 - np.linalg.norm(fine_field, axis=1)
        offset[index] = np.einsum("ij,ij->i", centres - fine_smoothed,
                                  normals)
        if log:
            log("  radius %6.2fmm (%5d rounds, level %d, %d steps)"
                % (radii_mm[index], target, current, applications))

    log_r = np.log(np.asarray(radii_mm))
    response = np.gradient(dispersion, log_r, axis=0)
    peak = np.argmax(response, axis=0)
    characteristic = np.asarray(radii_mm)[peak]
    rows = np.arange(count)
    coarser = np.minimum(peak + 2, len(radii_mm) - 1)
    local = offset[peak, rows] - offset[coarser, rows]
    signed = local / np.maximum(characteristic, 1e-6)
    return {"radii_mm": np.asarray(radii_mm, dtype=np.float32),
            "dispersion": dispersion, "response": response.astype(np.float32),
            "characteristic_mm": characteristic.astype(np.float32),
            "signed": signed.astype(np.float32),
            "offset": offset.astype(np.float32),
            "mean_edge_mm": np.float32(edge)}
