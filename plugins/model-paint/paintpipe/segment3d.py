"""3D feature atoms: segment the surface in 3D, then let the agent NAME the pieces.

What the Voronoi patches were missing, stated plainly: their borders only PREFER
creases. A patch is a tile, not a feature, so a part boundary can only ever be as good
as the tiling that happened to fall near it -- which is exactly why a cow's legs ended
at the ankles: the hip junction ran through patch interiors, and no vote can split a
patch.

This module replaces the tiling with the 3D segmentation this project already built and
validated in its first arc, then abandoned at the spec pivot:

    scale-space index    -- per-face characteristic scale and signed relief, computed by
                            diffusion over the face graph in 3D (Lindeberg's
                            characteristic scale; scripts/scale_space.py)
    Felzenszwalb regions -- adaptive-threshold agglomeration over edge weights built
                            from scale gap + relief gap + dihedral turn
                            (scripts/index_regions.py)
    merge tree +         -- every region pair merged in border order; objects chosen by
    persistence            how long they survive, walking EVERY forest root
                            (scripts/index_persist.py -- the code that found each dragon
                            spike, the skull and the feet as whole objects)

The atoms handed to the naming agent are a cut of that merge tree, so their boundaries
are concave junctions and relief edges found in 3D -- hips, not ankles. The agent's job
shrinks to what it is good at: saying which atom is which part. And because the atoms
are tree nodes, every atom still carries its own sub-tree, which is what makes
"colour the sub-part" a descent rather than a re-segmentation.
"""

import os
import sys

import numpy as np

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def _session_arrays(mesh):
    """The minimal session dict the v0 functions expect, straight from a mesh."""
    return {"vertices": np.asarray(mesh.vertices, dtype=np.float64),
            "faces": np.asarray(mesh.faces, dtype=np.int64),
            "normals": np.asarray(mesh.face_normals, dtype=np.float64),
            "pairs": np.asarray(mesh.face_adjacency, dtype=np.int64),
            "areas": np.asarray(mesh.area_faces, dtype=np.float64)}


def scale_index(mesh, scales=12, log=None):
    """The 3D scale-space index, multigrid (paintpipe.fastscale): identical
    ladder and outputs to the v0 builder, coarse rungs on quotient graphs."""
    from . import fastscale
    session = _session_arrays(mesh)
    if log:
        log("  scale index over %d faces..." % len(mesh.faces))
    return fastscale.build(session, scales=scales, log=log), session


def calibrate(mesh, index, nozzle_mm=0.4, log=None):
    """Read `min_faces` and a target region count off the model and the printer.

    Both were hand-set constants (`base_k=15.0`, `min_faces=60`), and the
    HANDOFF names them as such. A face count is the wrong unit for either: 60
    faces is a barnacle on one model and a speck on the next, so the same
    number means different sizes on different meshes and nothing at all across
    two models.

    `min_faces` becomes a PHYSICAL floor. A region narrower than a couple of
    extrusion widths cannot be laid down as its own colour, so a region below
    that area is confetti by definition -- not because it is small in
    triangles, but because the printer cannot express it.

    `base_k` DOES NOT get the same treatment, and the reason is measured
    rather than assumed. The obvious rule -- one region per disc of the
    model's own fine characteristic radius -- was tried and refuted. To
    reproduce the region counts that are known to work, the dragon needs a
    ratio of 0.455 against its p25 radius and the shell needs 1.238: a factor
    of 2.7 apart, and worse at other quantiles. So the scale-space quantiles do
    not predict a good region count, and any single coefficient here would be
    fitted to one model.

    What the same measurement DOES show is worth recording, because it points
    at a real defect rather than a missing constant. The shell's structure is
    genuinely five times finer than the dragon's (p5 characteristic radius
    0.96mm against 4.97mm -- barnacles against spikes), yet the two land within
    14% of each other in region count, 1469 against 1291, while their triangle
    counts differ by 32%. The current substrate therefore tracks TESSELLATION
    DENSITY, not the structure of the object, and an encrusted model is
    under-resolved relative to its own detail. `base_k` stays an explicit,
    documented parameter until that is fixed properly; `target_regions` (see
    `solve_base_k`) is offered as the better-shaped knob, because a region
    count is a quantity somebody can reason about and `k` is not.

    Returns (min_faces, scale_report).
    """
    areas = np.asarray(mesh.area_faces, dtype=float)
    total = float(areas.sum())
    mean_face = total / max(len(areas), 1)

    # Two extrusion widths: one is a single bead, which no slicer will place
    # as an isolated colour, so the smallest honest region is a pair.
    floor_mm2 = float(np.pi * (nozzle_mm) ** 2)
    min_faces = int(max(4, round(floor_mm2 / max(mean_face, 1e-12))))

    radius = np.asarray(index["characteristic_mm"], dtype=float)
    radius = radius[np.isfinite(radius)]
    report = {"surface_mm2": round(total, 1),
              "min_faces": min_faces,
              "floor_mm2": round(floor_mm2, 4),
              "fine_radius_mm": round(float(np.percentile(radius, 5)), 3),
              "quartile_radius_mm": round(float(np.percentile(radius, 25)), 3)}
    if log:
        log("  calibrate: %.0f mm2 surface; structure radius p5 %.2f mm, "
            "p25 %.2f mm; min_faces %d (%.3f mm2 floor at %.2f mm nozzle)"
            % (total, report["fine_radius_mm"], report["quartile_radius_mm"],
               min_faces, floor_mm2, nozzle_mm))
    return min_faces, report


