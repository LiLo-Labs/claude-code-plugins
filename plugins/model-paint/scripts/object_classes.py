"""Class objects by what they ARE, not by where they happen to sit.

Three identification defects were visible on the shell once every feature type was
given one colour and looked at from six sides. All three are classification errors
sitting on top of correct boundaries, and all three have generic causes.

**Height split every repeated feature in two.** Normalised height was a clustering
feature, so the barnacle cones above z=22mm and the identical cones below it became
two classes, and so did their throats, and so did the shell itself -- no class equalled
"the shell". Height is not a property of what a thing IS. A cup is a cup on the crown or
at the foot. It is gone from the feature set. The one thing it was there for, isolating
the flat underside, is done properly here by measurement: faces whose normal points
down and which sit at the model's lowest extent are invisible from every camera
direction, which is a fact about the model rather than a threshold.

**The exposed underlayer inside a break could not be separated from the outer shell.**
It is the same material, the same size and the same flatness; nothing measured at its
own scale distinguishes them. What distinguishes them is that one is a step BELOW its
surroundings and the other IS the surroundings. So the feature set gains
`parent-relative elevation`: the offset of an object measured not at its own scale but
at the scale of the thing it sits on, normalised by its own size. Positive means it
stands proud -- a barnacle on a shell, a boss on a plate. Negative means it is recessed
-- an underlayer revealed by a break, the floor of a groove. Zero means it is the
surface. This is the generic distinction between applied, revealed, and base, and it is
the one axis the earlier feature sets had no way to express.

**Classes that over-reach cannot be fixed by choosing k.** Splitting a bad class by
raising k re-cuts every good class too. `--split` re-clusters WITHIN one class and
leaves the rest untouched, so an agent that looks at a class render and says "this one
holds two things" gets that class divided and nothing else disturbed.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from patch_features import cluster                                   # noqa: E402

FEATURES = ["log extent mm", "relief", "log area", "parent elevation"]
PALETTE = np.array([
    [0.90, 0.24, 0.20], [0.20, 0.55, 0.90], [0.30, 0.75, 0.35], [0.95, 0.65, 0.15],
    [0.65, 0.35, 0.85], [0.10, 0.70, 0.70], [0.95, 0.45, 0.65], [0.55, 0.45, 0.25],
    [0.45, 0.80, 0.20], [0.20, 0.35, 0.70], [0.85, 0.35, 0.45], [0.40, 0.65, 0.60],
    [0.75, 0.55, 0.90], [0.60, 0.60, 0.20], [0.25, 0.60, 0.45], [0.90, 0.50, 0.30],
])


def hidden_underside(session):
    """Faces that point down at the model's lowest extent: the printed footprint.

    Measured, not assumed: these are invisible from every direction, so they can never
    be clicked, never be judged from a render, and must never be painted.
    """
    faces, vertices, normals = session["faces"], session["vertices"], session["normals"]
    height = vertices[faces].mean(axis=1)[:, 2]
    span = max(float(np.ptp(height)), 1e-9)
    return (normals[:, 2] < -0.9) & (height < height.min() + 0.01 * span)


def object_rows(session, index, objects, parent_ratio):
    """One row per object. No position, no height -- only what the thing is."""
    count = int(objects.max()) + 1
    areas = session["areas"]
    radii = np.asarray(index["radii_mm"], dtype=np.float64)
    characteristic = np.asarray(index["characteristic_mm"], dtype=np.float64)
    signed = np.asarray(index["signed"], dtype=np.float64)
    offset = np.asarray(index["offset"], dtype=np.float64) if "offset" in index else None

    # The rung standing for "the scale of what this sits on": several times the face's
    # own scale, clipped to the ladder that exists.
    if offset is not None:
        own = np.searchsorted(radii, characteristic).clip(0, len(radii) - 1)
        parent = np.searchsorted(radii, characteristic * parent_ratio).clip(0, len(radii) - 1)
        rows_index = np.arange(len(characteristic))
        elevation = offset[parent, rows_index] / np.maximum(characteristic, 1e-6)
    else:
        elevation = np.zeros(len(characteristic))

    total = float(areas.sum())
    order = np.argsort(objects, kind="stable")
    bounds = np.searchsorted(objects[order], np.arange(count + 1))
    corners = session["vertices"][session["faces"]]
    rows = np.zeros((count, 4))
    for node in range(count):
        members = order[bounds[node]:bounds[node + 1]]
        if not len(members):
            continue
        # How big the thing IS, from its own extent in millimetres -- not the median of
        # its faces' characteristic scale. That was the dominant feature and it does not
        # measure size: on four barnacle cups of 1.6, 1.1, 1.0 and 3.7mm extent it
        # returned 0.99, 3.42, 2.50 and 1.83mm, in the wrong order. It measures how fast
        # the surface turns nearby, which depends on how tightly the cups are packed and
        # how deep each throat is. That is why identical cups landed in different classes
        # and whole colonies came out unselected while their neighbours matched.
        span = np.ptp(corners[members].reshape(-1, 3), axis=0)
        rows[node] = (np.log(max(float(np.linalg.norm(span)), 1e-6)),
                      np.median(signed[members]),
                      np.log(max(areas[members].sum() / total, 1e-9)),
                      np.median(elevation[members]))
    return rows


def standardise(rows, live):
    out = rows - rows[live].mean(axis=0)
    return out / np.maximum(rows[live].std(axis=0), 1e-9)



def graph_classes(space, areas, k_neighbours, strength):
    """Group objects by merging the most alike first, with no fixed number of classes.

    k-means was the wrong instrument and the renders said so. It cuts a feature space
    into exactly k pieces wherever the boundaries fall, and repeated instances of one
    feature form a DENSE BLOB rather than a tidy island -- so two barnacle cones in the
    same chain landed in different classes, four neighbouring rosettes in three, and one
    continuous crack ran through four. A class became "a fragment skimmed off five
    different feature populations". Nothing about that is fixable by choosing k or by
    splitting afterwards: the cut runs through the middle of a population.

    Merging fixes it at the root. Two objects that measure almost the same are joined
    before anything else happens, so near-identical instances CANNOT end up apart --
    which is the property the whole exercise needs and the one k-means cannot offer.
    The threshold adapts per group, exactly as it does when regions are built from
    faces, so a tight population of 200 cones stays one class while a loose scatter is
    allowed to divide.

    The graph is the mutual k-nearest-neighbour graph in feature space: an edge exists
    only where both objects count the other among their nearest. That asymmetry matters
    -- a lone outlier names a neighbour but is not named back, so it stays out instead of
    dragging a real population toward itself.
    """
    from scipy import sparse
    from scipy.spatial import cKDTree

    count = len(space)
    k = int(min(max(k_neighbours, 2), count - 1))
    tree = cKDTree(space)
    distance, neighbour = tree.query(space, k=k + 1)

    rows = np.repeat(np.arange(count), k)
    cols = neighbour[:, 1:].ravel()
    vals = distance[:, 1:].ravel()
    forward = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(count, count))
    mutual = forward.multiply(forward.T)
    keep = np.asarray(mutual[rows, cols]).ravel() > 0
    pairs = np.stack([rows[keep], cols[keep]], axis=1)
    weights = vals[keep]
    if not len(pairs):
        return np.arange(count)

    order = np.argsort(weights, kind="stable")
    parent = np.arange(count)
    size = np.ones(count)
    internal = np.zeros(count)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for edge in order:
        a, b = find(pairs[edge, 0]), find(pairs[edge, 1])
        if a == b:
            continue
        w = weights[edge]
        if w <= min(internal[a] + strength / size[a], internal[b] + strength / size[b]):
            if size[a] < size[b]:
                a, b = b, a
            parent[b] = a
            size[a] += size[b]
            internal[a] = w
    roots = np.array([find(i) for i in range(count)])
    _u, labels = np.unique(roots, return_inverse=True)
    return labels.astype(np.int32)



def enforce_twins(labels, space, adjacency, areas_of, tolerance=0.35, rounds=8):
    """Make near-identical touching objects share a class, without merging classes.

    Two invariants matter and they pull against each other. Objects that measure almost
    the same and touch each other ARE the same feature and must share a class -- two
    barnacle cones in one chain landing in different classes is the defect that started
    this. But genuinely different neighbours must stay apart, and that is the invariant
    a merge-everything scheme quietly destroys.

    Measured on the shell over 54 twin pairs and 1,021 distinct-neighbour pairs:
    replacing the fixed-k cut with adaptive merging took twins from 92.6% to 100% and
    distinct-neighbours from 99.6% down to 84.4%. It fixed four pairs and broke about a
    hundred and fifty. A test that a single all-swallowing class passes perfectly cannot
    certify a partition, which is why both numbers are measured here and neither alone.

    So keep the cut that separates well, and repair only where it violates the other
    invariant: a disagreeing twin pair is pulled onto whichever of the two classes
    carries more surface, repeatedly until nothing changes. Only the objects in
    violation move; the class structure is untouched.
    """
    labels = labels.copy()
    for _ in range(rounds):
        moved = 0
        for a, b in adjacency:
            if labels[a] == labels[b]:
                continue
            if np.linalg.norm(space[a] - space[b]) > tolerance:
                continue
            first = areas_of[labels == labels[a]].sum()
            second = areas_of[labels == labels[b]].sum()
            winner = labels[a] if first >= second else labels[b]
            labels[a] = labels[b] = winner
            moved += 1
        if not moved:
            break
    return labels


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--objects", default="index_objects.npy")
    parser.add_argument("--classes", type=int, default=12)
    parser.add_argument("--parent-ratio", type=float, default=4.0,
                        help="how many times an object's own scale counts as the scale "
                             "of what it sits on")
    parser.add_argument("--split", type=int, default=None,
                        help="re-cluster only this class id, leaving the others alone")
    parser.add_argument("--into", type=int, default=2, help="how many parts to split into")
    parser.add_argument("--method", choices=["graph", "kmeans"], default="kmeans",
                        help="graph merges the most alike first and finds its own "
                             "number of classes; kmeans is the old fixed-k cut that "
                             "put identical neighbouring instances in different classes")
    parser.add_argument("--neighbours", type=int, default=12,
                        help="mutual nearest neighbours in feature space")
    parser.add_argument("--strength", type=float, default=4.0,
                        help="how much spread one class tolerates; larger merges more")
    parser.add_argument("--enforce-twins", action="store_true", default=True,
                        help="pull near-identical touching objects onto one class")
    parser.add_argument("--no-enforce-twins", dest="enforce_twins",
                        action="store_false")
    parser.add_argument("--twin-tolerance", type=float, default=0.35,
                        help="how alike two touching objects must be to count as twins")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--views", default="iso,front")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    index = np.load(os.path.join(args.session, "scale_space.npz"))
    objects = np.load(os.path.join(args.session, args.objects))
    faces, areas = session["faces"], session["areas"]
    total = float(areas.sum())

    rows = object_rows(session, index, objects, args.parent_ratio)
    under = hidden_underside(session)
    count = int(objects.max()) + 1
    share_under = np.array([under[objects == n].mean() if (objects == n).any() else 0.0
                            for n in range(count)])
    buried = share_under > 0.5
    live = ~buried

    existing = os.path.join(args.session, "object_classes.npy")
    if args.split is not None and os.path.exists(existing):
        labels = np.load(existing)
        target = np.flatnonzero((labels == args.split) & live)
        if len(target) < args.into:
            raise SystemExit("object_classes: class %d has too few objects to split"
                             % args.split)
        sub, _c = cluster(standardise(rows, target)[target], args.into, seed=args.seed)
        nxt = int(labels.max()) + 1
        for part in range(1, args.into):
            labels[target[sub == part]] = nxt + part - 1
        print("split class %d into %d; classes now %d"
              % (args.split, args.into, labels.max() + 1))
    else:
        labels = np.full(count, -1, dtype=np.int32)
        alive = np.flatnonzero(live)
        space = standardise(rows, alive)[alive]
        if args.method == "graph":
            assignment = graph_classes(space, areas, args.neighbours, args.strength)
        else:
            assignment, _c = cluster(space, args.classes, seed=args.seed)
        if args.enforce_twins:
            left, right = objects[session["pairs"][:, 0]], objects[session["pairs"][:, 1]]
            crossing = left != right
            slot = {int(v): i for i, v in enumerate(alive)}
            touching = {(slot[int(x)], slot[int(y)])
                        for x, y in zip(left[crossing], right[crossing])
                        if int(x) in slot and int(y) in slot}
            per_object = np.array([areas[objects == v].sum() for v in alive])
            before = assignment.copy()
            assignment = enforce_twins(assignment, space, touching, per_object,
                                       args.twin_tolerance)
            print("  twin repair moved %d of %d objects"
                  % (int((before != assignment).sum()), len(assignment)))
        labels[alive] = assignment
        labels[buried] = int(assignment.max()) + 1
        print("%d objects -> %d classes plus the hidden underside (%s)"
              % (count, int(assignment.max()) + 1, args.method))

    np.save(existing, labels)
    face_class = labels[objects]
    np.save(os.path.join(args.session, "object_class_of_face.npy"), face_class)

    report = []
    for klass in sorted(set(int(v) for v in labels)):
        mask = face_class == klass
        if not mask.any():
            continue
        members = labels == klass
        report.append({"class": int(klass), "area": round(float(areas[mask].sum() / total), 5),
                       "objects": int(members.sum()),
                       "size_mm": round(float(np.exp(np.median(rows[members, 0]))), 2),
                       "relief": round(float(np.median(rows[members, 1])), 4),
                       "elevation": round(float(np.median(rows[members, 3])), 4),
                       "hidden": bool(share_under[members].mean() > 0.5)})
    report.sort(key=lambda r: -r["area"])
    with open(os.path.join(args.session, "object_classes.json"), "w") as handle:
        json.dump({"features": FEATURES, "classes": report}, handle, indent=2)
    for r in report:
        stands = "proud" if r["elevation"] > 0.02 else ("recessed" if r["elevation"] < -0.02
                                                        else "flush")
        print("  class-%-2d %6.2f%%  %4d obj  ~%6.2fmm  %-8s%s"
              % (r["class"], 100 * r["area"], r["objects"], r["size_mm"], stands,
                 "  HIDDEN" if r["hidden"] else ""))

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = PALETTE[np.maximum(face_class, 0) % len(PALETTE)]
    colours[face_class < 0] = (1.0, 0.0, 1.0)
    out = os.path.join(args.session, "objectclasses")
    os.makedirs(out, exist_ok=True)
    for view in args.views.split(","):
        if view.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()], 900)
            raster.save_png(os.path.join(out, "classes-%s.png" % view.strip()), image)
    print("  %s/classes-*.png" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
