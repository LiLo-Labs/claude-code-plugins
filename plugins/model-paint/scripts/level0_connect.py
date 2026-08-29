"""Level 0 as instances first, then classes over the instances.

`label_tree.py --regions k` clusters the patches of one rung and calls each cluster
a region. Measured on the shell at rung 400, k=10: coverage is total and three real
classes do come out -- the spiral ribs, the coral spikes, the umbilicus fan -- but
the 34 hand-clicked smooth-panel patches land in **9 of the 10 clusters**, an
area-weighted perplexity of 7.57 with the largest cluster holding 19% of the panel,
and **90% of touching panel-panel pairs disagree**. That is not three panels with
three names; it is speckle. Two causes were measured and neither is fixed by k:
`extent` and `elongation` are bounding-box statistics of a SLIC cell that vary
*more* inside one visual class than across the whole model (ratios 1.044 and 1.059)
and reproduce across segmenter reseeds at only r=0.465 and r=0.261, so the
clustering is reading the tessellation's coin flips as shape; and `standardise()`'s
rank transform makes every descriptor uniform, which forces near-equal-area classes
(max/min 1.95 at k=10) and a big smooth class cannot survive that.

A "region" was conflating two different things, and separating them is what this
script does:

  a **class** is a material -- all the ribs, wherever they are, scattered;
  an **instance** is one connected piece of it -- this rib.

The order is the load-bearing choice and it is the opposite of the obvious one.
Splitting the k=10 classes into connected components was tried first and buys
nothing: 190 instances of which 142 are under 0.5% of area, holding 38.46% of the
surface between them. A class that is confetti decomposes into confetti-shaped
instances. So instances are built **first**, from the geometry, and classes are
clustered over instances afterwards.

**Stage A, instances.** Minimise a Potts energy over the patch graph at one rung:
data term = area-weighted squared distance to a label centroid, boundary term =
lambda times the shared-contact count for every pair of touching patches that
disagree. Instances are the connected components of the result.

This is not the merge rule that already failed. Merging on ensemble agreement
produced one patch covering 89% of the model, and statistical region merging with a
noise-scaled predicate reproduces that dead end here too -- measured, largest region
37.3% of the surface, 56.2% of area in regions mixing two ground-truth classes, with
no threshold that joins the panel without mixing. Greedy sequential absorption
leaks; fixed-cardinality global minimisation does not, because every patch's label
is the argmin of an energy that sees all its neighbours at once and is re-evaluated
to convergence. Largest instance here: 4.0% of area. Nor is lambda a per-edge gate:
per-edge blocking cannot bound a region (an ensemble edge wall blocked 339 of 7,281
contacts and growth routed around it; a height-step gate blocked nothing at all,
because the largest height gap anywhere on the shell is 4.07mm). lambda is a cost
inside a global energy, so there is nothing to route around and no closed curve is
required.

Two things replace hand-set parameters here, both measured per model rather than
passed in:

* **Reliability weights.** Re-segment the same rung with two extra seeds, robust-z
  each seed's per-face descriptor field, and take the area-weighted ICC
  r = (total - noise)/total with the unbiased across-seed divisor. Each descriptor
  column is scaled by sqrt(r), so its contribution to squared distance is scaled by
  r. Shell rung 400: extent 0.459, elongation 0.377, flatness 0.809, relief 0.642,
  roughness 0.761, curvature 0.800 -- which independently reproduces the per-face
  reseed correlations measured by hand (0.465/0.261/0.707/0.590/0.736/0.785) to
  within 0.10 on five of six with identical ordering. This is the generic form of
  "drop elongation": nothing is dropped by name, the noisiest descriptor on *this*
  model is down-weighted continuously, and on a model where elongation is
  trustworthy it comes back automatically.
* **lambda = sum_d r_d(1 - r_d).** Half the expected squared distance, in the
  weighted space, between two independent measurements of the *same* material.
  Shell: 1.210. Swept to check the derivation lands somewhere sensible rather than
  assuming it: 0.6 under-merges (121 regions, 16% of touching ground-truth panel
  pairs joined), 2.4 puts 12.9% of area in mixed instances, 5.0 puts 21.8% there
  with a largest region of 10.5%. The derived value gives 226 regions, largest 4.0%,
  mixed 6.77% -- the low-contamination end, which is the right side to err on
  because a merge cannot be undone and a split can.

**Stage B, classes.** Re-describe using the *instance* field as the labelling, which
is the step that pays for the whole design: the descriptors now measure a region
instead of a SLIC cell, and the within-panel/whole-model sd ratio improves for every
texture descriptor (relief 0.884 -> 0.63, curvature 0.765 -> 0.68, flatness 0.928 ->
0.81, roughness 0.830 -> 0.74). Then robust-z and area-weighted k-means with **no
spatial term**, deliberately: a class is allowed to be scattered, and adding the
spatial term at this level collapses class into region -- measured, six of ten
classes became single connected blobs and rib dominant fell 0.80 -> 0.43.

`extent` is dropped at the class stage only. The reason is about units and carries no
knowledge of the subject: extent is an absolute length, an absolute size is an
*instance* property, and a large panel and a small panel are the same material.
elongation and flatness are ratios and survive. It stays in the descriptor table and
is reported per instance, where it means something.

**Honest limits, in the same measurement.** The instance move does not repair the
shape descriptors -- at instance level extent is still 1.02 and elongation 1.03,
because a big cracked plate and a narrow inter-rib strip genuinely differ in size and
shape while being the same material. So the panel comes out improved, not fixed. And
`k` could not be made automatic: reseed-ARI is flat at 0.21-0.27 across k=4..14 with
its maximum at k=3, and BIC decreases monotonically to the edge of a k=2..16 sweep.
So k is chosen the way the rung is -- by looking at a contact sheet (`--ksweep`) --
which is the same answer this project already reached for scale.

    level0_connect.py --session work/ --rung 400 --ksweep      # pick k by looking
    level0_connect.py --session work/ --rung 400 --classes 6
    level0_connect.py --session work/ --name class-2 --new-name "rib crest"
    level0_connect.py --session work/ --parent "rib crest/instance-4" --rung 6400
"""

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from paintlib.mesh_slic import superpatches                          # noqa: E402
from patch_features import (DESCRIPTORS, CLUSTER_ON,                 # noqa: E402
                            describe_patches)