def solve_base_k(pairs, weights, count, min_faces, target_regions, sizes=None,
                 tolerance=0.12, rounds=12, log=None):
    """Solve for the merge threshold instead of choosing it.

    `k` gates every merge against `internal + k / size`, so region count falls
    monotonically as k rises -- which makes it a bisection rather than a
    search. The bracket is widened first (a fixed one silently pins k to an
    endpoint on a model whose weights are scaled differently), then halved
    until the region count is within `tolerance` of the target.

    Monotonicity is what makes this safe: there is exactly one k per count, so
    the answer does not depend on where the bisection started.
    """
    import index_regions

    def regions_at(k):
        labels = index_regions.felzenszwalb(pairs, weights, count, float(k),
                                            min_faces, sizes=sizes)
        return int(labels.max()) + 1, labels

    low, high = 0.05, 5.0
    low_n, _ = regions_at(low)
    high_n, high_labels = regions_at(high)
    for _widen in range(8):
        if high_n <= target_regions:
            break
        low, low_n = high, high_n
        high *= 4.0
        high_n, high_labels = regions_at(high)
    if low_n < target_regions:
        # Even the finest bracket is coarser than asked for: the mesh cannot
        # express the target, and saying so beats returning an endpoint as
        # though it were a solution.
        if log:
            log("  base_k: mesh bottoms out at %d regions, target was %d"
                % (low_n, target_regions))
        return float(low), regions_at(low)[1]

    best_k, best_labels, best_n = high, high_labels, high_n
    for _round in range(rounds):
        middle = 0.5 * (low + high)
        count_here, labels = regions_at(middle)
        if abs(count_here - target_regions) < abs(best_n - target_regions):
            best_k, best_labels, best_n = middle, labels, count_here
        if abs(count_here - target_regions) <= tolerance * target_regions:
            best_k, best_labels, best_n = middle, labels, count_here
            break
        if count_here > target_regions:
            low = middle
        else:
            high = middle
    if log:
        log("  base_k solved: %.3f -> %d regions (target %d)"
            % (best_k, best_n, target_regions))
    return float(best_k), best_labels


