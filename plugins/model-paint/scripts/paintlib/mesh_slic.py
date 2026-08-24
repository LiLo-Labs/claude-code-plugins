"""Over-segment the surface itself into patches, with no render in the loop.

An earlier version of this rendered the model, segmented the image, and carried
the answer back to triangles. The boundaries were excellent -- superpixels snap to
exactly the edges a person sees -- but the fusion inherited a limit that has no
business existing: a 626,766 triangle model at 1600 pixels gives about five pixels
per face, the per-face majority vote flips between viewpoints, and the surface
shatters. Raising resolution is chasing a problem created by looking at a picture
of something already in memory.

So run the same idea on the mesh. SLIC's formulation carries over directly, with
the face graph standing in for the pixel grid: seed evenly over the surface, grow
by a cost that trades distance against how different the surface looks, and
iterate. Every triangle is a first-class element, nothing is occluded, nothing is
foreshortened, and the result does not depend on where a camera stood.

The cost between neighbouring faces mixes:

  distance   how far apart they are, which keeps patches compact
  normal     how much the surface turns, which is what a crease IS
  relief     whether one stands proud of the other
  cavity     whether one is inside something and the other is not

Normal difference dominates, because that is the cue that separates a barnacle
from the shell it sits on. Distance only stops a patch from wandering.
"""

import heapq

import numpy as np


