"""Level 0 from a scale space of the mesh, so the rung stops being a choice.

`label_tree.py` builds its top level by k-means over the six CLUSTER_ON descriptors
of the patches at one hand-picked rung. On the shell at rung 400 with ten regions it
covers 100% of faces and does surface real classes -- the rib crests come out as one
class running across every whorl, the coral tubes as another, the umbilicus fan as a
third -- but the smooth inter-rib panels are split across several clusters that are
not several things. Measured on the ground agent's 34 clicked panel patches: the
largest single cluster holds 19% of the panel area, and 90% of touching panel-panel
pairs disagree. That is the failure this script attacks.

**Why the shipped descriptors cannot fix it.** They are mostly properties of the
tessellation rather than of the surface. Re-segmenting the same model at rung 400
with SLIC seeds 7 / 11 / 23 and correlating face-level, area weighted, gives
elongation 0.261, extent 0.465, relief 0.590, flatness 0.707, roughness 0.736,
curvature 0.785. Segment the same shell at a different rung and it is worse:
extent 0.155 and elongation 0.140 between rung 400 and rung 6400. Clustering on
numbers that move when the segmenter is re-seeded produces regions that move too.

**The scale space.** `paintlib.signals.relief` smooths the surface and subtracts it,
a high-pass whose cut-off is its `iterations` argument -- hardcoded at 12. Expose
that argument and the same primitive becomes a stack:

    r_k(f)  = relief(vertices, faces, iterations=k),  k = 3, 6, 12, 24, ...
    v_k(a)  = area-weighted mean of |r_k| over atom a
    lr_k(a) = log v_k(a) - log(the same mean over the whole model)
    SLOPE   = least-squares slope of lr_k against log2(k)     -- the atom's own scale
    LEVEL   = mean lr_k                                       -- how much relief at all
    RESID   = rms departure from that line                    -- peaked, or flat

Verified: level k=12 of the stack correlates 1.000000 with the session's shipped
`relief.npy`, so this is that one primitive with its hidden parameter opened up.
The whole stack costs about 2 seconds on 626,766 faces because the smoothing is
incremental -- k=48 is the k=24 copy smoothed 24 more times.

**On the shell it is a property of the surface, not of the segmenter.** Same
three-seed test on the shipped configuration: SLOPE 0.879, LEVEL 0.955, RESID 0.925,
against 0.261 for elongation. Same model, atoms taken from rung 400 versus rung
12800: SLOPE 0.793, LEVEL 0.934, against extent's 0.155. And it recovers the recorded
scale inversion from an instrument that never touches the ladder -- mean lr_k over the
ground-truth classes at k = 3, 6, 12, 24, 48:

    barnacle  +0.389 +0.339 +0.274 +0.189 +0.081   falling: a fine-scale thing
    rib       +0.152 +0.172 +0.191 +0.198 +0.192   flat to rising: a coarse one

which is the handoff's "flank band clean at 400, upper whorl clean at 12800" written
as two curves with opposite tilt. On the 66 ground-truth patches SLOPE separates
barnacle from rib at AUC 0.945 and barnacle from panel at 0.846. It does not separate
rib from panel: 0.607, close to nothing, and that negative is the reason this script
improves the panel without fixing it.

**On the dragon it is not.** Same three-seed test there: SLOPE 0.639, LEVEL 0.642 --
still the most reproducible descriptor available on that model, where roughness
manages 0.622 and elongation 0.348, but nowhere near the shell's 0.879, and below the
0.8 bar the design set itself as a genericity check. Lengthening the ladder does not
recover it (0.639 at 3..24, 0.650 at 3..384), so it is not a ladder artefact. Whatever
makes the scale statistic stable on a single sculpted body does not carry to 29
articulated ones. Read the shell numbers as a result on the shell.

**Where the ladder stops is measured, not chosen.** The design this implements
proposed extending it while the diffusion radius sqrt(k)*mean_edge stays under a
quarter of the model diagonal. Implemented literally that gives k up to 6144 on the
shell and it is measurably wrong: barnacle-versus-rib AUC degrades from 0.945 to
0.594 as the fit is dragged across the bend where smoothing has eaten the model's own
form. The rule used instead compares two mesh quantities and has no fraction in it:
extend while the model-wide mean |r_k| stays under one mean edge length, because past
that the smoothed copy sits further from the surface than neighbouring samples sit
from each other, and it is no longer a local reference. Shell: k = 3..48. Dragon:
k = 3..24.

**Potts instead of plain k-means.** Assignment minimises

    ||x(a) - centroid(g)||^2  +  beta * (number of neighbours not in g)

by ICM, alternating with centroid updates. This is not the recorded merge-on-
agreement dead end, which put 89% of the model in one patch: there is no predicate
and no transitive closure, one disagreeing contact costs beta and is outvoted, and a
merged cluster's data cost rises because centroids are refitted every round. beta is
read off the data -- the median margin between an atom's best and second-best
centroid divided by the mean atom degree -- so an average-sized neighbourhood has to
be roughly unanimous to flip an atom of typical margin.

**Coverage is total and disjoint by construction**, by the same four mechanisms
label_tree.py already relies on: every atom takes exactly one argmin, every face
inherits its atom's label, faces stranded at a parent boundary go to fill_nearest
across the surface rather than to a global default, and a subdivision only ever
partitions its parent's own faces.

**Hidden faces bias the new axis, so they are excluded from it.** The shell's view
atlas sees 89.28% of faces from at least one of 32 directions; the unseen 10.72% is
only 3.24% of area, but it carries 1.7x the fine-scale relief of visible surface, so
left in it drags enclosed crevices toward the fine-scale end and into the barnacle
class. Atom statistics are therefore taken over visible faces where an atom has any
and over all of them otherwise -- 399 of 400 atoms take the first branch. Labelling
still covers hidden faces: every input here is mesh-intrinsic, nothing is ray-cast.
What hidden faces break is *verification*, so each node carries the share of its area
no view reaches and a majority-hidden node is reported as not visually verifiable.

**What it does to the failure, measured against the baseline it replaces**, both at
rung 400 with ten regions on the shell, scored on the ground agent's clicked patches:

    smooth panel   dominant cluster 19% -> 39%, spread over 9 clusters -> 6,
                   perplexity 7.57 -> 4.64, touching panel pairs disagreeing 90% -> 68%
    rib            dominant 80% -> 80%, 3 clusters -> 2, and now in a cluster of its
                   own: in the baseline the rib class *was* the largest panel cluster
    barnacle       dominant 52% -> 69%, touching pairs disagreeing 55% -> 27%
    coral          dominant 43% -> 39%, touching pairs disagreeing 67% -> 33%
    cluster areas  max:min 1.95 -> 55.1, the price of z-scores over ranks

The design that specified this set its own bar at 60% of panel area in one cluster.
39% does not clear it, and the render says the same thing the number does: the smooth
panels come out in two or three large classes instead of six or seven small ones, and
the rib class still bleeds onto smooth surface between the whorls. This is real
progress on a recorded failure and it is not a fix. What it is unambiguously good for
is the level below: subdividing the barnacle region at the rung computed from that
region's own scale profile puts every barnacle aperture on the model in one class.

**Parameters a human still chooses: one, the region count.** The rung, the SLIC seed,
the ladder ends, the relief floor, the visibility rule and the Potts weight are all
computed. `--regions auto` removes the last one by peak cross-restart stability and
returns 8 on the shell, inside the 8-10 window established independently -- but it
varies only the k-means restart, so it is a weaker measurement than it looks.

    level0_multiscale.py --session work/                       # level 0
    level0_multiscale.py --session work/ --regions auto
    level0_multiscale.py --session work/ --parent "barnacle field"
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from patch_features import DESCRIPTORS, describe_patches, cluster    # noqa: E402
from resolve_parts import fill_nearest                               # noqa: E402
from scale_ladder import ladder_path                                 # noqa: E402
from label_tree import (TREE, PALETTE, load_tree, save_tree, find,   # noqa: E402
                        visible_coordinate)

CACHE = "scale_space.npz"
SHAPE_ON = ["flatness", "roughness", "curvature"]


def build_scale_space(vertices, faces, areas):
    """The stack of high-passes, and the rung where it stops being one.

    Smoothing is carried forward between rungs, so the whole ladder costs barely
    more than its top rung. The loop ends when the surface has departed from its
    smoothed copy by more than one edge length: two mesh quantities, no fraction.
    """
    from scipy.sparse import coo_matrix

    vertices = np.asarray(vertices, dtype=np.float64)
    count = len(vertices)
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    mean_edge = float(np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]],
                                     axis=1).mean())
    both = np.vstack([edges, edges[:, ::-1]])
    graph = coo_matrix((np.ones(len(both)), (both[:, 0], both[:, 1])),
                       shape=(count, count)).tocsr()
    degree = np.asarray(graph.sum(axis=1)).ravel()
    degree[degree == 0] = 1.0

    face_normals = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]],
                            vertices[faces[:, 2]] - vertices[faces[:, 0]])
    lengths = np.linalg.norm(face_normals, axis=1, keepdims=True)
    weights = lengths.ravel() / 2.0
    face_normals = face_normals / np.maximum(lengths, 1e-12)
    normals = np.zeros_like(vertices)
    for column in range(3):
        np.add.at(normals, faces[:, column], face_normals * weights[:, None])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)

    stack, rungs = [], []
    smoothed, done, k = vertices.copy(), 0, 3
    while True:
        for _ in range(k - done):
            smoothed = np.asarray(graph @ smoothed) / degree[:, None]
        done = k
        displacement = np.einsum("ij,ij->i", vertices - smoothed, normals)
        level = displacement[faces].mean(axis=1).astype(np.float32)
        stack.append(level)
        rungs.append(k)
        if float((np.abs(level) * areas).sum() / areas.sum()) > mean_edge:
            break
        k *= 2
    # The rung that broke the condition is kept in the cache but out of the fit:
    # a fit wants at least three points to have a residual at all.
    keep = max(3, len(rungs) - 1)
    return np.array(stack), np.array(rungs), keep, mean_edge


def scale_space(session_dir, session):
    path = os.path.join(session_dir, CACHE)
    if os.path.exists(path):
        cached = np.load(path)
        return cached["stack"], cached["rungs"], int(cached["keep"]), float(cached["edge"])
    stack, rungs, keep, edge = build_scale_space(session["vertices"], session["faces"],
                                                 session["areas"])
    np.savez_compressed(path, stack=stack, rungs=rungs, keep=keep, edge=edge)
    return stack, rungs, keep, edge


def scale_statistics(labels, stack, rungs, areas, usable, floor):
    """SLOPE, LEVEL, RESID per atom, plus the raw log-ratio profile for reporting.

    `usable` is the visible-face mask. An atom with no visible face falls back to all
    of its faces rather than dropping out, so the statistic stays defined everywhere
    and the labelling stays total.

    `floor` is what stops a log of nothing. The shell has a planar underside where
    relief is exactly zero at the fine rungs, and unfloored those atoms come back with
    SLOPE +16.9 against a model spread of about 0.1 -- one atom then owns the feature
    space and steals a cluster. The floor is the model's own coordinate precision, so
    it is read off the vertex array rather than picked: a displacement smaller than
    the file can represent is not a measurement.
    """
    count = int(labels.max()) + 1
    profile = np.zeros((count, len(rungs)))
    hit = np.zeros(count, dtype=bool)
    for index in range(len(rungs)):
        magnitude = np.abs(stack[index])
        reference = float((magnitude * areas).sum() / areas.sum())
        weighted = magnitude * areas
        seen_top = np.bincount(labels[usable], weights=weighted[usable], minlength=count)
        seen_bottom = np.bincount(labels[usable], weights=areas[usable], minlength=count)
        all_top = np.bincount(labels, weights=weighted, minlength=count)
        all_bottom = np.bincount(labels, weights=areas, minlength=count)
        top = np.where(seen_bottom > 0, seen_top, all_top)
        bottom = np.maximum(np.where(seen_bottom > 0, seen_bottom, all_bottom), 1e-30)
        value = top / bottom
        hit |= value < floor
        profile[:, index] = (np.log(np.maximum(value, floor))
                             - np.log(max(reference, 1e-30)))

    axis = np.log2(rungs.astype(float))
    axis = axis - axis.mean()
    slope = (profile * axis).sum(axis=1) / (axis ** 2).sum()
    level = profile.mean(axis=1)
    fitted = level[:, None] + slope[:, None] * axis[None, :]
    resid = np.sqrt(((profile - fitted) ** 2).mean(axis=1))
    return np.column_stack([slope, level, resid]), profile, hit


def atom_contacts(labels, pairs):
    left, right = labels[pairs[:, 0]], labels[pairs[:, 1]]
    crossing = left != right
    low = np.minimum(left[crossing], right[crossing])
    high = np.maximum(left[crossing], right[crossing])
    return np.unique(np.column_stack([low, high]), axis=0)


def potts(space, contacts, groups, seed, beta=None, rounds=12):
    """k-means for a starting point, then ICM against a Potts smoothing term.

    Returns (assignment, beta). With beta=None the weight is read off the data: the
    median gap between an atom's best and second-best centroid, divided by the mean
    number of neighbours an atom has, so a typical atom flips only when a typical
    neighbourhood is close to unanimous.
    """
    assignment, centres = cluster(space, groups, seed=seed)
    groups = len(centres)
    count = len(space)
    neighbours = [[] for _ in range(count)]
    for a, b in contacts:
        neighbours[int(a)].append(int(b))
        neighbours[int(b)].append(int(a))
    degree = np.mean([len(n) for n in neighbours]) or 1.0

    def data_cost():
        return ((space[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)

    if beta is None:
        ordered = np.sort(data_cost(), axis=1)
        beta = float(np.median(ordered[:, 1] - ordered[:, 0]) / degree)

    for _ in range(rounds):
        cost = data_cost()
        for atom in range(count):
            if neighbours[atom]:
                disagree = np.full(groups, len(neighbours[atom]), dtype=float)
                for other in neighbours[atom]:
                    disagree[assignment[other]] -= 1.0
                cost[atom] += beta * disagree
        updated = np.argmin(cost, axis=1).astype(np.int32)
        for index in range(groups):
            members = space[updated == index]
            if len(members):
                centres[index] = members.mean(axis=0)
        if (updated == assignment).all():
            assignment = updated
            break
        assignment = updated
    return assignment, float(beta)


def stability_k(space, contacts, candidates, seeds):
    """The k whose partition is most reproducible across restarts.

    The rule this replaces -- take the largest k still as reproducible as k=4 -- was
    proposed with the caveat that it had never been run. Run on the shell it returns
    20, the top of the candidate range, because the curve never falls back to its
    k=4 value (0.29) again: 4:0.29 5:0.45 6:0.42 7:0.55 8:0.67 9:0.62 10:0.61 ...
    20:0.56. The peak of that same curve is k=8, which is inside the 8-10 window the
    ground agent established independently, so the argmax is what is used here.

    It is still the weakest thing in this script: it varies only the k-means starting
    point, not the segmentation underneath, so it measures the objective's own basin
    structure rather than the model's. The curve is printed so a reader can disagree.
    """
    def rand_index(a, b):
        table = np.zeros((a.max() + 1, b.max() + 1))
        for x, y in zip(a, b):
            table[x, y] += 1
        rows, columns = table.sum(axis=1), table.sum(axis=0)
        pairs = lambda v: (v * (v - 1) / 2).sum()                    # noqa: E731
        total = len(a) * (len(a) - 1) / 2
        expected = pairs(rows) * pairs(columns) / total
        maximum = (pairs(rows) + pairs(columns)) / 2
        return float((pairs(table) - expected) / max(maximum - expected, 1e-12))

    curve = []
    for k in candidates:
        runs = [potts(space, contacts, k, seed=s)[0] for s in seeds]
        scores = [rand_index(runs[i], runs[j])
                  for i in range(len(runs)) for j in range(i + 1, len(runs))]
        curve.append((k, float(np.mean(scores))))
    return max(curve, key=lambda entry: entry[1])[0], curve


def subdivision_rung(profile_row, rungs, total_area, mean_edge, built):
    """The rung to subdivide a region at, computed rather than passed in.

    The region's log-ratio profile peaks at the scale its relief lives on; convert
    that to a radius and take the built rung whose median patch radius is closest.
    """
    peak = rungs[int(np.argmax(profile_row))]
    radius = float(np.sqrt(peak)) * mean_edge
    return min(built, key=lambda r: abs(np.sqrt(total_area / (np.pi * r)) - radius))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--regions", default="10",
                        help="how many regions, or 'auto' for the stability sweep")
    parser.add_argument("--parent", default=None,
                        help="subdivide this label instead of the whole surface")
    parser.add_argument("--rung", type=int, default=None,
                        help="atoms come from this rung; the default is the coarsest "
                             "built one at level 0 and the computed one below it")
    parser.add_argument("--beta", type=float, default=None,
                        help="Potts weight; the default is read off the data")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    faces, areas = session["faces"], session["areas"]
    total_area = float(areas.sum())
    tree = load_tree(args.session)

    stack, rungs, keep, mean_edge = scale_space(args.session, session)
    fit_rungs = rungs[:keep]
    print("scale space: k = %s  (mean edge %.4fmm, %d rungs cached)"
          % (", ".join(str(int(k)) for k in fit_rungs), mean_edge, len(rungs)))

    atlas_path = os.path.join(args.session, "view_atlas.npz")
    if os.path.exists(atlas_path):
        visible = np.load(atlas_path)["seen"] > 0
        print("view atlas: %.2f%% of faces seen, %.2f%% of area"
              % (100 * visible.mean(), 100 * areas[visible].sum() / total_area))
    else:
        visible = np.ones(len(faces), dtype=bool)
        print("no view atlas: every face treated as visible")

    built = sorted(int(name[7:-4]) for name in os.listdir(args.session)
                   if name.startswith("ladder_") and name.endswith(".npy"))
    if not built:
        raise SystemExit("level0_multiscale: no ladder rungs built; run "
                         "scale_ladder.py --build")

    parent = None
    if args.parent:
        parent = find(tree, args.parent)
        if parent is None:
            raise SystemExit("level0_multiscale: no label %r" % args.parent)

    rung = args.rung
    if rung is None:
        rung = (parent.get("subdivide_rung") or built[-1]) if parent else built[0]
    if rung not in built:
        raise SystemExit("level0_multiscale: rung %d not built" % rung)
    patch_labels = np.load(ladder_path(args.session, rung))

    if parent is not None:
        member_faces = np.array(parent["face_indices"], dtype=np.int64)
        prefix = "%s/" % parent["name"]
    else:
        member_faces = np.arange(len(faces))
        prefix = ""
    inside = np.zeros(len(faces), dtype=bool)
    inside[member_faces] = True

    counts = np.bincount(patch_labels[inside], minlength=int(patch_labels.max()) + 1)
    live = np.flatnonzero(counts > 0)
    if len(live) < 2:
        raise SystemExit("level0_multiscale: rung %d gives %d patch(es) inside %r"
                         % (rung, len(live), args.parent))

    centres = session["vertices"][faces].mean(axis=1)
    diagonal = float(np.linalg.norm(np.ptp(session["vertices"], axis=0))) or 1.0
    relief_path = os.path.join(args.session, "relief.npy")
    fields = {"relief": np.load(relief_path) if os.path.exists(relief_path)
              else np.zeros(len(faces)),
              "occlusion": session["occlusion"], "roughness": session["roughness"],
              "thickness": session["thickness"]}
    rows, _stats = describe_patches(patch_labels, centres, session["normals"],
                                    areas, fields, diagonal)
    floor = float(np.finfo(session["vertices"].dtype).eps) * diagonal
    scale_rows, profile, floored = scale_statistics(patch_labels, stack[:keep],
                                                    fit_rungs, areas, visible, floor)
    print("relief floor %.2e mm (%s coordinates): %d of %d atoms reach it at some rung"
          % (floor, session["vertices"].dtype, int(floored[live].sum()), len(live)))

    # An atom that reaches the floor has no scale signature to fit, and standing it
    # next to atoms that do wrecks both. Unfloored it owns the space; floored and left
    # in, the shell's planar underside still ate three of ten regions and each of them
    # was invisible from every view. Given a class of its own -- a nameable thing, a
    # flat cut face -- the remaining regions go back to describing the surface: panel
    # perplexity 4.80 -> 4.64, rib dominant share 52% -> 80%, barnacle 47% -> 69%.
    measurable = live[~floored[live]]
    flat = live[floored[live]]

    # z-score rather than rank: rank-normalising makes every cluster near-equal-area,
    # and a shell's smooth body is many times the area of its ribs. Measured by the
    # ground agent: panel perplexity 7.24 -> 5.30 and cluster area max:min 1.95 -> 4.9.
    raw = np.column_stack([rows[:, [DESCRIPTORS.index(n) for n in SHAPE_ON]], scale_rows])
    space = raw[measurable]
    space = (space - space.mean(axis=0)) / np.maximum(space.std(axis=0), 1e-12)

    contacts = atom_contacts(patch_labels, session["pairs"])
    index_of = {int(p): i for i, p in enumerate(measurable)}
    local = np.array([[index_of[int(a)], index_of[int(b)]] for a, b in contacts
                      if int(a) in index_of and int(b) in index_of], dtype=np.int64)
    if not len(local):
        local = np.zeros((0, 2), dtype=np.int64)

    if str(args.regions).lower() == "auto":
        groups, curve = stability_k(space, local, range(4, min(21, len(measurable))),
                                    seeds=(args.seed, args.seed + 4, args.seed + 16))
        print("k by restart stability: %d   %s"
              % (groups, "  ".join("%d:%.2f" % (k, s) for k, s in curve)))
    else:
        asked = min(int(args.regions), len(measurable))
        groups = max(1, asked - (1 if len(flat) else 0))

    assignment, beta = potts(space, local, groups, seed=args.seed, beta=args.beta)
    print("Potts beta %.3f%s over %d atoms, %d contacts"
          % (beta, " (given)" if args.beta is not None else " (from the data)",
             len(measurable), len(local)))

    region_of_patch = {int(p): int(g) for p, g in zip(measurable, assignment)}
    for patch in flat:
        region_of_patch[int(patch)] = groups
    if len(flat):
        groups += 1
    face_region = np.full(len(faces), -1, dtype=np.int32)
    for face_index in member_faces:
        face_region[face_index] = region_of_patch.get(int(patch_labels[face_index]), -1)
    if (face_region[member_faces] < 0).any():
        filled = fill_nearest(face_region, session["pairs"])
        face_region[member_faces] = filled[member_faces]

    tree["nodes"] = [n for n in tree["nodes"]
                     if not (n.get("parent") == (parent["name"] if parent else None)
                             and n.get("auto"))]
    added = []
    for group in range(groups):
        mask = (face_region == group) & inside
        if not mask.any():
            continue
        indices = np.flatnonzero(mask)
        members = np.array([p for p, g in region_of_patch.items() if g == group])
        weight = np.array([areas[patch_labels == p].sum() for p in members])
        weight = weight / max(weight.sum(), 1e-12)
        row = (profile[members] * weight[:, None]).sum(axis=0)
        name = "%sregion-%d" % (prefix, group)
        while find(tree, name):
            name += "'"
        hidden = float(areas[indices][~visible[indices]].sum() / areas[indices].sum())
        node = {"name": name, "parent": parent["name"] if parent else None,
                "rung": rung, "auto": True,
                "area": round(float(areas[mask].sum() / total_area), 5),
                "faces": int(mask.sum()),
                "at": visible_coordinate(session, indices),
                "hidden_area_share": round(hidden, 4),
                "slope": round(float((scale_rows[members, 0] * weight).sum()), 4),
                "level": round(float((scale_rows[members, 1] * weight).sum()), 4),
                "resid": round(float((scale_rows[members, 2] * weight).sum()), 4),
                "subdivide_rung": int(subdivision_rung(row, fit_rungs, total_area,
                                                       mean_edge, built)),
                "centroid": [round(float(v), 2) for v in
                             session["vertices"][faces[indices]].mean(axis=(0, 1))],
                "face_indices": [int(v) for v in indices]}
        tree["nodes"].append(node)
        added.append(node)
    save_tree(args.session, tree)

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = np.tile(np.array([0.88, 0.88, 0.90]), (len(faces), 1))
    for index, node in enumerate(added):
        colours[node["face_indices"]] = PALETTE[index % len(PALETTE)]
    out = os.path.join(args.session, "labels")
    os.makedirs(out, exist_ok=True)
    slug = "multiscale-" + (parent["name"].replace("/", "-") if parent else "level0")
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug).strip("-")
    for view in (["iso", "front", "left", "back"] if not parent else ["iso"]):
        image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view], 900)
        raster.save_png(os.path.join(out, "%s-%s.png" % (slug, view)), image)

    print("\n%d regions inside %s at rung %d"
          % (len(added), parent["name"] if parent else "the whole surface", rung))
    for index, node in enumerate(added):
        rgb = PALETTE[index % len(PALETTE)]
        flag = "  NOT VISUALLY VERIFIABLE" if node["hidden_area_share"] > 0.5 else ""
        print("  %-22s %6.2f%%  slope %+6.3f level %+6.3f resid %5.3f  hidden %5.2f%%"
              "  next rung %5d  at %-16s rgb(%3d,%3d,%3d)%s"
              % (node["name"], 100 * node["area"], node["slope"], node["level"],
                 node["resid"], 100 * node["hidden_area_share"], node["subdivide_rung"],
                 node["at"] or "-", *(int(255 * c) for c in rgb), flag))

    claimed = np.zeros(len(faces), dtype=np.int32)
    for node in added:
        claimed[node["face_indices"]] += 1
    scope = claimed[member_faces]
    print("\ncoverage: %d of %d faces in this scope carry exactly one label, "
          "%d carry none, %d carry more than one"
          % (int((scope == 1).sum()), len(member_faces), int((scope == 0).sum()),
             int((scope > 1).sum())))
    print("          %.4f%% of the scope's area labelled"
          % (100 * areas[member_faces][scope > 0].sum() / areas[member_faces].sum()))
    print("  render: %s/%s-*.png" % (out, slug))
    print("  LOOK at it before believing any of the numbers above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
