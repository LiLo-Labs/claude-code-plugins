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


def atoms(mesh, cap=300, base_k=15.0, min_faces=60, scales=12, log=None):
    """Cached front door: the atoms of a mesh are a pure function of its
    geometry and these parameters, so they are computed once per mesh EVER,
    whatever output directory a run uses."""
    import hashlib
    key = hashlib.sha256()
    key.update(np.ascontiguousarray(mesh.vertices).tobytes())
    key.update(np.ascontiguousarray(mesh.faces).tobytes())
    key.update(("%s|%s|%s|%s|fastscale-v3" % (cap, base_k, min_faces,
                                               scales)).encode())
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
                                      log=log)
    np.savez_compressed(cache, face_atom=face_atom,
                        children=tree["children"], base=tree["base"],
                        regions=np.int64(tree["regions"]),
                        node_of_atom=np.asarray(tree["node_of_atom"],
                                                dtype=np.int64),
                        area=tree["area"], features=tree["features"])
    return face_atom, tree


def _atoms_uncached(mesh, cap=300, base_k=15.0, min_faces=60, scales=12,
                    log=None):
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
    weights = index_regions.edge_weights(session, index, None, 0.0)
    pairs = session["pairs"]
    count = len(session["faces"])
    base = index_regions.felzenszwalb(pairs, weights, count, base_k, min_faces)
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