def atoms(mesh, cap=300, base_k=15.0, min_faces=None, scales=12, log=None,
          evidence=None, camera_weight=2.0, nozzle_mm=0.4,
          target_regions=None):
    """Cached front door: the atoms of a mesh are a pure function of its
    geometry and these parameters, so they are computed once per mesh EVER,
    whatever output directory a run uses."""
    import hashlib
    key = hashlib.sha256()
    key.update(np.ascontiguousarray(mesh.vertices).tobytes())
    key.update(np.ascontiguousarray(mesh.faces).tobytes())
    # The evidence is part of what the atoms ARE, so it is part of their
    # identity. A cache key that ignored it would serve geometry-only atoms to
    # a caller that paid to render the model, silently and forever.
    key.update(("%s|%s|%s|%s|%s|%s|%s|fastscale-v4"
                % (cap, base_k, min_faces, scales, nozzle_mm, target_regions,
                   camera_weight if evidence is not None else "geom")).encode())
    if evidence is not None:
        key.update(np.ascontiguousarray(
            np.asarray(evidence["evidence"], dtype=np.float32)).tobytes())
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "model-paint")
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, "atoms-%s.npz" % key.hexdigest()[:20])
    if os.path.exists(cache):
        if log:
            log("  atoms from cache: %s" % cache)
        saved = np.load(cache, allow_pickle=False)
        tree = {"children": saved["children"], "base": saved["base"],
                "regions": int(saved["regions"]),
                "node_of_atom": [int(v) for v in saved["node_of_atom"]],
                "area": saved["area"], "features": saved["features"]}
        return saved["face_atom"], tree
    face_atom, tree = _atoms_uncached(mesh, cap=cap, base_k=base_k,
                                      min_faces=min_faces, scales=scales,
                                      log=log, evidence=evidence,
                                      camera_weight=camera_weight,
                                      nozzle_mm=nozzle_mm,
                                      target_regions=target_regions)
    np.savez_compressed(cache, face_atom=face_atom,
                        children=tree["children"], base=tree["base"],
                        regions=np.int64(tree["regions"]),
                        node_of_atom=np.asarray(tree["node_of_atom"],
                                                dtype=np.int64),
                        area=tree["area"], features=tree["features"])
    return face_atom, tree