def _normalise(values):
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    if not finite.any():
        return np.zeros_like(values)
    lo, hi = np.percentile(values[finite], [2, 98])
    out = np.clip((values - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    out[~finite] = 0.0
    return out


def edge_costs(centres, normals, pairs, fields=None, feature_weight=6.0,
               normal_weight=4.0, boundary_prior=None, prior_weight=8.0):
    """Cost of walking between two adjacent faces. Higher means a likelier edge."""
    spatial = np.linalg.norm(centres[pairs[:, 0]] - centres[pairs[:, 1]], axis=1)
    scale = float(np.median(spatial)) or 1.0

    turn = 1.0 - np.einsum("ij,ij->i", normals[pairs[:, 0]], normals[pairs[:, 1]])
    turn = np.clip(turn, 0.0, 2.0) / 2.0

    difference = normal_weight * turn
    for values in (fields or {}).values():
        scaled = _normalise(values)
        difference = difference + np.abs(scaled[pairs[:, 0]] - scaled[pairs[:, 1]])

    if boundary_prior is not None:
        # How often an ensemble of runs put these two faces in DIFFERENT patches.
        # Thresholding that agreement directly does not work: disagreements are
        # scattered and never close into curves, so merging on them leaks until
        # the model is one patch. As a cost it behaves properly -- a pair that
        # runs keep separating becomes expensive to cross, and the final
        # segmentation puts a boundary there because it is cheaper to go around.
        difference = difference + prior_weight * np.clip(
            1.0 - np.asarray(boundary_prior, dtype=float), 0.0, 1.0)

    return (spatial / scale) * (1.0 + feature_weight * difference) + 1e-6


def _farthest_seeds(centres, count, adjacency_pairs, rng):
    """Spread seeds over the surface by repeated farthest-point selection."""
    total = len(centres)
    first = int(rng.integers(total))
    seeds = [first]
    best = np.linalg.norm(centres - centres[first], axis=1)
    while len(seeds) < count:
        pick = int(np.argmax(best))
        if best[pick] <= 0:
            break
        seeds.append(pick)
        best = np.minimum(best, np.linalg.norm(centres - centres[pick], axis=1))
    return np.array(seeds, dtype=np.int64)


def _assign(neighbours, weights, seeds, face_count):
    """Multi-source Dijkstra: every face joins the seed that reaches it cheapest."""
    distance = np.full(face_count, np.inf)
    owner = np.full(face_count, -1, dtype=np.int32)
    heap = []
    for index, seed in enumerate(seeds):
        distance[seed] = 0.0
        owner[seed] = index
        heap.append((0.0, int(seed)))
    heapq.heapify(heap)

    while heap:
        cost, face = heapq.heappop(heap)
        if cost > distance[face]:
            continue
        for neighbour, weight in zip(neighbours[face], weights[face]):
            candidate = cost + weight
            if candidate < distance[neighbour]:
                distance[neighbour] = candidate
                owner[neighbour] = owner[face]
                heapq.heappush(heap, (candidate, neighbour))
    return owner, distance


def consensus_patches(centres, normals, pairs, scales=(1200, 2000, 3200),
                      repeats=2, fields=None, agreement=0.6, iterations=2,
                      feature_weight=6.0, normal_weight=4.0, seed=7, progress=None):
    """Run the segmentation many times and keep only the boundaries runs agree on.

    A single run is one opinion. Its seeding is arbitrary, and where a patch
    boundary lands in a smooth region depends on where the nearest seeds happened
    to fall -- so a boundary can appear in one run and not the next. Real edges do
    not behave that way: a crease separates the same two triangles no matter how
    the surface was seeded, and no matter whether it was cut into 1,200 patches or
    3,200.

    So vary both the seeding and the scale, and count. For every pair of adjacent
    triangles, how many runs put them in the same patch? Merge the pair only if
    most runs did. What survives is the set of boundaries that are a property of
    the geometry rather than of one arbitrary seeding, and the patches between
    them are correspondingly more trustworthy.

    Runs at different scales also disagree usefully: a fine run splits a barnacle
    from its neighbour, a coarse run keeps a whole rib together, and the pairs they
    agree on are the ones that matter at every scale.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    face_count = len(centres)
    together = np.zeros(len(pairs), dtype=np.int32)
    runs = 0

    for scale in scales:
        for repeat in range(max(1, int(repeats))):
            labels = superpatches(centres, normals, pairs, target_patches=scale,
                                  fields=fields, iterations=iterations,
                                  feature_weight=feature_weight,
                                  normal_weight=normal_weight,
                                  seed=seed + runs * 101 + repeat)
            together += labels[pairs[:, 0]] == labels[pairs[:, 1]]
            runs += 1
            if progress:
                progress(runs, len(scales) * max(1, int(repeats)), scale,
                         int(labels.max()) + 1)

    merge = (together / float(runs)) >= agreement
    graph = coo_matrix((np.ones(int(merge.sum())), (pairs[merge, 0], pairs[merge, 1])),
                       shape=(face_count, face_count))
    _, labels = connected_components(graph, directed=False)
    return labels.astype(np.int32), together / float(runs)


def superpatches(centres, normals, pairs, target_patches=3000, fields=None,
                 iterations=3, feature_weight=6.0, normal_weight=4.0, seed=7,
                 progress=None, boundary_prior=None, prior_weight=8.0):
    """Split the surface into roughly `target_patches` compact, edge-respecting pieces.

    Returns a label per face. Deterministic for a given mesh and seed.
    """
    face_count = len(centres)
    target_patches = max(1, min(int(target_patches), face_count))

    costs = edge_costs(centres, normals, pairs, fields, feature_weight, normal_weight,
                       boundary_prior, prior_weight)
    neighbours = [[] for _ in range(face_count)]
    weights = [[] for _ in range(face_count)]
    for (left, right), cost in zip(pairs, costs):
        neighbours[left].append(int(right))
        weights[left].append(float(cost))
        neighbours[right].append(int(left))
        weights[right].append(float(cost))

    rng = np.random.default_rng(seed)
    seeds = _farthest_seeds(centres, target_patches, pairs, rng)

    owner = None
    for step in range(max(1, int(iterations))):
        owner, _distance = _assign(neighbours, weights, seeds, face_count)
        if progress:
            progress(step + 1, len(seeds))
        if step == iterations - 1:
            break
        # Re-seed each patch at the face closest to its own centroid, which is what
        # makes this iterate toward compact patches rather than staying wherever
        # the first sampling happened to land.
        moved = []
        for index in range(len(seeds)):
            members = np.flatnonzero(owner == index)
            if not len(members):
                continue
            middle = centres[members].mean(axis=0)
            moved.append(int(members[np.argmin(
                np.linalg.norm(centres[members] - middle, axis=1))]))
        if not moved:
            break
        seeds = np.array(sorted(set(moved)), dtype=np.int64)

    # Any face the walk never reached (an isolated shell) becomes its own patch.
    orphans = np.flatnonzero(owner < 0)
    if len(orphans):
        owner = owner.copy()
        owner[orphans] = np.arange(len(orphans)) + owner.max() + 1
    _, labels = np.unique(owner, return_inverse=True)
    return labels.astype(np.int32)