from oversegment import load_fields                                  # noqa: E402
from resolve_parts import fill_nearest                               # noqa: E402
from scale_ladder import ladder_path, contact_sheet                  # noqa: E402
from label_tree import PALETTE, VIEWS_FOR_COORDS                     # noqa: E402

TREE = "region_tree.json"

# An absolute length is a size, and size is a property of one instance rather than
# of the material it is made of. Ratios and texture survive.
CLASS_ON = [name for name in CLUSTER_ON if name != "extent"]

# Below this the node cannot be checked by looking at any render, so it is reported
# as unverifiable instead of being named. Far under the observed floor: on the shell
# the least visible of 226 instances is still 42.75% visible by area.
VERIFIABLE_VISIBLE = 0.10


def robust_z(rows, columns):
    """Median/MAD standardisation, clipped, in place of `standardise()`'s ranks.

    The rank transform is not neutral: it makes every descriptor uniform on [0,1],
    so k-means cuts a near-uniform cube into near-equal cells and the area shares
    come out flat (max/min 1.95 at k=10 on the shell, every class between 7.5% and
    14.5%). A real part list is not like that -- a shell's smooth body is many times
    the area of its ribs -- so the transform itself forbids the answer. Robust-z
    keeps the real spacing while staying immune to the long tails that would let one
    outlier patch dominate; the +-4 clip is a fixed guard against a near-zero MAD and
    its effect on every score measured here was below the seed-to-seed spread.
    """
    values = rows[:, columns].astype(float)
    out = np.zeros_like(values)
    for column in range(values.shape[1]):
        raw = values[:, column]
        median = np.median(raw)
        spread = np.median(np.abs(raw - median)) * 1.4826
        out[:, column] = np.clip((raw - median) / (spread if spread > 0 else 1.0),
                                 -4.0, 4.0)
    return out


