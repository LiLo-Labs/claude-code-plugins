"""Extra segmentation signals for models that creases alone cannot split.

Dihedral cutting assumes features meet the surface at an angle. That holds for a
creature with eyes set into sockets and plates that overlap, and it fails
completely on a continuously sculpted object. Measured: on a scallop shell
barricade (626,766 triangles, one connected body) crease cutting put 625,884 of
them in a single region and returned 59 slivers of 13 to 30 faces. Nothing about
that output is usable.

Two measurements do separate such a model, and neither depends on there being an
edge to cut on:

**Local thickness.** Distance through the solid, from each face inward. Horns,
spikes, tube worms and encrusting growth are thin; skulls, bodies and shells are
thick. On the shell this alone separates the rocky base and the coral tubes from
the shell body.

**Surface roughness.** Mean dihedral angle to neighbouring faces, diffused over a
few rings so that a bumpy *region* scores high rather than a single edge. This is
what finds barnacle crust against a smooth shell. The diffusion count matters: too
much and everything averages to the same value, which is how the first attempt at
this washed out completely.

Both are cheap -- about two seconds together on 626k faces -- and both produce a
per-face scalar. Segmentation uses them by cutting the face graph wherever two
neighbours fall on opposite sides of a threshold, which is the same mechanism as a
crease cut and composes with it.

Thresholds are percentiles, not absolute values, because a value that means "thin"
on a 55 mm terrain piece means nothing on a 200 mm dragon. Percentiles are still
only a starting guess: the caller is expected to look at the result and adjust,
which is what `--probe` and the reasoning layer are for.
"""

import numpy as np


def surface_roughness(pairs, angles, count, rounds=2, blend=0.6):
    """Per-face bumpiness: mean angle to neighbours, diffused over `rounds` rings."""
    if not len(pairs):
        return np.zeros(count)

    magnitude = np.abs(angles)
    total = np.zeros(count)
    seen = np.zeros(count)
    np.add.at(total, pairs[:, 0], magnitude)
    np.add.at(total, pairs[:, 1], magnitude)
    np.add.at(seen, pairs[:, 0], 1.0)
    np.add.at(seen, pairs[:, 1], 1.0)
    rough = total / np.maximum(seen, 1.0)

    for _ in range(max(0, int(rounds))):
        spread = np.zeros(count)
        touched = np.zeros(count)
        np.add.at(spread, pairs[:, 0], rough[pairs[:, 1]])
        np.add.at(spread, pairs[:, 1], rough[pairs[:, 0]])
        np.add.at(touched, pairs[:, 0], 1.0)
        np.add.at(touched, pairs[:, 1], 1.0)
        rough = (1.0 - blend) * rough + blend * (spread / np.maximum(touched, 1.0))
    return rough


def local_thickness(vertices, triangles, normals, centroids, epsilon=1e-3):
    """Distance through the solid per face, or None when no ray engine is usable.

    The mesh handed to the ray engine is a throwaway built from the caller's own
    arrays. It is never written anywhere, and face order is preserved, so index i
    still means triangle i.
    """
    try:
        import trimesh
    except ImportError:
        return None

    try:
        probe = trimesh.Trimesh(vertices=vertices, faces=triangles, process=False)
        hit = probe.ray.intersects_first(
            ray_origins=centroids - normals * epsilon, ray_directions=-normals)
    except Exception:
        return None                     # no embree, degenerate mesh, anything

    thickness = np.full(len(triangles), np.nan)
    valid = hit >= 0
    if not valid.any():
        return None
    thickness[valid] = np.linalg.norm(
        centroids[valid] - centroids[hit[valid]], axis=1)
    return thickness