def _atoms_uncached(mesh, cap=300, base_k=15.0, min_faces=None, scales=12,
                    log=None, evidence=None, camera_weight=2.0,
                    nozzle_mm=0.4, target_regions=None):
    """Feature-aligned atoms: a cut of the persistence merge tree, at most `cap` wide.

    Returns (face_atom, tree) where `tree` carries what a caller needs to descend into
    sub-parts: the merge children, the base-region labels, and each atom's node id.

    The cut is top-down by area: start at the forest roots and keep splitting whichever
    current node has the largest area until the cap is reached or nodes stop having
    children. Internal boundaries are the tree's own -- concave junctions and relief
    edges -- so a medium feature (a leg, a spike) becomes one atom, a big surface (a
    torso) becomes several, and tiny features group into their local cluster until a
    sub-pass descends. `cap` is the id-legibility bound, the same honest constant that
    governs the id renders; it does not shape any boundary, only how many tree nodes
    are offered at once.
    """
    import index_regions
    import index_persist

    index, session = scale_index(mesh, scales=scales, log=log)

    # CAMERA EVIDENCE, WHEN THE CALLER PAID FOR IT. This call used to hardcode
    # (None, 0.0) -- geometry only -- and its sibling in scripts/hierarchy_select.py
    # carries a comment saying that exact call was a bug it already fixed.
    # Geometry alone does not see a boundary that is soft relief rather than a
    # crease, so on an encrusted surface it blurs straight across the edges
    # that matter most, and no later stage can recover a boundary the substrate
    # never drew.
    weights = index_regions.edge_weights(
        session, index, evidence,
        camera_weight if evidence is not None else 0.0)
    pairs = session["pairs"]
    count = len(session["faces"])

    # The speck floor is no longer a face count somebody picked: it is the
    # smallest area this printer can lay down as its own colour. `base_k` stays
    # explicit -- see calibrate() for the measurement that refused to justify a
    # derived value -- but a caller who knows what granularity they want can
    # ask for a region COUNT and have k solved for it, which is a quantity a
    # person can reason about in a way that k is not.
    solved_min, _report = calibrate(mesh, index, nozzle_mm=nozzle_mm, log=log)
    if min_faces is None:
        min_faces = solved_min
    if target_regions:
        base_k, base = solve_base_k(pairs, weights, count, min_faces,
                                    int(target_regions), log=log)
    else:
        base = index_regions.felzenszwalb(pairs, weights, count, base_k,
                                          min_faces)
    regions = int(base.max()) + 1
    if log:
        log("  base regions: %d" % regions)

    left, right = base[pairs[:, 0]], base[pairs[:, 1]]
    crossing = left != right
    key = (np.minimum(left[crossing], right[crossing]).astype(np.int64) * regions
           + np.maximum(left[crossing], right[crossing]).astype(np.int64))
    unique, inverse = np.unique(key, return_inverse=True)
    totals = np.bincount(inverse, weights=weights[crossing])
    seen = np.bincount(inverse)
    region_pairs = np.stack([unique // regions, unique % regions], axis=1).astype(np.int64)
    region_weights = totals / np.maximum(seen, 1)
    region_area = np.bincount(base, weights=session["areas"], minlength=regions)

    children, birth, death, area, used = index_persist.merge_tree(
        region_pairs, region_weights, regions, region_area)
    roots = index_persist.forest_roots(children, used)

    # Top-down cut by area, bounded by the cap.
    import heapq
    heap = [(-float(area[int(r)]), int(r)) for r in roots]
    heapq.heapify(heap)
    frontier = []
    while heap and len(heap) + len(frontier) < cap:
        _negative, node = heapq.heappop(heap)
        kids = children[node]
        if node < regions or kids[0] < 0:
            frontier.append(node)
            continue
        heapq.heappush(heap, (-float(area[int(kids[0])]), int(kids[0])))
        heapq.heappush(heap, (-float(area[int(kids[1])]), int(kids[1])))
    frontier.extend(node for _n, node in heap)

    # Faces of each frontier node, via its base-region leaves.
    face_atom = np.full(count, -1, dtype=np.int32)
    node_of_atom = []
    for atom_id, node in enumerate(sorted(frontier)):
        leaves = []
        index_persist.leaves_of(children, int(node), regions, leaves)
        mask = np.isin(base, leaves)
        face_atom[mask] = atom_id
        node_of_atom.append(int(node))
    if log:
        log("  atoms: %d (from %d tree nodes over %d forest roots)"
            % (len(node_of_atom), used, len(roots)))
    # Per-face geometric signature, kept because recovery needs it: a
    # scattered texture family (barnacle fields) is found again by what its
    # confirmed members MEASURE like, not by adjacency. Radius and relief
    # sign alone matched a third of an everywhere-encrusted shell, so the
    # third axis is response strength -- how sharply featured the surface is
    # at its characteristic scale -- which separates a granular field from a
    # smooth dome that happens to share its radius.
    response = index["response"]
    peak = np.argmax(response, axis=0)
    strength = response[peak, np.arange(response.shape[1])]
    tree = {"children": children, "base": base, "regions": regions,
            "node_of_atom": node_of_atom, "area": area,
            "features": np.stack([index["characteristic_mm"],
                                  index["signed"],
                                  strength], axis=1).astype(np.float32)}
    return face_atom, tree


def snap_to_base(tree, face_part, areas, keep=None):
    """Labels live on the merge tree's base regions; faces only follow.

    Naming votes on atoms, but every downstream mutation -- recovery
    claims, design cuts, sweeps, welds -- was free to move single faces,
    and single-face moves are where every ragged boundary came from: a
    boundary that is not a region edge is not a geometric edge at all.
    This projection assigns each base region its area-majority label, so
    whatever a stage just did, the label field it hands on is a cut of
    the tree again. Faces never move alone -- with one exception: `keep`
    marks faces whose label is a DESIGN decision (a pattern painted onto
    smooth geometry has no tree node to snap to), and those keep their
    label untouched.
    """
    base = np.asarray(tree["base"], dtype=np.int64)
    regions = int(tree["regions"])
    areas = np.asarray(areas, dtype=np.float64)
    best = np.full(regions, -1.0)
    winner = np.full(regions, -1, dtype=np.asarray(face_part).dtype)
    for label in np.unique(face_part):
        chosen = face_part == label
        mass = np.bincount(base[chosen], weights=areas[chosen],
                           minlength=regions)
        take = mass > best
        winner[take] = label
        best[take] = mass[take]
    snapped = winner[base]
    if keep is not None and np.any(keep):
        snapped[keep] = face_part[keep]
    return snapped


def descend(tree, atom_id, max_children=32):
    """One atom's own sub-atoms, from its sub-tree: the parent/child colouring hook."""
    import index_persist
    children = tree["children"]
    node = tree["node_of_atom"][atom_id]
    out = []
    frontier = [node]
    while frontier and len(out) + len(frontier) < max_children:
        current = frontier.pop(0)
        kids = children[current]
        if current < tree["regions"] or kids[0] < 0:
            out.append(current)
        else:
            frontier.extend((int(kids[0]), int(kids[1])))
    out.extend(frontier)
    faces = {}
    for sub_id, sub_node in enumerate(out):
        leaves = []
        index_persist.leaves_of(children, int(sub_node), tree["regions"], leaves)
        faces[sub_id] = np.flatnonzero(np.isin(tree["base"], leaves))
    return faces
