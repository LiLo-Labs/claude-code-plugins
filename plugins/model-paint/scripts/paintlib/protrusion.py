"""Find protruding features that leave no crease where they meet the surface.

Dihedral segmentation finds anything that meets the body at an angle: eyes set
into sockets, plates, a nose horn sitting proud of the snout. It cannot find a
sculpted horn, because a sculpted horn blends smoothly into the skull and there
is no edge to cut on. Measured on a real dragon, crease cutting alone left both
horns and both eyes inside one 27,468-triangle region.

Local thickness separates them. Cast a ray from each triangle inward along its
own inverted normal and measure the distance to the far wall: that is the shape
diameter. Horns, spikes, claws, teeth and fins are thin. Skulls, bodies and
limbs are thick. The boundary between them is the neck of the protrusion, which
is exactly where a person would draw the line too.

Two corrections matter in practice:

1. Growing from thin seeds. The thinnest 20 percent of a horn is its tip, not the
   whole horn. Each seed is grown outward while thickness rises gently and cut
   where it jumps, which is the neck.
2. Interior faces. A ball-joint socket is a thin wall and scores exactly like a
   horn. Those faces are inside the model, invisible and unpaintable, and are
   dropped by testing whether a ray leaving the face escapes the mesh.
"""

import numpy as np


def _ray_engine_available(mesh):
    try:
        mesh.ray
        return True
    except Exception:
        return False


def local_thickness(mesh, epsilon=1e-3):
    """Shape diameter per face: distance through the solid, or NaN if unmeasurable."""
    origins = mesh.triangles_center - mesh.face_normals * epsilon
    hit = mesh.ray.intersects_first(ray_origins=origins,
                                    ray_directions=-mesh.face_normals)
    thickness = np.full(len(mesh.faces), np.nan)
    valid = hit >= 0
    if valid.any():
        near = mesh.triangles_center[valid]
        far = mesh.triangles_center[hit[valid]]
        thickness[valid] = np.linalg.norm(near - far, axis=1)
    return thickness


def exterior_mask(mesh, epsilon=1e-3):
    """False for faces buried inside the model, which can never be seen or painted."""
    origins = mesh.triangles_center + mesh.face_normals * epsilon
    hit = mesh.ray.intersects_first(ray_origins=origins,
                                    ray_directions=mesh.face_normals)
    return hit < 0


def _clusters(adjacency, member, count):
    """Connected components of the subgraph induced by `member`."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    both = member[adjacency[:, 0]] & member[adjacency[:, 1]]
    if not both.any():
        return np.full(count, -1), 0
    graph = coo_matrix((np.ones(int(both.sum())),
                        (adjacency[both, 0], adjacency[both, 1])),
                       shape=(count, count))
    total, labels = connected_components(graph, directed=False)
    labels = np.where(member, labels, -1)
    return labels, total


def _grow(seed_faces, neighbors, thickness, allowed, seed_thickness,
          neck_ratio, max_faces):
    """Flood out from a seed while the solid stays thin, and give up if it floods.

    A horn stays thin all the way to its neck, then the skull behind it is several
    times thicker. Bounding growth at `neck_ratio` times the seed thickness cuts
    exactly there. If the region still runs past `max_faces`, this was not a
    protrusion at all -- it was a thin shell somewhere on the body -- and the
    caller discards it rather than painting a third of the model.
    """
    ceiling = seed_thickness * neck_ratio
    region = set(int(f) for f in seed_faces)
    queue = list(region)
    while queue:
        face = queue.pop()
        for neighbor in neighbors[face]:
            neighbor = int(neighbor)
            if neighbor in region or not allowed[neighbor]:
                continue
            value = thickness[neighbor]
            if not np.isfinite(value) or value > ceiling:
                continue
            region.add(neighbor)
            if len(region) > max_faces:
                return None            # flooded: not a compact feature
            queue.append(neighbor)
    return np.array(sorted(region), dtype=np.int64)


def find_protrusions(mesh, seed_percentile=20.0, min_seed_faces=60,
                     neck_ratio=2.2, max_fraction=0.12, exclude_interior=True):
    """Return a list of face-index arrays, one per protruding feature.

    Parameters are deliberately blunt. The output is reviewed by a human against
    a render before anything is painted, so a missed spike costs one round of
    conversation, not a ruined print.
    """
    if not _ray_engine_available(mesh):
        return []

    count = len(mesh.faces)
    adjacency = mesh.face_adjacency
    if not len(adjacency):
        return []

    thickness = local_thickness(mesh)
    if not np.isfinite(thickness).any():
        return []

    allowed = np.isfinite(thickness)
    if exclude_interior:
        allowed &= exterior_mask(mesh)
    if not allowed.any():
        return []

    cutoff = np.nanpercentile(thickness[allowed], seed_percentile)
    seeds = allowed & (thickness <= cutoff)
    labels, total = _clusters(adjacency, seeds, count)
    if not total:
        return []

    neighbors = [[] for _ in range(count)]
    for left, right in adjacency:
        neighbors[left].append(right)
        neighbors[right].append(left)

    max_faces = int(count * max_fraction)
    claimed = np.zeros(count, dtype=bool)
    features = []
    order = sorted(range(total), key=lambda c: -int((labels == c).sum()))
    for cluster in order:
        members = np.where(labels == cluster)[0]
        if len(members) < min_seed_faces or claimed[members].any():
            continue
        grown = _grow(members, neighbors, thickness, allowed & ~claimed,
                      float(np.nanmedian(thickness[members])), neck_ratio, max_faces)
        if grown is None or len(grown) < min_seed_faces:
            continue
        claimed[grown] = True
        features.append(grown)
    return features