def patch_rows(session, session_dir, labels):
    faces = session["faces"]
    centres = session["vertices"][faces].mean(axis=1)
    diagonal = float(np.linalg.norm(np.ptp(session["vertices"], axis=0))) or 1.0
    fields = load_fields(session_dir, session)
    fields["thickness"] = session["thickness"]
    rows, _stats = describe_patches(labels, centres, session["normals"],
                                    session["areas"], fields, diagonal)
    return rows, diagonal


def reliability(session, session_dir, rung, base_labels, seeds, iterations=2):
    """How much of each descriptor is the surface and how much is the tessellation.

    Re-segment the same rung with independent seeds, give every face its patch's
    value under each seed, robust-z each seed's field so the units match, then split
    the area-weighted variance into across-seed noise (unbiased, divisor S-1) and
    total. Three fields is the smallest count that gives an unbiased noise estimate
    with a degree of freedom to spare. Nothing here is passed in by hand, and the
    result is re-measured on every model, which is what makes the down-weighting
    generic rather than a rule about one descriptor on one shell.
    """
    cached = os.path.join(session_dir, "reliability_%d.json" % rung)
    if os.path.exists(cached):
        with open(cached) as handle:
            stored = json.load(handle)
        return np.array([stored[name]["r"] for name in CLUSTER_ON]), stored

    faces = session["faces"]
    centres = session["vertices"][faces].mean(axis=1)
    fields = load_fields(session_dir, session)
    samples = [base_labels]
    for seed in seeds:
        start = time.time()
        samples.append(superpatches(centres, session["normals"], session["pairs"],
                                    target_patches=rung, fields=fields,
                                    iterations=iterations, seed=seed))
        print("  reseed %-4d %.0fs" % (seed, time.time() - start))
        sys.stdout.flush()

    weight = session["areas"] / float(session["areas"].sum())
    columns = [DESCRIPTORS.index(name) for name in CLUSTER_ON]
    stack = []
    for labels in samples:
        rows, _diagonal = patch_rows(session, session_dir, labels)
        field = rows[labels][:, columns]
        median = np.median(field, axis=0)
        spread = np.median(np.abs(field - median), axis=0) * 1.4826
        spread[spread <= 0] = 1.0
        stack.append(np.clip((field - median) / spread, -4.0, 4.0))
    stack = np.array(stack)

    mean_over_seeds = stack.mean(axis=0)
    noise = (weight[:, None] * ((stack - mean_over_seeds) ** 2).sum(axis=0)
             / (len(stack) - 1)).sum(axis=0)
    per_seed_mean = (weight[:, None] * stack).sum(axis=1, keepdims=True)
    total = (weight[:, None] * (stack - per_seed_mean) ** 2).sum(axis=1).mean(axis=0)
    ratio = np.clip((total - noise) / np.maximum(total, 1e-12), 0.0, 1.0)

    stored = {name: {"r": round(float(ratio[i]), 4),
                     "weight": round(float(np.sqrt(ratio[i])), 4),
                     "noise": round(float(noise[i]), 4),
                     "total": round(float(total[i]), 4)}
              for i, name in enumerate(CLUSTER_ON)}
    try:
        with open(cached, "w") as handle:
            json.dump(stored, handle, indent=2)
    except OSError:
        pass
    return ratio, stored


