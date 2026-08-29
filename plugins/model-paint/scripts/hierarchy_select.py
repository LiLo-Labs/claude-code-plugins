"""Click a thing, walk up to the whole thing, then find every other one on the model.

A flat list of objects cannot answer "select all the barnacles". Persistence picks each
object at the scale where it is most stable, which is correct in principle and means in
practice that one cup is a single object while its neighbour is three -- a rim, a wall
and a throat. Measured across 963 objects on the shell, extent runs from 0.87mm to
94.95mm, a factor of 109. So a click lands on whatever fragment happens to be there:
pointing at a colony returned the matrix BETWEEN the cups, because the object under the
cursor was a 2mm sliver and not a cone at all.

Searching harder cannot fix that. A cone that was never assembled into one node cannot
be matched by any similarity measure, at any radius.

The merge tree already contains it. Every grouping of the surface that the border
strengths support is a node somewhere in that tree -- the rim alone, the whole cup, the
colony, the whorl. Persistence chooses ONE antichain through it; this searches the whole
thing instead.

Two moves, and they are the two a person makes with a selection tool:

**Up.** From the clicked leaf, walk the ancestor chain and report each ancestor's extent
in millimetres and its share of the surface. That is the "select more" key, and each step
is a real grouping rather than a dilation of the last one.

**Across.** Having settled on a node, find every other node in the tree that measures
like it, keeping only maximal matches so a cup and its own rim are never both returned.
This is what makes one click select every colony on the model: matching happens at
whatever level the click resolved to, so a cone matches a cone even where persistence cut
that cone into three.

    hierarchy_select.py --session work/ --at iso:441,368            # show the chain
    hierarchy_select.py --session work/ --at iso:441,368 --up 3 --radius 0.9 --name cups
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from index_regions import edge_weights, felzenszwalb                 # noqa: E402
from index_persist import merge_tree, select                         # noqa: E402
from object_classes import hidden_underside                          # noqa: E402

HIGHLIGHT = (0.95, 0.25, 0.10)
EXEMPLAR = (0.10, 0.85, 1.0)
DIMMED = (0.86, 0.86, 0.88)


def build_tree(session, index, base_k, min_faces, camera_weight, session_dir):
    """The same tree index_persist builds, and it has to be the SAME.

    This used to hardcode `edge_weights(session, index, None, 0.0)` -- geometry only,
    camera evidence ignored, whatever the caller passed. On a crease-bounded model that
    is harmless; on the shell it is fatal, because the shell's boundaries are soft
    relief that geometry alone does not see. Measured: geometry-only weights give the
    shell 1,477 leaves and a tree in which persistence finds TWO objects, one of them
    82% of the surface. With the evidence it is 1,797 leaves and 963 objects. Selection
    was being run against a tree nothing else in the pipeline uses.
    """
    evidence_path = os.path.join(session_dir, "view_evidence.npz")
    evidence = np.load(evidence_path) if (camera_weight > 0
                                          and os.path.exists(evidence_path)) else None
    weights = edge_weights(session, index, evidence, camera_weight)
    faces, areas, pairs = session["faces"], session["areas"], session["pairs"]
    base = felzenszwalb(pairs, weights, len(faces), base_k, min_faces)
    count = int(base.max()) + 1

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

    # A leaf is not born at zero; see index_persist for why. The same correction has to
    # be made here or the antichain computed below is not the one index_persist emits.
    inside = base[pairs[:, 0]] == base[pairs[:, 1]]
    leaf_birth = np.zeros(count)
    np.maximum.at(leaf_birth, base[pairs[inside, 0]], weights[inside])

    children, birth, death, area, used = merge_tree(region_pairs, region_weights,
                                                    count, region_area)
    birth[:count] = leaf_birth
    live = region_weights[region_weights > 0]
    floor = float(live.min()) if len(live) else 1e-6
    ceiling = float(region_weights.max())
    whole = select(children, birth, death, area, used, floor, ceiling)
    return base, children, area, used, count, np.asarray(whole, dtype=np.int64)


def node_leaves(children, node, count):
    out, stack = [], [node]
    while stack:
        current = stack.pop()
        if current < count:
            out.append(current)
        else:
            stack.extend(children[current])
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--at", action="append", required=True,
                        help="view:x,y -- repeat to point at several examples")
    parser.add_argument("--up", type=int, default=None,
                        help="how many steps up the tree from the clicked leaf; "
                             "omit to just print the chain")
    parser.add_argument("--radius", type=float, default=0.9,
                        help="how alike another node must be, in standard deviations")
    parser.add_argument("--name", default="selection")
    parser.add_argument("--base-k", type=float, default=15.0)
    parser.add_argument("--camera-weight", type=float, default=2.0,
                        help="weight on multi-angle boundary evidence, when a "
                             "view_evidence.npz is present; must match index_persist "
                             "or the tree searched is not the one that made the objects")
    parser.add_argument("--min-faces", type=int, default=60)
    parser.add_argument("--views", default="iso")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    index = np.load(os.path.join(args.session, "scale_space.npz"))
    faces, areas = session["faces"], session["areas"]
    total = float(areas.sum())
    corners = session["vertices"][faces]

    base, children, area, used, count, whole = build_tree(session, index, args.base_k,
                                                          args.min_faces,
                                                          args.camera_weight,
                                                          args.session)
    print("merge tree: %d leaf regions, %d nodes, %d whole objects"
          % (count, used, len(whole)))

    parent = np.full(used, -1, dtype=np.int64)
    for node in range(count, used):
        for kid in children[node]:
            if kid >= 0:
                parent[kid] = node

    # A click does not land on a feature, it lands on a LEAF -- a flank of a spike, a
    # sliver of a cup wall. Walking up from there is not enough, because a leaf's first
    # merge is often sideways into its neighbour: on the dragon the chain from a spike
    # went 0.045% (part of one spike) straight to 0.377% (about one and a half), so the
    # whole spike was never a node on that chain at all. Matching from the leaf then
    # matched flank-to-flank -- it highlighted a patch on 124 spikes and missed the
    # rest, which is exactly what the render showed.
    #
    # The whole features do exist in this tree; they are what persistence selects. So a
    # click SNAPS to the smallest selected object containing it, and the chain is walked
    # from there. The tree is still what lets a click go coarser -- spike, then row of
    # spikes, then body -- but it no longer has to start from a fragment.
    is_whole = np.zeros(used, dtype=bool)
    is_whole[whole] = True

    def snap(node):
        walk = node
        while walk >= 0:
            if is_whole[walk]:
                return int(walk)
            walk = parent[walk]
        return int(node)

    # Several exemplars, because one is never enough for a real population. A cup at
    # the crown, a cup on the reef and a cup in a crowded bed differ enough that a
    # radius wide enough to reach all three from ONE of them also reaches things that
    # are not cups. Distance is taken to the NEAREST exemplar, so pointing at three
    # describes the spread of the population instead of averaging it into a centre that
    # nothing matches.
    leaves = []
    for spec in args.at:
        try:
            view, coords = spec.split(":", 1)
            x, y = (int(v) for v in coords.split(","))
        except ValueError:
            parser.error("--at wants view:x,y, got %r" % spec)
        face = raster.region_at(None, session["pick_%s" % view], x, y)
        if face is None:
            parser.error("nothing under %s -- that pixel is background" % spec)
        leaves.append(int(base[face]))
    leaf = leaves[0]
    view = args.at[0].split(":", 1)[0]

    # Features per node, computed only for what we need: extent in mm, relief, elevation.
    signed = np.asarray(index["signed"], dtype=np.float64)
    buried = hidden_underside(session)

    radii = np.asarray(index["radii_mm"], dtype=np.float64)
    dispersion = np.asarray(index["dispersion"], dtype=np.float64)

    cache = {}
    def describe(node):
        """A SCALE-FREE signature. Nothing here is a length.

        Absolute size was a matching feature and it was the whole bug: a barnacle is a
        barnacle at 1mm or at 5mm, so putting extent in the vector guarantees that one
        population splits by size, which is exactly what happened -- cones cut across
        four classes at 1.83, 2.14, 2.50 and 3.42mm. Building a scale-invariant index and
        then matching on absolute scale throws the invariance away.

        So every number below is a ratio or a normalised shape:
          - the two aspect ratios of the object's own bounding box, sorted, which say
            whether it is a blob, a plate or a rod at any size
          - relief already divided by the object's own scale
          - how much the surface turns at radii measured in FRACTIONS of the object's
            own extent, which is the shape of its scale-space response rather than
            where that response sits on the ladder
        Two cones of different sizes give the same signature; a cone and a rib do not.
        """
        if node in cache:
            return cache[node]
        leaves = node_leaves(children, node, count)
        mask = np.isin(base, leaves)
        span = np.sort(np.ptp(corners[mask].reshape(-1, 3), axis=0))[::-1]
        extent = float(np.linalg.norm(span)) or 1e-6
        longest = max(span[0], 1e-9)
        curve = []
        for fraction in (0.25, 0.5, 1.0):
            target = np.clip(extent * fraction, radii[0], radii[-1])
            rung = int(np.argmin(np.abs(radii - target)))
            curve.append(float(np.median(dispersion[rung][mask])))
        row = np.array([span[1] / longest, span[2] / longest,
                        float(np.median(signed[mask]))] + curve)
        cache[node] = (row, mask, extent,
                       float(areas[mask].sum() / total), bool(buried[mask].mean() > 0.5))
        return cache[node]

    chain = [snap(leaf)]
    while parent[chain[-1]] >= 0:
        chain.append(int(parent[chain[-1]]))
    if chain[0] != leaf:
        print("click snapped from leaf %d to whole object %d" % (leaf, chain[0]))
    print("ancestor chain from the click (%d steps):" % (len(chain) - 1))
    for step, node in enumerate(chain[:12]):
        _row, _m, extent, share, _h = describe(node)
        print("  up %-2d  node %-6d  extent %6.2f mm  %6.3f%% of surface"
              % (step, node, extent, 100 * share))
    if args.up is None:
        print("\n  pick one with --up N, then --radius to find every other node like it")
        return 0

    # "up N" is not comparable between clicks. The tree is deeper under a crowded bed
    # than under an isolated bump, so the same N gave a 5.81mm cup at one exemplar and a
    # 19.57mm shell band at another -- and one bad exemplar drags the whole match onto
    # rock. So the FIRST click sets the size of the thing being pointed at, and every
    # other click walks to whichever of its own ancestors is closest to that size. The
    # size is used only to line the exemplars up with each other; it is not part of the
    # signature they are matched by, which stays scale-free.
    def chain_of(start):
        walk = [snap(start)]
        while parent[walk[-1]] >= 0:
            walk.append(int(parent[walk[-1]]))
        return walk

    first = chain_of(leaves[0])
    anchor = first[min(args.up, len(first) - 1)]
    wanted = describe(anchor)[2]
    targets = [anchor]
    for start in leaves[1:]:
        walk = chain_of(start)
        best = min(walk, key=lambda node: abs(np.log(max(describe(node)[2], 1e-6))
                                              - np.log(max(wanted, 1e-6))))
        targets.append(best)
    targets = sorted(set(targets))
    mask = np.zeros(len(faces), dtype=bool)
    for node in targets:
        mask |= describe(node)[1]
    print("\n%d exemplar node(s) at up %d: %s"
          % (len(targets), args.up,
             ", ".join("%.2fmm" % describe(n)[2] for n in targets)))

    # Every node in the tree, scored against the target. Maximal matches only, so a cup
    # and its own rim are never both returned.
    # Candidates are whole objects and their ancestors -- never a raw leaf. Scoring
    # every node in the tree meant a fragment could match a fragment, which is how the
    # flank-patch selection happened. Anything below a selected object is a part of one
    # and is reachable by asking for sub-parts, not by a similarity search.
    candidate = np.zeros(used, dtype=bool)
    for node in whole:
        walk = int(node)
        while walk >= 0 and not candidate[walk]:
            candidate[walk] = True
            walk = parent[walk]

    rows = np.zeros((used, 6))
    live = np.zeros(used, dtype=bool)
    for node in np.flatnonzero(candidate):
        r, m, ext, sh, hid = describe(int(node))
        rows[node] = r
        live[node] = (not hid) and sh > 0
    scale = rows[live].std(axis=0)
    scale[scale <= 0] = 1.0
    distance = np.min([np.linalg.norm((rows - rows[node]) / scale, axis=1)
                       for node in targets], axis=0)
    like = live & (distance <= args.radius)

    keep = []
    for node in np.flatnonzero(like):
        walk, ancestor_taken = parent[node], False
        while walk >= 0:
            if like[walk]:
                ancestor_taken = True
                break
            walk = parent[walk]
        if not ancestor_taken:
            keep.append(int(node))

    picked = np.zeros(len(faces), dtype=bool)
    for node in keep:
        picked |= describe(node)[1]
    print("  %d matching nodes (maximal), %.2f%% of the surface"
          % (len(keep), 100 * areas[picked].sum() / total))

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = np.tile(np.array(DIMMED), (len(faces), 1))
    colours[picked] = HIGHLIGHT
    colours[mask] = EXEMPLAR
    out = os.path.join(args.session, "hselect")
    os.makedirs(out, exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in args.name).strip("-").lower()
    for name in dict.fromkeys([view] + args.views.split(",")):
        if name.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[name.strip()], 900)
            raster.save_png(os.path.join(out, "%s-%s.png" % (slug, name.strip())), image)
    print("  %s/%s-*.png -- cyan is what you clicked, orange is everything like it"
          % (out, slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
