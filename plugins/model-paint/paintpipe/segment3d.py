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


def hidden_edges(base, pairs, evidence, quantile=0.90, stand_out=2.0):
    """Face pairs the substrate calls one region while the camera sees an edge.

    THIS IS THE CEILING, MADE COUNTABLE. Every claim in this pipeline is a
    union of base regions, so a boundary that runs through the middle of a
    region cannot be expressed by any of them -- not by the climb, not by the
    ladder, not by any amount of looking. The survey can only select among
    nodes that exist.

    A pair where the segmentation says "same region" and the camera says
    "there is an edge here" is exactly such a place, and it is a disagreement
    between two signals that are already computed. So the ceiling stops being
    an abstract worry and becomes a number: how much of what can be seen is
    unreachable by anything downstream.

    Returns (mask over pairs, the strength cut used).
    """
    best = np.asarray(evidence["evidence"], dtype=float).max(axis=0)
    observed = np.asarray(evidence["seen"], dtype=float) > 0
    if not observed.any():
        return np.zeros(len(pairs), dtype=bool), 0.0
    # A quantile alone is not enough, and a test caught it: on a surface whose
    # evidence is nearly uniform -- nothing distinctive seen anywhere -- the
    # top decile is still a tenth of the pairs, so the rule would report the
    # whole model as hiding edges and re-cut all of it on the strength of no
    # observation at all. An edge has to STAND OUT to count, so it must clear
    # the quantile AND be a real multiple of the typical pair. When the
    # distribution is flat those two conditions cannot both hold, which is the
    # correct answer: nothing was seen, so nothing is hidden.
    cut = float(np.percentile(best[observed], 100.0 * quantile))
    typical = float(np.median(best[observed]))
    cut = max(cut, stand_out * typical)
    strong = observed & (best >= cut) & (best > 0)
    internal = base[pairs[:, 0]] == base[pairs[:, 1]]
    return strong & internal, cut


def refine_substrate(base, pairs, weights, areas, evidence, min_faces,
                     base_k=15.0, rounds=3, log=None, **kwargs):
    """Split, then look again, until nothing more can be split.

    One pass cannot finish the job: splitting a region moves some of its hidden
    edges onto the new boundaries, but a piece that is still too coarse still
    hides its own. Each round is cheap (4s on a 475k-triangle model) and each
    one is strictly local to what is still contradicted, so this converges
    rather than running away -- it stops when no region hides enough to be
    worth re-cutting, or when the pieces would fall below what the printer can
    lay down.
    """
    report = {"rounds": [], "start_regions": int(base.max()) + 1}
    for number in range(int(rounds)):
        base, step = split_hidden(base, pairs, weights, areas, evidence,
                                  min_faces, base_k=base_k, log=log, **kwargs)
        report["rounds"].append(step)
        if not step.get("split"):
            break
    report["end_regions"] = int(base.max()) + 1
    return base, report