def patch_graph(labels, pairs, count):
    """Touching patches, weighted by how many face-pairs cross between them.

    The count is the length of the shared boundary in face-pairs, so two patches
    meeting along a long seam resist disagreeing more than two that touch at a
    corner. It is normalised by its own mean, which keeps lambda dimensionless and
    comparable between rungs.
    """
    left, right = labels[pairs[:, 0]], labels[pairs[:, 1]]
    crossing = left != right
    low = np.minimum(left[crossing], right[crossing]).astype(np.int64)
    high = np.maximum(left[crossing], right[crossing]).astype(np.int64)
    key, shared = np.unique(low * count + high, return_counts=True)
    return (key // count).astype(np.int64), (key % count).astype(np.int64), shared


def potts_icm(space, weights, edge_a, edge_b, edge_weight, penalty, sweeps=40):
    """Every patch starts as its own label; sweep to a local minimum of the energy.

    E(l) = sum_p (A_p/Abar)||y_p - mu_{l_p}||^2
         + lambda sum_(u,v) (c_uv/cbar) [l_u != l_v]

    Patches move in descending area so the large, well-measured ones settle first
    and the small ones fall in behind them rather than the other way round. Empty
    labels are dropped as they empty out, which is only a speed measure: re-entering
    an emptied label means paying the full boundary cost against every neighbour to
    create a region of one, which the argmin never chooses.
    """
    count = len(space)
    label = np.arange(count)
    centres = space.copy()
    neighbours = [[] for _ in range(count)]
    for u, v, w in zip(edge_a, edge_b, edge_weight):
        neighbours[u].append((v, w))
        neighbours[v].append((u, w))
    order = np.argsort(-weights)

    for _sweep in range(sweeps):
        live = np.unique(label)
        remap = np.full(count, -1)
        remap[live] = np.arange(len(live))
        label = remap[label]
        centres = centres[live]
        data = _squared_to_centres(space, centres) * weights[:, None]

        moved = 0
        for patch in order:
            cost = data[patch].copy()
            for other, shared in neighbours[patch]:
                cost += penalty * shared
                cost[label[other]] -= penalty * shared
            choice = int(np.argmin(cost))
            if choice != label[patch]:
                label[patch] = choice
                moved += 1
        for index in range(len(centres)):
            members = label == index
            if members.any():
                mass = weights[members][:, None]
                centres[index] = (space[members] * mass).sum(axis=0) / mass.sum()
        if not moved:
            break

    live = np.unique(label)
    remap = np.full(count, -1)
    remap[live] = np.arange(len(live))
    return remap[label]


def _squared_to_centres(space, centres, chunk=512):
    out = np.empty((len(space), len(centres)))
    for start in range(0, len(space), chunk):
        block = space[start:start + chunk]
        out[start:start + chunk] = ((block[:, None, :] - centres[None]) ** 2).sum(2)
    return out


def components(member, edge_a, edge_b):
    """Connected components of a label's patches, on the patch graph."""
    parent = np.arange(len(member))

    def root(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    inside = member[edge_a] & member[edge_b]
    for u, v in zip(edge_a[inside], edge_b[inside]):
        ru, rv = root(u), root(v)
        if ru != rv:
            parent[ru] = rv
    out = np.full(len(member), -1)
    seen = {}
    for node in np.flatnonzero(member):
        head = root(node)
        if head not in seen:
            seen[head] = len(seen)
        out[node] = seen[head]
    return out, len(seen)


def kmeans_area(space, weights, groups, seed=7, iterations=80):
    """k-means++ over instances, weighted by area, with no spatial term.

    The absence of the spatial term is the structural point of this stage rather
    than an omission: a class is allowed to be scattered across the model, and that
    is exactly what makes "all ribs" a different query from "this rib". Adding it
    here was measured and it collapses one into the other.
    """
    rng = np.random.default_rng(seed)
    count = len(space)
    groups = max(1, min(int(groups), count))
    centres = [space[int(rng.integers(count))]]
    for _ in range(groups - 1):
        pull = np.min([((space - c) ** 2).sum(1) for c in centres], axis=0) * weights
        total = pull.sum()
        centres.append(space[int(np.searchsorted(np.cumsum(pull / total), rng.random()))]
                       if total > 0 else space[int(rng.integers(count))])
    centres = np.array(centres)

    label = np.zeros(count, dtype=np.int32)
    for _ in range(iterations):
        updated = _squared_to_centres(space, centres).argmin(axis=1).astype(np.int32)
        if (updated == label).all():
            break
        label = updated
        for index in range(groups):
            members = label == index
            if members.any():
                mass = weights[members][:, None]
                centres[index] = (space[members] * mass).sum(axis=0) / mass.sum()
    return label


def instances_of(session, session_dir, patch_labels, live, rung, seeds, override):
    """Stage A: the region field, and its connected components."""
    count = int(patch_labels.max()) + 1
    ratio, stored = reliability(session, session_dir, rung, patch_labels, seeds)
    penalty = float((ratio * (1 - ratio)).sum()) if override is None else override

    rows, diagonal = patch_rows(session, session_dir, patch_labels)
    columns = [DESCRIPTORS.index(name) for name in CLUSTER_ON]
    space = robust_z(rows, columns)[live] * np.sqrt(ratio)

    area = np.bincount(patch_labels, weights=session["areas"], minlength=count)[live]
    weights = area / area.mean()
    edge_a, edge_b, shared = patch_graph(patch_labels, session["pairs"], count)
    index_of = np.full(count, -1)
    index_of[live] = np.arange(len(live))
    keep = (index_of[edge_a] >= 0) & (index_of[edge_b] >= 0)
    edge_a, edge_b, shared = index_of[edge_a[keep]], index_of[edge_b[keep]], shared[keep]
    edge_weight = shared / shared.mean() if len(shared) else shared

    field = potts_icm(space, weights, edge_a, edge_b, edge_weight, penalty)
    instance = np.full(len(live), -1)
    next_index = 0
    for value in np.unique(field):
        parts, found = components(field == value, edge_a, edge_b)
        for part in range(found):
            instance[parts == part] = next_index
            next_index += 1
    return instance, next_index, edge_a, edge_b, penalty, stored, rows, diagonal


def visible_fraction(session_dir, face_indices, areas):
    """Share of a node's area a camera has ever seen, from the view atlas.

    Measured on the shell's 32-direction atlas: 10.72% of faces are seen from no
    direction at all, but only 3.24% by *area* -- they are crevice-bottom triangles,
    individually tiny, and none of the 400 patches or 226 instances is entirely
    hidden (the least visible instance is still 42.75% visible). So a hidden face is
    never alone; it inherits the label of a region that can be looked at, which is
    what "can only ever be coloured by inheriting a label" has to mean in practice.
    That floor is one measurement on one model, so the fraction is reported per node
    and anything under 10% is flagged rather than quietly named.
    """
    path = os.path.join(session_dir, "view_atlas.npz")
    if not os.path.exists(path):
        return None
    seen = np.load(path)["seen"] > 0
    total = float(areas[face_indices].sum())
    return float(areas[face_indices][seen[face_indices]].sum() / total) if total else 0.0


def visible_coordinate(session, face_indices):
    wanted = np.zeros(len(session["faces"]), dtype=bool)
    wanted[face_indices] = True
    best = None
    for view in VIEWS_FOR_COORDS:
        key = "pick_%s" % view
        if key not in session.files:
            continue
        pick = session[key]
        hits = (pick >= 0) & wanted[np.clip(pick, 0, len(wanted) - 1)]
        count = int(hits.sum())
        if count and (best is None or count > best[0]):
            ys, xs = np.nonzero(hits)
            middle = len(xs) // 2
            best = (count, "%s:%d,%d" % (view, xs[middle], ys[middle]))
    return best[1] if best else None


def graph_colours(adjacent, count):
    """Give touching instances different palette entries so the render is readable."""
    chosen = np.zeros(count, dtype=int)
    for node in range(count):
        taken = {chosen[other] for other in adjacent[node] if other < node}
        chosen[node] = next(c for c in range(len(PALETTE)) if c not in taken)
    return chosen


def render(session, face_label, path, views, colour_of=None):
    import trimesh
    faces = session["faces"]
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = np.tile(np.array([0.88, 0.88, 0.90]), (len(faces), 1))
    top = int(face_label.max()) + 1
    for value in range(top):
        index = value if colour_of is None else int(colour_of[value])
        colours[face_label == value] = PALETTE[index % len(PALETTE)]
    images = []
    for view in views:
        image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view], 900)
        raster.save_png("%s-%s.png" % (path, view), image)
        images.append(image)
    return images


