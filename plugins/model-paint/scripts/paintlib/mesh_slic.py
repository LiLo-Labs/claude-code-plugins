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
               normal_weight=4.0):
    """Cost of walking between two adjacent faces. Higher means a likelier edge."""
    spatial = np.linalg.norm(centres[pairs[:, 0]] - centres[pairs[:, 1]], axis=1)
    scale = float(np.median(spatial)) or 1.0

    turn = 1.0 - np.einsum("ij,ij->i", normals[pairs[:, 0]], normals[pairs[:, 1]])
    turn = np.clip(turn, 0.0, 2.0) / 2.0

    difference = normal_weight * turn
    for values in (fields or {}).values():
        scaled = _normalise(values)
        difference = difference + np.abs(scaled[pairs[:, 0]] - scaled[pairs[:, 1]])

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


def superpatches(centres, normals, pairs, target_patches=3000, fields=None,
                 iterations=3, feature_weight=6.0, normal_weight=4.0, seed=7,
                 progress=None):
    """Split the surface into roughly `target_patches` compact, edge-respecting pieces.

    Returns a label per face. Deterministic for a given mesh and seed.
    """
    face_count = len(centres)
    target_patches = max(1, min(int(target_patches), face_count))

    costs = edge_costs(centres, normals, pairs, fields, feature_weight, normal_weight)
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