def split_hidden(base, pairs, weights, areas, evidence, min_faces,
                 base_k=15.0, quantile=0.90, min_hidden=3, ladder=(0.25, 0.06,
                                                                   0.015),
                 log=None):
    """Re-cut only the regions that hide an edge, and only as far as they can go.

    NOT by deleting the strong edges and taking components. That is a recorded
    dead end in this project: a scattered subset of cut edges never closes a
    curve, so it cannot bound a region, and growth simply routes around the
    gap (the edge wall blocked 4.66% of contacts and changed nothing). The cut
    has to be agglomerative, which is what felzenszwalb is -- so the offending
    region is re-merged from its own faces at a finer threshold, and the
    strong edges do their work by being expensive to merge across rather than
    by being removed.

    Refinement is LOCAL and CONDITIONAL, which is what keeps it honest and
    cheap. A region nobody saw an edge inside is left exactly as it was, so
    this can only add detail where something observed it.

    The ladder stops at `min_faces` -- the printer's own floor. A region that
    cannot split into parts the printer could lay down as separate colours is
    left whole, because splitting it would manufacture a boundary finer than
    anything that could ever be printed. The residual ceiling after this pass
    is therefore two real limits and no artefacts: edges nothing can observe,
    and edges finer than the nozzle.
    """
    import index_regions

    hidden, cut = hidden_edges(base, pairs, evidence, quantile=quantile)
    if not hidden.any():
        if log:
            log("  refine: no region hides a visible edge")
        return base, {"suspect": 0, "split": 0, "added": 0, "cut": cut}

    owner = base[pairs[hidden][:, 0]]
    regions, counts = np.unique(owner, return_counts=True)
    suspect = regions[counts >= int(min_hidden)]
    if not len(suspect):
        return base, {"suspect": 0, "split": 0, "added": 0, "cut": cut}

    # Faces grouped by region once, rather than scanned per region.
    order = np.argsort(base, kind="stable")
    starts = np.searchsorted(base[order], np.arange(int(base.max()) + 2))
    # Internal pairs grouped by region, likewise.
    internal = base[pairs[:, 0]] == base[pairs[:, 1]]
    inner_pairs = pairs[internal]
    inner_weights = weights[internal]
    inner_owner = base[inner_pairs[:, 0]]
    pair_order = np.argsort(inner_owner, kind="stable")
    pair_starts = np.searchsorted(inner_owner[pair_order],
                                  np.arange(int(base.max()) + 2))

    refined = base.copy()
    next_label = int(base.max()) + 1
    split_count = 0
    for region in suspect:
        faces = order[starts[region]:starts[region + 1]]
        if len(faces) < 2 * min_faces:
            continue
        local_pairs = inner_pairs[pair_order[pair_starts[region]:
                                             pair_starts[region + 1]]]
        local_weights = inner_weights[pair_order[pair_starts[region]:
                                                 pair_starts[region + 1]]]
        if not len(local_pairs):
            continue
        lookup = np.full(int(base.shape[0]), -1, dtype=np.int64)
        lookup[faces] = np.arange(len(faces))
        mapped = lookup[local_pairs]
        keep = (mapped >= 0).all(axis=1)
        if not keep.any():
            continue
        mapped, local_weights = mapped[keep], local_weights[keep]

        # Make the hidden edges the most expensive merges in this region, so
        # the re-cut lands ON the thing that was seen. Without this the split
        # goes wherever the weights happen to be highest, which is the same
        # edge only because `edge_weights` folded the evidence in upstream --
        # an implicit coupling a caller can break by passing geometry-only
        # weights alongside camera evidence, and then the region splits
        # confidently in the wrong place. This is a weighting, not a drawing:
        # felzenszwalb still decides whether to cut at all.
        local_hidden = hidden[internal][pair_order[pair_starts[region]:
                                                   pair_starts[region + 1]]]
        local_hidden = local_hidden[keep]
        if local_hidden.any():
            local_weights = local_weights.copy()
            local_weights[local_hidden] = max(
                float(local_weights.max()) * 1.5, 1e-6)

        for step in ladder:
            labels = index_regions.felzenszwalb(mapped, local_weights,
                                                len(faces), base_k * step,
                                                min_faces)
            parts = int(labels.max()) + 1
            if parts >= 2:
                sizes = np.bincount(labels, minlength=parts)
                if int(sizes.min()) >= min_faces:
                    refined[faces] = next_label + labels
                    next_label += parts
                    split_count += 1
                    break

    added = next_label - (int(base.max()) + 1) - split_count
    _unique, refined = np.unique(refined, return_inverse=True)
    refined = refined.astype(np.int32)
    report = {"suspect": int(len(suspect)), "split": int(split_count),
              "added": int(added), "cut": round(float(cut), 5),
              "hidden_pairs": int(hidden.sum())}
    if log:
        log("  refine: %d regions hid a visible edge, %d split into finer "
            "regions (+%d); %d -> %d regions"
            % (len(suspect), split_count, added, int(base.max()) + 1,
               int(refined.max()) + 1))
    return refined, report


def atoms(mesh, cap=300, base_k=15.0, min_faces=None, scales=12, log=None,
          evidence=None, camera_weight=2.0, nozzle_mm=0.4,
          target_regions=None, refine=True, refine_rounds=3):
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
    key.update(("%s|%s|%s|%s|%s|%s|%s|%s|%s|fastscale-v5"
                % (cap, base_k, min_faces, scales, nozzle_mm, target_regions,
                   refine, refine_rounds,
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
                                      target_regions=target_regions,
                                      refine=refine,
                                      refine_rounds=refine_rounds)
    np.savez_compressed(cache, face_atom=face_atom,
                        children=tree["children"], base=tree["base"],
                        regions=np.int64(tree["regions"]),
                        node_of_atom=np.asarray(tree["node_of_atom"],
                                                dtype=np.int64),
                        area=tree["area"], features=tree["features"])
    return face_atom, tree


def _atoms_uncached(mesh, cap=300, base_k=15.0, min_faces=None, scales=12,
                    log=None, evidence=None, camera_weight=2.0,
                    nozzle_mm=0.4, target_regions=None, refine=True,
                    refine_rounds=3):
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

    # BREAK THE CEILING. Every claim downstream is a union of base regions, so
    # a boundary running through the middle of one cannot be expressed by any
    # of them: the survey can only select among nodes that exist. Regions that
    # hide an edge the camera can see are re-cut here, locally and only where
    # something observed the contradiction, down to the printer's own floor.
    if evidence is not None and refine:
        base, _refine_report = refine_substrate(
            base, pairs, weights, session["areas"], evidence, min_faces,
            base_k=base_k, rounds=refine_rounds, log=log)
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