def relief(vertices, triangles, iterations=12, use_area_weight=True):
    """Height of each face above the locally smoothed surface. A high-pass filter.

    Roughness finds a field of many small bumps. Crease cutting finds anything
    ringed by a hard edge. Neither finds a single smooth dome sitting on a smooth
    surface -- a limpet on a shell, a rivet on a plate, a boss on a casting -- and
    on a sculpted model that blends its details in, that is most of them. Measured
    on the shell barricade: crease-bounded detection returned zero candidates,
    because nothing on it has a crease ring at all.

    Smoothing the surface and subtracting it does find them. Positive relief is a
    bump standing proud, negative is a dent. Scale-free in the sense that it
    responds to local deviation rather than absolute size, so the same threshold
    behaves sensibly on a 55 mm terrain piece and a 200 mm creature.

    The smoothed copy exists only in this function. Face count and order are never
    touched, so index i still means triangle i.
    """
    from scipy.sparse import coo_matrix

    vertices = np.asarray(vertices, dtype=np.float64)
    triangles = np.asarray(triangles)
    count = len(vertices)

    edges = np.vstack([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    both = np.vstack([edges, edges[:, ::-1]])
    weights = np.ones(len(both))
    graph = coo_matrix((weights, (both[:, 0], both[:, 1])), shape=(count, count)).tocsr()
    degree = np.asarray(graph.sum(axis=1)).ravel()
    degree[degree == 0] = 1.0

    smoothed = vertices.copy()
    for _ in range(max(1, int(iterations))):
        smoothed = np.asarray(graph @ smoothed) / degree[:, None]

    # Vertex normals from the original surface, area weighted so a dense patch
    # does not drag the direction around.
    face_normals = np.cross(vertices[triangles[:, 1]] - vertices[triangles[:, 0]],
                            vertices[triangles[:, 2]] - vertices[triangles[:, 0]])
    lengths = np.linalg.norm(face_normals, axis=1, keepdims=True)
    areas = lengths.ravel() / 2.0
    face_normals = face_normals / np.maximum(lengths, 1e-12)
    normals = np.zeros_like(vertices)
    weight = areas[:, None] if use_area_weight else 1.0
    for column in range(3):
        np.add.at(normals, triangles[:, column], face_normals * weight)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)

    displacement = np.einsum("ij,ij->i", vertices - smoothed, normals)
    return displacement[triangles].mean(axis=1)


def isolated_bumps(vertices, triangles, pairs, areas, relief_values=None,
                   percentile=88.0, min_faces=120, max_faces=8000, max_span=None,
                   claimed=None):
    """Compact regions standing proud of the surface: domes, studs, rivets, warts.

    Built on :func:`relief`. Returns a list of face-index arrays, largest first.
    ``claimed`` lets a caller exclude what has already been selected, which is how
    a coverage audit finds what a first pass missed rather than re-finding it.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    if relief_values is None:
        relief_values = relief(vertices, triangles)
    proud = relief_values >= np.percentile(relief_values, percentile)
    if claimed is not None:
        proud &= ~claimed
    both = proud[pairs[:, 0]] & proud[pairs[:, 1]]
    if not both.any():
        return []

    count = len(triangles)
    graph = coo_matrix((np.ones(int(both.sum())), (pairs[both, 0], pairs[both, 1])),
                       shape=(count, count))
    total, labels = connected_components(graph, directed=False)
    sizes = np.bincount(labels, weights=proud.astype(float)).astype(int)

    vertices = np.asarray(vertices)
    found = []
    for cluster in np.argsort(-sizes):
        size = sizes[cluster]
        if size < min_faces or size > max_faces:
            continue
        idx = np.where((labels == cluster) & proud)[0]
        if not len(idx):
            continue
        if max_span is not None:
            span = np.ptp(vertices[triangles[idx]].reshape(-1, 3), axis=0).max()
            if span > max_span:
                continue
        found.append(idx)
    return found


def _class_boundary(values, pairs, threshold, below=True):
    """Cut edges where the two faces sit on opposite sides of `threshold`."""
    if values is None or not len(pairs):
        return None
    finite = np.isfinite(values)
    member = np.zeros(len(values), dtype=bool)
    member[finite] = (values[finite] <= threshold) if below else (values[finite] >= threshold)
    return member[pairs[:, 0]] != member[pairs[:, 1]]


def signal_cuts(pairs, angles, count, vertices=None, triangles=None, normals=None,
                centroids=None, thin_percentile=22.0, rough_percentile=93.0,
                rough_rounds=2, use_thickness=True, use_roughness=True):
    """Cut mask over `pairs`, plus the raw signals for the caller to describe with.

    Returns ``(cuts, {"thickness": ..., "roughness": ...})``. Either signal may be
    None when it could not be computed or was switched off; a missing signal
    contributes no cuts rather than failing the run, because a model that only
    needs creases should not stop working when a ray engine is unavailable.
    """
    cuts = np.zeros(len(pairs), dtype=bool)
    found = {"thickness": None, "roughness": None}

    if use_roughness:
        rough = surface_roughness(pairs, angles, count, rounds=rough_rounds)
        found["roughness"] = rough
        if np.ptp(rough) > 0:
            boundary = _class_boundary(
                rough, pairs, float(np.percentile(rough, rough_percentile)), below=False)
            if boundary is not None:
                cuts |= boundary

    if use_thickness and vertices is not None:
        thickness = local_thickness(vertices, triangles, normals, centroids)
        found["thickness"] = thickness
        if thickness is not None and np.isfinite(thickness).any():
            cutoff = float(np.nanpercentile(thickness[np.isfinite(thickness)],
                                            thin_percentile))
            boundary = _class_boundary(thickness, pairs, cutoff, below=True)
            if boundary is not None:
                cuts |= boundary

    return cuts, found


def coverage_report(labels, areas):
    """How concentrated the segmentation is -- the tell for a collapsed run.

    A single region holding almost the whole surface means the signals in use
    found nothing, whatever the segment count says.
    """
    count = int(labels.max()) + 1 if len(labels) else 0
    if not count:
        return {"segments": 0, "largest_area_fraction": 1.0, "collapsed": True}
    totals = np.bincount(labels, weights=areas, minlength=count)
    share = totals / max(totals.sum(), 1e-12)
    largest = float(share.max())
    meaningful = int((share > 0.005).sum())
    return {
        "segments": count,
        "largest_area_fraction": largest,
        "meaningful_segments": meaningful,
        "collapsed": largest > 0.90 or meaningful < 2,
    }
