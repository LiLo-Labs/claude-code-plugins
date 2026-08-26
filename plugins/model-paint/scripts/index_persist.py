"""Objects that choose their own scale, by how long they survive being merged.

The hierarchy so far needs its levels handed to it -- k=15, 21, 60 -- and those numbers
were picked by eye. That is the same defect as picking one segmentation rung, one level
up: a barnacle cup, the colony it belongs to and the shell they sit on are objects at
three different sizes, and no single choice of level holds all three. Worse, a level
chosen for one model means nothing on the next.

So do not choose levels. Merge everything, from the weakest border to the strongest,
and record the whole tree. Every possible region on this surface appears somewhere in
it. What separates a real object from an artefact of where the merge happened to be cut
is PERSISTENCE: a barnacle cup forms early, when its rim joins its throat, and survives
a long way up the tree before the colony absorbs it, because nothing around it is as
similar to it as its own parts are. A meaningless intermediate -- half a cup plus a
sliver of shell -- is born and absorbed almost immediately.

Persistence is measured in log of border strength, because these strengths are
multiplicative in the same way the radii of the scale index are: the interesting fact
about a cup is that it survives a doubling of the merge threshold, not that it survives
0.4 of one.

Selecting from the tree is then the classic problem of choosing an antichain -- a set of
nodes with no ancestor among them, so the result is a partition rather than a pile of
overlapping claims. It is solved exactly, bottom up: a node is either taken whole, or
replaced by the best selection among its children, whichever scores higher. Score is
persistence weighted by area, so a large object must be stable over a long interval to
beat its own parts, and a tiny flake must be very stable indeed to be worth naming.

What comes back is objects at MIXED scales in one partition -- the shell body chosen
high in the tree, individual cups chosen low, each because that is where it is most
itself -- plus, for every chosen object, the children it was made from, which are its
sub-parts.

    index_persist.py --session work/
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from index_regions import edge_weights, felzenszwalb                 # noqa: E402


def merge_tree(pairs, weights, count, sizes):
    """Agglomerate in border-strength order; return the tree with birth/death weights.

    Node ids below `count` are the leaves. Each merge creates a new node recording the
    border strength that joined it, which is the death of its two children.
    """
    parent = np.arange(count)
    node_of = np.arange(count)
    total = 2 * count - 1
    children = np.full((total, 2), -1, dtype=np.int64)
    birth = np.zeros(total)
    death = np.full(total, np.inf)
    area = np.zeros(total)
    area[:count] = sizes
    next_node = count

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for edge in np.argsort(weights, kind="stable"):
        a, b = find(pairs[edge, 0]), find(pairs[edge, 1])
        if a == b:
            continue
        w = float(weights[edge])
        left, right = node_of[a], node_of[b]
        children[next_node] = (left, right)
        birth[next_node] = w
        death[left] = death[right] = w
        area[next_node] = area[left] + area[right]
        parent[b] = a
        node_of[a] = next_node
        next_node += 1
        if next_node >= total:
            break
    return children, birth, death, area, next_node


def select(children, birth, death, area, root_count, floor, ceiling):
    """Best antichain by area-weighted persistence, solved bottom up.

    Nothing here is a constant. `floor` is the weakest border actually present and
    `ceiling` the strongest, both read off this model, so persistence is measured
    against the range of borders this surface happens to have rather than against a
    number that would mean something different on the next model.

    The root is never selectable. It survives to the top by definition -- there is
    nothing left to absorb it -- so any persistence assigned to it is an artefact of
    the tree ending, and giving it one makes it beat every real object and return the
    whole model as a single part. That is exactly what a hardcoded root lifetime did
    here on the first run: one object, 100% of the surface.
    """
    total = len(birth)
    score = np.zeros(total)
    take = np.zeros(total, dtype=bool)
    root = root_count - 1
    for node in range(total):
        if area[node] <= 0:
            continue
        start = max(float(birth[node]), floor)
        end = float(death[node]) if np.isfinite(death[node]) else ceiling
        own = float(np.log(max(end, start * (1.0 + 1e-9)) / start) * area[node])
        left, right = children[node]
        below = 0.0 if left < 0 else score[left] + score[right]
        if left < 0:
            score[node], take[node] = own, True
        elif node == root or below > own:
            score[node] = below
        else:
            score[node], take[node] = own, True
    chosen = []

    def walk(node):
        if take[node] or children[node][0] < 0:
            chosen.append(node)
            return
        walk(children[node][0])
        walk(children[node][1])

    sys.setrecursionlimit(1 << 20)
    walk(root_count - 1)
    return chosen


def leaves_of(children, node, count, out):
    stack = [node]
    while stack:
        current = stack.pop()
        if current < count:
            out.append(current)
        else:
            stack.extend(children[current])


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--base-k", type=float, default=15.0,
                        help="k for the leaf regions the tree is built over")
    parser.add_argument("--min-faces", type=int, default=60)
    parser.add_argument("--camera-weight", type=float, default=2.0)
    parser.add_argument("--views", default="iso")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    index = np.load(os.path.join(args.session, "scale_space.npz"))
    evidence_path = os.path.join(args.session, "view_evidence.npz")
    evidence = np.load(evidence_path) if (args.camera_weight > 0
                                          and os.path.exists(evidence_path)) else None
    weights = edge_weights(session, index, evidence, args.camera_weight)
    faces, areas, pairs = session["faces"], session["areas"], session["pairs"]

    base = felzenszwalb(pairs, weights, len(faces), args.base_k, args.min_faces)
    count = int(base.max()) + 1
    print("%d leaf regions" % count)

    left, right = base[pairs[:, 0]], base[pairs[:, 1]]
    crossing = left != right
    key = np.minimum(left[crossing], right[crossing]).astype(np.int64) * count \
        + np.maximum(left[crossing], right[crossing]).astype(np.int64)
    unique, inverse = np.unique(key, return_inverse=True)
    totals = np.bincount(inverse, weights=weights[crossing])
    seen = np.bincount(inverse)
    region_pairs = np.stack([unique // count, unique % count], axis=1).astype(np.int64)
    region_weights = totals / np.maximum(seen, 1)
    region_area = np.bincount(base, weights=areas, minlength=count)

    # A leaf is not born at zero. It was itself built by merging faces, and the weight
    # at which it would have formed is its own internal variation -- the strongest
    # border already inside it. Defaulting leaves to the global floor instead made
    # every leaf look immortal (log of death over an almost-zero birth) and the
    # selection returned 1,776 objects of one leaf each. This is FH's own Int(C),
    # read off the same weights the tree is built from.
    inside = base[pairs[:, 0]] == base[pairs[:, 1]]
    leaf_birth = np.zeros(count)
    np.maximum.at(leaf_birth, base[pairs[inside, 0]], weights[inside])

    children, birth, death, area, used = merge_tree(region_pairs, region_weights,
                                                    count, region_area)
    birth[:count] = leaf_birth
    live = region_weights[region_weights > 0]
    floor = float(live.min()) if len(live) else 1e-6
    ceiling = float(region_weights.max())
    chosen = select(children, birth, death, area, used, floor, ceiling)
    print("merge tree: %d nodes; selected %d objects at mixed scales"
          % (used, len(chosen)))

    label = np.full(len(faces), -1, dtype=np.int32)
    records = []
    total_area = float(areas.sum())
    for slot, node in enumerate(chosen):
        members = []
        leaves_of(children, node, count, members)
        mask = np.isin(base, members)
        label[mask] = slot
        kids = children[node]
        records.append({"object": slot, "node": int(node),
                        "area": round(float(areas[mask].sum() / total_area), 5),
                        "leaves": len(members),
                        "born": round(float(birth[node]), 4),
                        "died": (None if not np.isfinite(death[node])
                                 else round(float(death[node]), 4)),
                        "subparts": 0 if kids[0] < 0 else 2})
    records.sort(key=lambda r: -r["area"])
    with open(os.path.join(args.session, "index_objects.json"), "w") as handle:
        json.dump({"objects": records}, handle, indent=2)
    np.save(os.path.join(args.session, "index_objects.npy"), label)

    spread = np.array([r["area"] for r in records])
    print("  area: largest %.2f%%, median %.3f%%, %d objects hold half the surface"
          % (100 * spread.max(), 100 * np.median(spread),
             int(np.searchsorted(np.cumsum(spread), 0.5) + 1)))
    print("  leaves per object: median %d, max %d"
          % (int(np.median([r["leaves"] for r in records])),
             max(r["leaves"] for r in records)))

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    rng = np.random.default_rng(3)
    palette = rng.uniform(0.15, 0.95, size=(max(len(chosen), 1), 3))
    colours = np.where((label >= 0)[:, None], palette[np.maximum(label, 0)], 0.9)
    out = os.path.join(args.session, "objects")
    os.makedirs(out, exist_ok=True)
    for view in args.views.split(","):
        if view.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()], 900)
            raster.save_png(os.path.join(out, "objects-%s.png" % view.strip()), image)
    print("  %s/objects-*.png" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