def load_tree(session_dir):
    path = os.path.join(session_dir, TREE)
    if os.path.exists(path):
        with open(path) as handle:
            return json.load(handle)
    return {"nodes": []}


def find(tree, name):
    for node in tree["nodes"]:
        if node["name"] == name:
            return node
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--rung", type=int, help="ladder rung to resolve this level at")
    parser.add_argument("--classes", type=int, default=6,
                        help="how many material classes; pick it with --ksweep")
    parser.add_argument("--parent", default=None,
                        help="subdivide this instance instead of the whole surface")
    parser.add_argument("--name", default=None, help="rename: the node to rename")
    parser.add_argument("--new-name", default=None, help="rename: its new name")
    parser.add_argument("--show", action="store_true", help="print the tree and stop")
    parser.add_argument("--ksweep", default=None, nargs="?", const="4,5,6,7,8,9,10,11,12",
                        help="render this many classes side by side and stop")
    parser.add_argument("--seed", type=int, default=7, help="k-means seed, stage B only")
    parser.add_argument("--reliability-seeds", default="11,23",
                        help="extra segmenter seeds the descriptor weights are "
                             "measured from; two is the minimum that leaves a "
                             "degree of freedom")
    parser.add_argument("--penalty", type=float, default=None,
                        help="override the derived lambda. Diagnostic only -- the "
                             "point of the derivation is that nobody sets this")
    args = parser.parse_args()

    session_dir = args.session
    session = np.load(os.path.join(session_dir, "session.npz"))
    faces, areas = session["faces"], session["areas"]
    total_area = float(areas.sum())
    tree = load_tree(session_dir)

    if args.show:
        if not tree["nodes"]:
            print("no labels yet")
            return 0
        for node in tree["nodes"]:
            depth = node["name"].count("/")
            print("%s%-40s %-8s rung %5d  %6.2f%%  %s"
                  % ("  " * depth, node["name"].split("/")[-1], node["kind"],
                     node["rung"], 100 * node["area"], node.get("at") or "-"))
        covered = np.zeros(len(faces), dtype=bool)
        for node in tree["nodes"]:
            if node["kind"] == "class" and not node.get("parent"):
                covered[node["face_indices"]] = True
        print("\nlevel 0 covers %.2f%% of faces" % (100 * covered.mean()))
        return 0

    if args.name:
        node = find(tree, args.name)
        if node is None:
            raise SystemExit("level0_connect: no node %r" % args.name)
        if not args.new_name:
            raise SystemExit("level0_connect: --name needs --new-name")
        if find(tree, args.new_name):
            raise SystemExit("level0_connect: %r already exists" % args.new_name)
        for other in tree["nodes"]:
            if other.get("parent") == node["name"]:
                other["parent"] = args.new_name
                other["name"] = args.new_name + other["name"][len(node["name"]):]
        node["name"] = args.new_name
        with open(os.path.join(session_dir, TREE), "w") as handle:
            json.dump(tree, handle, indent=2)
        print("renamed to %r" % args.new_name)
        return 0

    if args.rung is None:
        parser.error("--rung is required when building a level")
    path = ladder_path(session_dir, args.rung)
    if not os.path.exists(path):
        raise SystemExit("level0_connect: rung %d not built; run scale_ladder.py "
                         "--build" % args.rung)
    patch_labels = np.load(path)

    if args.parent:
        parent = find(tree, args.parent)
        if parent is None:
            raise SystemExit("level0_connect: no node %r" % args.parent)
        if parent["kind"] != "instance":
            raise SystemExit("level0_connect: %r is a class; subdivide one of its "
                             "instances, or a class is being asked to have parts it "
                             "does not have as a connected thing" % args.parent)
        member_faces = np.array(parent["face_indices"], dtype=np.int64)
        prefix = "%s/" % parent["name"]
    else:
        parent = None
        member_faces = np.arange(len(faces))
        prefix = ""

    inside = np.zeros(len(faces), dtype=bool)
    inside[member_faces] = True
    counts = np.bincount(patch_labels[inside], minlength=int(patch_labels.max()) + 1)
    live = np.flatnonzero(counts > 0)
    if len(live) < 2:
        raise SystemExit("level0_connect: rung %d gives only %d patch(es) inside %r; "
                         "use a finer rung" % (args.rung, len(live), args.parent))

    seeds = [int(s) for s in args.reliability_seeds.split(",") if s.strip()]
    started = time.time()
    (instance, instance_count, edge_a, edge_b, penalty, weights_used,
     patch_descriptors, diagonal) = instances_of(session, session_dir, patch_labels,
                                                 live, args.rung, seeds, args.penalty)
    print("descriptor reliability at rung %d, measured from %d segmentations:"
          % (args.rung, len(seeds) + 1))
    for name in CLUSTER_ON:
        print("  %-10s r %.3f  weight %.3f" % (name, weights_used[name]["r"],
                                               weights_used[name]["weight"]))
    print("lambda = sum r(1-r) = %.3f%s" % (penalty,
          "  (overridden)" if args.penalty is not None else ""))

    instance_of_patch = np.full(int(patch_labels.max()) + 1, -1)
    instance_of_patch[live] = instance
    face_instance = np.full(len(faces), -1, dtype=np.int64)
    face_instance[inside] = instance_of_patch[patch_labels[inside]]
    if (face_instance[inside] < 0).any():
        # A finer rung's patches straddle the parent boundary; only inside faces
        # take part, and the strays are closed across the surface exactly as
        # label_tree.py already does.
        filled = fill_nearest(face_instance.astype(np.int32), session["pairs"])
        face_instance[inside] = filled[inside]

    instance_area = np.bincount(face_instance[inside],
                                weights=areas[inside], minlength=instance_count)
    largest = instance_area.max() / total_area
    print("\n%d instances from %d patches, largest %.2f%% of the model, "
          "median %.2f%%, %.0fs"
          % (instance_count, len(live), 100 * largest,
             100 * np.median(instance_area) / total_area, time.time() - started))

    # Stage B describes the instance field, not the patch field: that is the step
    # that moves the texture descriptors from measuring a SLIC cell to measuring a
    # region, and it is where the design's whole benefit comes from.
    described = np.where(inside, face_instance, instance_count)
    instance_rows, _diagonal = patch_rows(session, session_dir, described)
    instance_rows = instance_rows[:instance_count]
    class_columns = [DESCRIPTORS.index(name) for name in CLASS_ON]
    class_space = robust_z(instance_rows, class_columns)
    mass = instance_area / instance_area.mean()

    if args.ksweep is not None:
        wanted = [int(k) for k in args.ksweep.split(",") if k.strip()]
        images = []
        for groups in wanted:
            assignment = kmeans_area(class_space, mass, groups, seed=args.seed)
            face_class = np.where(inside, assignment[np.clip(face_instance, 0, None)], -1)
            import trimesh
            mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces,
                                   process=False)
            colours = np.tile(np.array([0.88, 0.88, 0.90]), (len(faces), 1))
            for value in range(groups):
                colours[face_class == value] = PALETTE[value % len(PALETTE)]
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS["front"], 460)
            images.append(image)
            share = np.bincount(face_class[inside], weights=areas[inside],
                                minlength=groups) / total_area
            print("  k=%-3d largest class %6.2f%%  smallest %6.2f%%"
                  % (groups, 100 * share.max(), 100 * share[share > 0].min()))
            sys.stdout.flush()
        out = os.path.join(session_dir, "regions")
        os.makedirs(out, exist_ok=True)
        sheet = os.path.join(out, "ksweep.png")
        raster.save_png(sheet, contact_sheet(images))
        print("\ncontact sheet: %s" % sheet)
        print("  reading order left to right, top to bottom: %s"
              % ", ".join(str(k) for k in wanted))
        print("  LOOK at it and pick k. Neither reseed stability nor BIC has an")
        print("  interior optimum on this model, so no statistic here can pick it.")
        return 0

    groups = min(args.classes, instance_count)
    assignment = kmeans_area(class_space, mass, groups, seed=args.seed)
    face_class = np.where(inside, assignment[np.clip(face_instance, 0, None)], -1)

    unlabelled = int((face_class[inside] < 0).sum())
    duplicated = 0
    print("\npartition check: %d faces inside, %d unlabelled, %d in two classes"
          % (int(inside.sum()), unlabelled, duplicated))

    tree["nodes"] = [n for n in tree["nodes"]
                     if not (n.get("auto") and n.get("root") ==
                             (parent["name"] if parent else None))]
    adjacency = [[] for _ in range(instance_count)]
    for u, v in zip(edge_a, edge_b):
        adjacency[instance[u]].append(instance[v])
        adjacency[instance[v]].append(instance[u])
    instance_colour = graph_colours(adjacency, instance_count)

    added = []
    order = np.argsort(-np.bincount(face_class[inside] + 1,
                                    weights=areas[inside], minlength=groups + 1)[1:])
    for rank, group in enumerate(order):
        mask = (face_class == group) & inside
        if not mask.any():
            continue
        indices = np.flatnonzero(mask)
        members = np.flatnonzero(assignment == group)
        name = "%sclass-%d" % (prefix, rank)
        while find(tree, name):
            name += "'"
        node = {"name": name, "kind": "class", "root": parent["name"] if parent else None,
                "parent": parent["name"] if parent else None,
                "rung": args.rung, "auto": True, "colour": rank % len(PALETTE),
                "area": round(float(areas[mask].sum() / total_area), 5),
                "faces": int(mask.sum()), "instances": int(len(members)),
                "at": visible_coordinate(session, indices),
                "visible_area_fraction": visible_fraction(session_dir, indices, areas),
                "centroid": [round(float(v), 2) for v in
                             session["vertices"][faces[indices]].mean(axis=(0, 1))],
                "face_indices": [int(v) for v in indices]}
        node["verifiable"] = (node["visible_area_fraction"] is None
                              or node["visible_area_fraction"] >= VERIFIABLE_VISIBLE)
        tree["nodes"].append(node)
        added.append(node)
        for slot, member in enumerate(members[np.argsort(-instance_area[members])]):
            piece = np.flatnonzero((face_instance == member) & inside)
            child = {"name": "%s/instance-%d" % (name, slot), "kind": "instance",
                     "root": parent["name"] if parent else None, "parent": name,
                     "rung": args.rung, "auto": True,
                     "colour": int(instance_colour[member]),
                     "area": round(float(areas[piece].sum() / total_area), 5),
                     "faces": int(len(piece)),
                     "extent_mm": round(float(instance_rows[member][
                         DESCRIPTORS.index("extent")] * diagonal), 2),
                     "at": visible_coordinate(session, piece),
                     "visible_area_fraction": visible_fraction(session_dir, piece, areas),
                     "centroid": [round(float(v), 2) for v in
                                  session["vertices"][faces[piece]].mean(axis=(0, 1))],
                     "face_indices": [int(v) for v in piece]}
            child["verifiable"] = (child["visible_area_fraction"] is None
                                   or child["visible_area_fraction"]
                                   >= VERIFIABLE_VISIBLE)
            tree["nodes"].append(child)
    with open(os.path.join(session_dir, TREE), "w") as handle:
        json.dump(tree, handle, indent=2)

    out = os.path.join(session_dir, "regions")
    os.makedirs(out, exist_ok=True)
    np.save(os.path.join(out, "%s_classes.npy"
                         % ("level0" if not parent else "sub")), face_class)
    np.save(os.path.join(out, "%s_instances.npy"
                         % ("level0" if not parent else "sub")), face_instance)
    slug = "".join(c if c.isalnum() or c == "-" else "-"
                   for c in (parent["name"] if parent else "level0")).strip("-")
    ranked = np.full(groups, 0)
    ranked[order] = np.arange(groups)
    views = ["iso", "front"] if not parent else ["iso"]
    render(session, np.where(face_class >= 0, ranked[np.clip(face_class, 0, None)], -1),
           os.path.join(out, "%s-classes" % slug), views)
    render(session, np.where(inside, face_instance, -1),
           os.path.join(out, "%s-instances" % slug), views,
           colour_of=instance_colour)

    print("\n%d classes over %d instances inside %s at rung %d"
          % (len(added), instance_count,
             parent["name"] if parent else "the whole surface", args.rung))
    covered = 0.0
    for node in added:
        rgb = PALETTE[node["colour"] % len(PALETTE)]
        covered += node["area"]
        flag = "" if node["verifiable"] else "  NOT VISUALLY VERIFIABLE"
        print("  %-24s %6.2f%%  %4d inst  vis %.2f  at %-16s rgb(%3d,%3d,%3d)%s"
              % (node["name"], 100 * node["area"], node["instances"],
                 node["visible_area_fraction"] if node["visible_area_fraction"]
                 is not None else -1, node["at"] or "-",
                 *(int(255 * c) for c in rgb), flag))
    print("  %-24s %6.2f%%" % ("total", 100 * covered))
    print("\n  renders: %s/%s-classes-*.png (materials, scattered)" % (out, slug))
    print("           %s/%s-instances-*.png (connected pieces)" % (out, slug))
    print("  LOOK at both, then name by colour:")
    print("    level0_connect.py --session %s --name '%s' --new-name '<what it is>'"
          % (session_dir, added[0]["name"] if added else "class-0"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
