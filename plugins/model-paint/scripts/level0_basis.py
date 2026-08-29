"""Level 0 in coordinates the segmenter cannot influence.

`label_tree.py` builds level 0 by clustering the patches of one rung in the six
`CLUSTER_ON` descriptors. On the shell at rung 400 that finds real classes -- ribs,
coral tubes, barnacle clusters -- but it splits the smooth shell panels across three
clusters that are not three different things. This script keeps everything about
that except the coordinates: still one flat k-means over the patches of one rung,
still the same assignment and `fill_nearest` mechanics, still the same
`label_tree.json`. Only the space changes.

**Why the space and not the objective.** Every one of the six descriptors is an
aggregate over a SLIC cell. `extent`, `elongation` and `flatness` are literally the
cell's bounding box, and the rest are field means over the cell, so all six move
when the segmenter is re-seeded and the cell boundaries land elsewhere. Measured
across SLIC seeds 7/11/23 at rung 400, area-weighted per face: `elongation`
reproduces at r=0.406 and `extent` at 0.457. The consequence at the level that
matters: cluster this space at k=10, re-segment with three seeds, and the
area-weighted adjusted Rand index between the three face-level part maps is 0.148.
A part list a person is asked to name and correct is largely reading the
segmenter's coin flips.

So build every coordinate from a face field pooled over a **geodesic ball of fixed
physical radius**, which no tessellation can see. Same seeds, same rung: 0.315 at
k=10 and 0.449 at k=6, against 0.148 and 0.177 for the existing space. On three SLIC
seeds (31/47/59) held out of every choice made here -- channels, radii, constants,
k -- it holds: **0.293 against 0.133 at k=10, 0.415 against 0.172 at k=6**. That is
the claim this file rests on, and it is the one a person cares about: a part list
they are asked to name and correct must not move because the segmenter was
re-seeded.

**The pipeline, and the measurement behind each step.**

*Seed-free coarsening.* Voxel-bin the face centroids on a grid of edge
`h = max(r_det/4, 1.5*sqrt(mean face area))` -- the first term keeps at least four
nodes across the smallest radius, the second stops the grid asking for cells finer
than the triangles. Shell 626,766 faces -> 228,113 nodes at h=0.252mm; dragon
475,270 -> 189,467 at 0.423mm. Two bins are adjacent **iff some face pair in
`session["pairs"]` crosses them**, so connectivity is the mesh's and not the grid's:
the dragon's 29 bodies stay 29, the two sides of a thin wall stay apart, and nothing
diffuses across the air gap between the shell and its base.

*Heat-kernel smoothing.* `P = 0.5*I + 0.5*D^-1 W` on that graph -- a lazy random
walk. The 0.5 is not a knob; it is what stops a bipartite two-colour oscillation and
makes `P` a smoother. Steps are converted to millimetres by measuring the mesh
rather than assuming: 32 unit masses, `t` in {64,256,1024}, `K = median over t of the
area-weighted mean displacement / sqrt(t)`, then `t = (r/K)^2`. K came out 0.1671 on
the shell and 0.2668 on the dragon -- a 60% difference between two models, which is
exactly why it cannot be a constant.

The coarsening is structural, not an optimisation. Unpreconditioned CG for the
implicit `(I + alpha*L)` solve on the full 626k-face graph did not finish in ten
minutes; the explicit pass on the coarse graph does all four radii in about two.

*Radii from the rung.* `r_patch = sqrt(total_area / n_patches / pi)`, the
equivalent-disc radius of one patch at this rung, times {1/8, 1/2, 2, 4}, named
det/mid/form/gross. Shell rung 400 -> 0.47/1.88/7.51/15.03mm. This keeps the ladder
a ladder: rung 6400 gets 0.12/0.47/1.88/3.76mm, a genuinely different space at a
different zoom, which is the opposite of the cross-rung averaging that blurred the
Monte Carlo consensus into selections that were nobody's.

*Channels.* Diffuse ten columns in one pass -- `n`, the six unique entries of
`n n^T`, and roughness -- snapshotting at each radius. `Cov = smooth(n n^T) -
smooth(n) smooth(n)^T` has eigenvalues l1>=l2>=l3, and `turn1 = sqrt(l1)`,
`turn2 = sqrt(l2)` are the angular spread of the normal field inside the ball: a
plane gives (0,0), a rib gives (high, ~0), a cone gives (high, high). That is the
seed-free replacement for extent/elongation/flatness -- the aspect ratio of the
surface's own curvature on a fixed physical support, with no cell boundary to see
and no undefined case to gate, unlike a shape index. Reproducibility across SLIC
seeds, against 0.820 for the best existing descriptor: turn1@det 0.857, turn1@form
0.929, turn2@form 0.969, turn1@gross 0.979, rough@det 0.839, drough 0.889. Every one
beats the best of the old six.

Two things this deliberately does not carry. **Scale ratios**, which were the
theory's headline and lost on every axis when measured (panel dominance 0.65 -> 0.48,
coral 0.77 -> 0.39): how much the surface turns over 7.5mm is the signal, not how
much more it turns over 0.5mm than over 7.5mm. And **relief**, in any radius-
parameterised form: F over the four visual classes came out 1.75/0.96/0.98/0.49 at
0.4-3.2mm against 2.43 for the existing relief, and beyond 1.6mm it varies more
inside one visual class than across the whole model, because a patch holds both
proud tops and recessed gaps and the mean cancels. The one band-pass that survived
measurement is on roughness.

*Robust z, not rank.* Rank-normalisation manufactures spread in a descriptor that
is genuinely constant, and it forbids a large class by construction: it forces every
descriptor into a uniform marginal, so a panel covering half the surface is spread
across half the axis. Each channel gets a log (for the positive magnitudes) then
`(v - median)/(1.4826*MAD)`, clipped at 8. The clip is 8 and not 4 because at 4 an
entire real region sat pinned at the floor on three channels at once.

*k by stability, then by looking.* For each k, `kmeans-ARI` is the agreement between
k-means seeds 7/11/23 and `reseed-ARI` the agreement between three SLIC
re-segmentations of the same rung; `k_max` is the largest k whose smallest cluster
still holds 1% of the area, because a class below that is not a paint region for a
four-filament plate. The default is the largest local maximum of reseed-ARI passing
kmeans-ARI >= 0.90. Be honest about what that rule is worth: it was constructed
after seeing the shell's curve, and it is a rule fitted to one model that has then
been run on a second. It gives k=6 on the shell (shortlist 2, 4, 6) and k=5 on the
dragon (shortlist 2, 5) -- both readable, neither obviously the best of its
shortlist. Prediction strength with its published >=0.8 rule picks k=2 on both
spaces and bare argmax of reseed-ARI also picks 2, so neither is proposed. Stability
supplies a default and a three-item shortlist; the shortlist is rendered as a
contact sheet and picked by looking, which is this project's existing doctrine for
the rung. `--regions` overrides it outright.

**What this trades away, measured, because it is half of the stated test.** The test
was "smooth panels become one class without ribs, tubes and clusters collapsing
together". Measured against the previous agent's 34 panel / 8 rib / 16 barnacle / 8
coral patches, k-means seeds 7/11/23, as the overlap between two classes' cluster
distributions (`sum over clusters of min(share_a, share_b)`, 0 = disjoint):

    k=10   panel/rib  old 0.43 -> new 0.70    panel/coral old 0.44 -> new 0.18
    k=6    panel/rib  old 0.54 -> new 0.88    panel/coral old 0.69 -> new 0.23

The panels do become one class -- panel dominance 0.25 -> 0.42 at k=10 and 0.38 ->
0.68 at k=6, touching-panel-pair disagreement 0.89 -> 0.67 and 0.77 -> 0.48 -- and
the barnacle and coral classes come apart from them. **The ribs go the other way:
they are absorbed into the panel class**, and at k=6 the rib's dominant cluster IS
the panel's. A per-class dominance score does not show this, because a rib sitting
80% inside the panel cluster still scores 0.80; only the pair overlap and the render
do. The old space held the ribs precisely through the descriptors this replaces:
`extent` and `elongation` are the SLIC cell's bounding box, and a rib patch is long
and thin whatever the surface is doing. Reading the same anisotropy off a geodesic
ball loses it, because a broad rounded cord on an already curving shell has much the
same normal spread as the panel beside it.

Adding the missing radius does not fix it. Measured over `turn1@mid`, `turn2@mid`,
both, and `turn2@det` as extra channels: panel/rib overlap stays 0.76-0.90 at k=6
and 0.65-0.79 at k=10, and every variant costs either panel dominance (0.68 -> 0.44
at k=6) or reseed-ARI (0.449 -> 0.385). So the rib is not a gap in the radius ladder,
and the six channels below are the best set measured. Ribs are the open failure of
this space, and the next attempt on it needs a genuinely directional statistic --
the eigenvector, not just the eigenvalue -- rather than another radius.

Nothing here is subject-specific and nothing is a threshold on an edge. Adjacency is
used to decide which voxels are connected and by `fill_nearest`, neither of which is
a test, so the recorded failure that any per-edge gate is defeated by a gradual
slope has nothing to attach to.

    level0_basis.py --session work/ --rung 400
    level0_basis.py --session work/ --rung 400 --regions 6
    label_tree.py   --session work/ --name region-2 --new-name "barnacle colony"
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
from label_tree import PALETTE, find, load_tree, save_tree, visible_coordinate  # noqa: E402
from oversegment import load_fields                                  # noqa: E402
from patch_features import cluster                                   # noqa: E402
from resolve_parts import fill_nearest                               # noqa: E402
from scale_ladder import contact_sheet, ladder_path                  # noqa: E402

RADII = {"det": 0.125, "mid": 0.5, "form": 2.0, "gross": 4.0}
CHANNELS = ["turn1_det", "turn1_form", "turn2_form", "turn1_gross", "rough_det",
            "drough"]
LOG_CHANNEL = {name: not name.startswith("drough") for name in CHANNELS}
MAD_CLIP = 8.0
STABILITY_SEEDS = (7, 11, 23)
MIN_CLUSTER_AREA = 0.01
KMEANS_ARI_GATE = 0.90


def coarse_graph(centres, areas, pairs, h):
    """Voxel bins joined by the mesh's own adjacency, not the grid's.

    The grid is only a bucketing device. Every edge here comes from a face pair, so
    two bins that touch in space but not across the surface -- the two sides of a
    thin wall, the shell and the rock it stands on -- are never connected.
    """
    from scipy.sparse import coo_matrix, diags, identity

    key = np.floor((centres - centres.min(axis=0)) / h).astype(np.int64)
    dims = key.max(axis=0) + 1
    flat = (key[:, 0] * dims[1] + key[:, 1]) * dims[2] + key[:, 2]
    _unique, bin_of = np.unique(flat, return_inverse=True)
    count = int(bin_of.max()) + 1

    bin_area = np.bincount(bin_of, weights=areas, minlength=count)
    safe = np.maximum(bin_area, 1e-12)
    bin_centre = np.stack([np.bincount(bin_of, weights=areas * centres[:, axis],
                                       minlength=count) / safe for axis in range(3)],
                          axis=1)

    left, right = bin_of[pairs[:, 0]], bin_of[pairs[:, 1]]
    crossing = left != right
    rows = np.concatenate([left[crossing], right[crossing]])
    cols = np.concatenate([right[crossing], left[crossing]])
    adjacency = coo_matrix((np.ones(len(rows)), (rows, cols)),
                           shape=(count, count)).tocsr()
    adjacency.data[:] = 1.0
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    walk = (diags(0.5 / np.maximum(degree, 1e-12)) @ adjacency
            + 0.5 * identity(count, format="csr")).tocsr()
    return walk, bin_of, bin_area, bin_centre


def calibrate(walk, bin_area, bin_centre, samples=32, seed=0, probes=(64, 256, 1024)):
    """How many steps make a millimetre, measured on this mesh rather than assumed.

    A random walk spreads as sqrt(t), so one constant K describes the whole ladder.
    It is a property of the mesh: 0.1671 on the shell against 0.2668 on the dragon.
    """
    count = len(bin_area)
    rng = np.random.default_rng(seed)
    sources = rng.choice(count, min(samples, count), replace=False)
    mass = np.zeros((count, len(sources)))
    mass[sources, np.arange(len(sources))] = 1.0

    done, constants = 0, []
    for probe in probes:
        for _ in range(probe - done):
            mass = walk @ mass
        done = probe
        spread = []
        for column, source in enumerate(sources):
            weight = np.maximum(mass[:, column], 0) * bin_area
            if weight.sum() <= 0:
                continue
            distance = np.linalg.norm(bin_centre - bin_centre[source], axis=1)
            spread.append(float((weight * distance).sum() / weight.sum()))
        constants.append(np.mean(spread) / np.sqrt(probe))
    return float(np.median(constants))


def form_fields(session, patch_count, report=print):
    """Per-face turn and roughness at four radii derived from the rung.

    Returns (fields, meta). One diffusion pass produces all four radii by
    snapshotting as it passes each one.
    """
    faces = session["faces"]
    centres = session["vertices"][faces].mean(axis=1).astype(np.float64)
    areas = session["areas"].astype(np.float64)
    normals = session["normals"].astype(np.float64)
    roughness = session["roughness"].astype(np.float64)

    r_patch = float(np.sqrt(areas.sum() / max(patch_count, 1) / np.pi))
    radii = {tag: r_patch * factor for tag, factor in RADII.items()}
    h = max(radii["det"] / 4.0, 1.5 * float(np.sqrt(areas.mean())))
    report("  %d patches, r_patch %.2fmm, radii %s"
           % (patch_count, r_patch,
              " ".join("%s %.2f" % (t, radii[t]) for t in RADII)))

    walk, bin_of, bin_area, bin_centre = coarse_graph(centres, areas,
                                                      session["pairs"], h)
    constant = calibrate(walk, bin_area, bin_centre)
    report("  voxel h %.3fmm -> %d coarse nodes, K %.4f (radius = K*sqrt(steps))"
           % (h, len(bin_area), constant))

    columns = np.stack([normals[:, 0], normals[:, 1], normals[:, 2],
                        normals[:, 0] ** 2, normals[:, 1] ** 2, normals[:, 2] ** 2,
                        normals[:, 0] * normals[:, 1], normals[:, 0] * normals[:, 2],
                        normals[:, 1] * normals[:, 2], roughness], axis=1)
    safe = np.maximum(bin_area, 1e-12)
    state = np.stack([np.bincount(bin_of, weights=areas * columns[:, j],
                                  minlength=len(bin_area)) / safe
                      for j in range(columns.shape[1])], axis=1)

    fields, steps, done = {}, {}, 0
    for tag in RADII:
        want = max(1, int(round((radii[tag] / constant) ** 2)))
        start = time.time()
        for _ in range(want - done):
            state = walk @ state
        done, steps[tag] = want, want

        mean_normal = state[:, 0:3]
        second = np.empty((len(bin_area), 3, 3))
        second[:, 0, 0], second[:, 1, 1], second[:, 2, 2] = state[:, 3], state[:, 4], state[:, 5]
        second[:, 0, 1] = second[:, 1, 0] = state[:, 6]
        second[:, 0, 2] = second[:, 2, 0] = state[:, 7]
        second[:, 1, 2] = second[:, 2, 1] = state[:, 8]
        second -= mean_normal[:, :, None] * mean_normal[:, None, :]
        eigenvalues = np.linalg.eigvalsh(second)

        fields["turn1_" + tag] = np.sqrt(np.maximum(eigenvalues[:, 2], 0))[bin_of]
        fields["turn2_" + tag] = np.sqrt(np.maximum(eigenvalues[:, 1], 0))[bin_of]
        fields["rough_" + tag] = state[:, 9][bin_of]
        report("    %-5s r %6.2fmm  %5d steps  %4.0fs"
               % (tag, radii[tag], want, time.time() - start))
    meta = {"r_patch": r_patch, "radii": radii, "h": h, "nodes": int(len(bin_area)),
            "K": constant, "steps": steps}
    return fields, meta


def patch_space(fields, labels, areas, clip=MAD_CLIP):
    """Area-weighted patch means of each face field, then a robust z per column."""
    count = int(labels.max()) + 1
    weight = np.maximum(np.bincount(labels, weights=areas, minlength=count), 1e-12)
    pooled = {name: np.bincount(labels, weights=field.astype(np.float64) * areas,
                                minlength=count) / weight
              for name, field in fields.items()}
    pooled["drough"] = pooled["rough_det"] - pooled["rough_mid"]

    space = np.zeros((count, len(CHANNELS)))
    for index, name in enumerate(CHANNELS):
        values = np.asarray(pooled[name], dtype=float)
        if LOG_CHANNEL[name]:
            values = np.log(np.maximum(values, 1e-9))
        middle = np.median(values)
        scale = np.median(np.abs(values - middle)) * 1.4826
        if scale <= 0:
            scale = values.std() or 1.0
        space[:, index] = np.clip((values - middle) / scale, -clip, clip)
    return space, pooled


def area_ari(left, right, weight):
    """Adjusted Rand index over surface area rather than face count.

    Faces vary in area by orders of magnitude, so counting them would let a dense
    corner of the mesh outvote a whole panel. Weights are normalised to sum to one
    and the pair counts taken in their continuous form, which makes the score
    independent of how the area happens to be measured.
    """
    weight = np.asarray(weight, dtype=float)
    total = weight.sum()
    if total <= 0:
        return float("nan")
    left = np.asarray(left, dtype=np.int64)
    right = np.asarray(right, dtype=np.int64)
    width = int(right.max()) + 1
    table = np.bincount(left * width + right, weights=weight / total,
                        minlength=(int(left.max()) + 1) * width)
    table = table.reshape(-1, width)
    rows, cols = table.sum(axis=1), table.sum(axis=0)
    agree = float((table ** 2).sum())
    expect = float((rows ** 2).sum() * (cols ** 2).sum())
    most = 0.5 * float((rows ** 2).sum() + (cols ** 2).sum())
    return (agree - expect) / (most - expect) if most > expect else 1.0


def face_labels(assignment, live, patch_labels, member_faces, face_count, pairs):
    """Patch clusters projected to faces, with stranded faces filled from neighbours."""
    region_of_patch = np.full(int(patch_labels.max()) + 1, -1, dtype=np.int32)
    region_of_patch[live] = assignment
    face_region = np.full(face_count, -1, dtype=np.int32)
    face_region[member_faces] = region_of_patch[patch_labels[member_faces]]
    if (face_region[member_faces] < 0).any():
        filled = fill_nearest(face_region, pairs)
        face_region[member_faces] = filled[member_faces]
    return face_region


def reseeded_rungs(session_dir, session, rung, seeds, report=print):
    """The same rung re-segmented from different SLIC seeds, cached beside the session.

    These exist to be disagreed with. Their disagreement is the score; nothing here
    merges on it, which is the failure that produced 280 patches with one covering
    89% of the model.
    """
    fields = load_fields(session_dir, session)
    centres = session["vertices"][session["faces"]].mean(axis=1)
    out = []
    for seed in seeds:
        path = os.path.join(session_dir, "basis_reseed_%d_%d.npy" % (rung, seed))
        if not os.path.exists(path):
            start = time.time()
            labels = superpatches(centres, session["normals"], session["pairs"],
                                  target_patches=rung, fields=fields,
                                  iterations=2, seed=seed)
            np.save(path, labels)
            report("    seed %-3d %4d patches  %.0fs"
                   % (seed, labels.max() + 1, time.time() - start))
        out.append(np.load(path))
    return out


def stability(space, spaces_reseeded, patch_labels, labels_reseeded, member_faces,
              areas, pairs, k_values, seeds=STABILITY_SEEDS, report=print):
    """kmeans-ARI and reseed-ARI per candidate k, both area-weighted over faces."""
    face_count = len(areas)
    weight = areas[member_faces]
    rows = []
    for k in k_values:
        runs = []
        for seed in seeds:
            live = np.flatnonzero(np.bincount(patch_labels[member_faces],
                                              minlength=int(patch_labels.max()) + 1) > 0)
            assignment, _ = cluster(space[live], k, seed=seed)
            runs.append(face_labels(assignment, live, patch_labels, member_faces,
                                    face_count, pairs)[member_faces])
        kmeans = float(np.mean([area_ari(runs[a], runs[b], weight)
                                for a in range(len(runs)) for b in range(a + 1, len(runs))]))

        reruns = []
        for other_space, other_labels in zip(spaces_reseeded, labels_reseeded):
            live = np.flatnonzero(np.bincount(other_labels[member_faces],
                                              minlength=int(other_labels.max()) + 1) > 0)
            assignment, _ = cluster(other_space[live], k, seed=seeds[0])
            reruns.append(face_labels(assignment, live, other_labels, member_faces,
                                      face_count, pairs)[member_faces])
        reseed = float(np.mean([area_ari(reruns[a], reruns[b], weight)
                                for a in range(len(reruns))
                                for b in range(a + 1, len(reruns))]))

        shares = np.array([weight[runs[0] == g].sum() for g in range(k)]) / weight.sum()
        rows.append({"k": k, "kmeans_ari": kmeans, "reseed_ari": reseed,
                     "smallest": float(shares.min()), "largest": float(shares.max())})
        report("    k %2d  kmeans-ARI %.3f  reseed-ARI %.3f  smallest class %5.2f%%"
               % (k, kmeans, reseed, 100 * shares.min()))
    return rows


def choose_k(rows):
    """The largest reproducible local maximum of reseed-ARI, if there is one.

    A local maximum rather than the maximum because the maximum is always k=2 -- two
    classes agree with themselves. The kmeans-ARI gate throws out any k where the
    clustering is not even stable against its own initialisation.
    """
    usable = [row for row in rows if row["smallest"] >= MIN_CLUSTER_AREA]
    if not usable:
        return None, []
    peaks = []
    for index, row in enumerate(usable):
        before = usable[index - 1]["reseed_ari"] if index else -1.0
        after = usable[index + 1]["reseed_ari"] if index + 1 < len(usable) else -1.0
        if row["reseed_ari"] >= before and row["reseed_ari"] >= after:
            peaks.append(row)
    gated = [row for row in peaks if row["kmeans_ari"] >= KMEANS_ARI_GATE]
    if gated:
        return gated[-1]["k"], [row["k"] for row in gated]
    if peaks:
        return peaks[-1]["k"], [row["k"] for row in peaks]
    return max(usable, key=lambda row: row["reseed_ari"])["k"], []


def render(mesh, face_region, groups, view, size):
    colours = np.tile(np.array([0.88, 0.88, 0.90]), (len(mesh.faces), 1))
    for group in range(groups):
        colours[face_region == group] = PALETTE[group % len(PALETTE)]
    image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view], size)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--rung", type=int, required=True,
                        help="ladder rung to resolve this level at")
    parser.add_argument("--regions", type=int, default=None,
                        help="override k; without it k comes from stability")
    parser.add_argument("--parent", default=None,
                        help="subdivide this label instead of the whole surface")
    parser.add_argument("--kmax", type=int, default=12,
                        help="largest k the stability search considers")
    parser.add_argument("--seed", type=int, default=STABILITY_SEEDS[0])
    parser.add_argument("--size", type=int, default=900)
    parser.add_argument("--rebuild", action="store_true",
                        help="recompute the diffused fields instead of using the cache")
    args = parser.parse_args()

    session_path = os.path.join(args.session, "session.npz")
    if not os.path.exists(session_path):
        parser.error("no session.npz in %s; run inspect_model.py first" % args.session)
    session = np.load(session_path)
    faces, areas = session["faces"], session["areas"].astype(np.float64)
    path = ladder_path(args.session, args.rung)
    if not os.path.exists(path):
        raise SystemExit("level0_basis: rung %d not built; run scale_ladder.py --build"
                         % args.rung)
    patch_labels = np.load(path)

    tree = load_tree(args.session)
    if args.parent:
        parent = find(tree, args.parent)
        if parent is None:
            raise SystemExit("level0_basis: no label %r" % args.parent)
        member_faces = np.array(parent["face_indices"], dtype=np.int64)
        prefix = "%s/" % parent["name"]
    else:
        parent, prefix = None, ""
        member_faces = np.arange(len(faces))
    inside = np.zeros(len(faces), dtype=bool)
    inside[member_faces] = True
    total_area = float(areas.sum())
    member_area = float(areas[member_faces].sum())

    counts = np.bincount(patch_labels[inside], minlength=int(patch_labels.max()) + 1)
    live = np.flatnonzero(counts > 0)
    if len(live) < 2:
        raise SystemExit("level0_basis: rung %d gives only %d patch(es) inside %r; "
                         "use a finer rung" % (args.rung, len(live), args.parent))

    cache = os.path.join(args.session, "basis_fields_%d.npz" % args.rung)
    print("form space at rung %d over %d faces" % (args.rung, len(faces)))
    if os.path.exists(cache) and not args.rebuild:
        stored = np.load(cache)
        fields = {name: stored[name] for name in stored.files if name != "meta"}
        meta = json.loads(str(stored["meta"]))
        print("  cached: %d coarse nodes, K %.4f, radii %s"
              % (meta["nodes"], meta["K"],
                 " ".join("%s %.2f" % (t, meta["radii"][t]) for t in RADII)))
    else:
        fields, meta = form_fields(session, int(patch_labels.max()) + 1)
        np.savez_compressed(cache, meta=json.dumps(meta),
                            **{k: v.astype(np.float32) for k, v in fields.items()})
    space, pooled = patch_space(fields, patch_labels, areas)

    shortlist, rows = [], []
    if args.regions is None:
        print("\nstability over SLIC re-segmentations of rung %d" % args.rung)
        labels_reseeded = reseeded_rungs(args.session, session, args.rung,
                                         STABILITY_SEEDS)
        # The face fields are a property of the mesh and the rung's radii, not of the
        # seed, so only the pooling is redone per reseed.
        spaces_reseeded = [patch_space(fields, labels, areas)[0]
                           for labels in labels_reseeded]
        rows = stability(space, spaces_reseeded, patch_labels, labels_reseeded,
                         member_faces, areas, session["pairs"],
                         range(2, max(3, args.kmax) + 1))
        groups, shortlist = choose_k(rows)
        print("  stable k: %s -> k* = %d"
              % (", ".join(str(k) for k in shortlist) or "none", groups))
    else:
        groups = args.regions
    groups = min(groups, len(live))

    assignment, _centres = cluster(space[live], groups, seed=args.seed)
    face_region = face_labels(assignment, live, patch_labels, member_faces,
                              len(faces), session["pairs"])

    hidden = None
    atlas_path = os.path.join(args.session, "view_atlas.npz")
    if os.path.exists(atlas_path):
        hidden = np.load(atlas_path)["seen"] == 0

    tree["nodes"] = [n for n in tree["nodes"]
                     if not (n.get("parent") == (parent["name"] if parent else None)
                             and n.get("auto"))]
    added = []
    for group in range(groups):
        mask = (face_region == group) & inside
        if not mask.any():
            continue
        indices = np.flatnonzero(mask)
        name = "%sregion-%d" % (prefix, group)
        while find(tree, name):
            name += "'"
        node = {"name": name, "parent": parent["name"] if parent else None,
                "rung": args.rung, "auto": True,
                "area": round(float(areas[mask].sum() / total_area), 5),
                "faces": int(mask.sum()),
                "at": visible_coordinate(session, indices),
                "centroid": [round(float(v), 2) for v in
                             session["vertices"][faces[indices]].mean(axis=(0, 1))],
                "face_indices": [int(v) for v in indices]}
        if hidden is not None:
            node["hidden_area"] = round(float(areas[mask & hidden].sum()
                                              / max(areas[mask].sum(), 1e-12)), 4)
        tree["nodes"].append(node)
        added.append(node)
    save_tree(args.session, tree)

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    out = os.path.join(args.session, "labels")
    os.makedirs(out, exist_ok=True)
    slug = (parent["name"].replace("/", "-") if parent else "level0-basis")
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in slug).strip("-")
    for view in (["iso", "front"] if not parent else ["iso"]):
        raster.save_png(os.path.join(out, "%s-%s.png" % (slug, view)),
                        render(mesh, face_region, groups, view, args.size))

    sheet_path = None
    if len(shortlist) > 1:
        # The shortlist is rendered rather than argued about, for the same reason the
        # rung is: "the second one has swallowed the rib" is easy from an image and
        # impossible from an area percentage.
        images = []
        for candidate in shortlist[-3:]:
            other, _ = cluster(space[live], min(candidate, len(live)), seed=args.seed)
            regions = face_labels(other, live, patch_labels, member_faces,
                                  len(faces), session["pairs"])
            images.append(render(mesh, regions, candidate, "iso", 460))
        sheet_path = os.path.join(out, "%s-shortlist.png" % slug)
        raster.save_png(sheet_path, contact_sheet(images, columns=len(images)))

    covered = np.zeros(len(faces), dtype=bool)
    overlap = 0
    for node in added:
        indices = np.array(node["face_indices"], dtype=np.int64)
        overlap += int(covered[indices].sum())
        covered[indices] = True

    print("\n%d regions inside %s at rung %d"
          % (len(added), parent["name"] if parent else "the whole surface", args.rung))
    for index, node in enumerate(added):
        rgb = PALETTE[index % len(PALETTE)]
        share = 100 * float(areas[node["face_indices"]].sum() / member_area)
        print("  %-22s %6.2f%% area  %7d faces  %5.1f%% hidden  at %-16s rgb(%3d,%3d,%3d)"
              % (node["name"], share, node["faces"],
                 100 * node.get("hidden_area", float("nan")), node["at"] or "-",
                 *(int(255 * c) for c in rgb)))
        if node["at"] is None:
            print("      never visible from any stored view -- name it from its "
                  "neighbours, not from a coordinate")
    print("\n  coverage %d/%d faces (%.2f%%), %d faces in more than one region"
          % (int(covered[member_faces].sum()), len(member_faces),
             100 * covered[member_faces].mean(), overlap))
    if rows:
        with open(os.path.join(out, "%s-stability.json" % slug), "w") as handle:
            json.dump({"rung": args.rung, "k": groups, "shortlist": shortlist,
                       "rows": rows}, handle, indent=2)
    print("  render: %s/%s-*.png" % (out, slug))
    if sheet_path:
        print("  shortlist: %s (k = %s, left to right)"
              % (sheet_path, ", ".join(str(k) for k in shortlist[-3:])))
    print("  LOOK at it, then name each region by its colour:")
    print("    label_tree.py --session %s --name '%s' --new-name '<what it is>'"
          % (args.session, added[0]["name"] if added else "region-0"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
