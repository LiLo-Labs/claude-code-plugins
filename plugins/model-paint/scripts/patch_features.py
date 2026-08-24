"""Describe every surface patch, then group patches that are the same kind of thing.

Once the surface is tiled into patches whose boundaries are already correct, the
remaining question is not "where does this feature end" but "which patches are the
same kind of thing". That is a much better conditioned question: a patch has a
size, a shape, a depth and a texture, and two barnacle cones agree on all of them
while a rib disagrees on every one.

So each patch gets a small vector of descriptors, patches are clustered in that
space, and the clusters are what an agent labels -- "these 340 patches are
barnacle cones", once, rather than pointing at each cone in turn.

Descriptors are deliberately scale-relative (fractions of the model's diagonal or
percentiles of its own signals) so the same clustering behaves the same way on a
55 mm terrain piece and a 200 mm creature.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


DESCRIPTORS = ["area", "extent", "elongation", "flatness", "relief", "occlusion",
               "roughness", "thickness", "height", "curvature"]

# What the grouping is allowed to use. Deliberately shape only: two barnacle cones
# on opposite sides of a model are the same kind of thing, and including where they
# sit or how deep in shadow they are splits one class in half on nothing. Position
# and cavity stay in the descriptor table because they are worth reporting and
# worth colouring by -- just not worth clustering on.
CLUSTER_ON = ["extent", "elongation", "flatness", "relief", "roughness", "curvature"]


def describe_patches(labels, centres, normals, areas, fields, diagonal):
    """One row of descriptors per patch, plus the raw stats for reporting."""
    count = int(labels.max()) + 1
    order = np.argsort(labels, kind="stable")
    sorted_labels = labels[order]
    starts = np.searchsorted(sorted_labels, np.arange(count))
    ends = np.searchsorted(sorted_labels, np.arange(count), side="right")

    rows = np.zeros((count, len(DESCRIPTORS)))
    stats = []
    total_area = float(areas.sum()) or 1.0
    heights = centres[:, 2]
    low, span = heights.min(), max(np.ptp(heights), 1e-9)

    for patch in range(count):
        members = order[starts[patch]:ends[patch]]
        if not len(members):
            stats.append(None)
            continue
        points = centres[members]
        spread = np.ptp(points, axis=0)
        sorted_spread = np.sort(spread)[::-1]
        longest = max(sorted_spread[0], 1e-9)
        patch_area = float(areas[members].sum())

        # Shape from the spread of face centres: elongation separates a rib from a
        # cone, flatness separates a plate from a lump.
        elongation = longest / max(sorted_spread[1], 1e-9)
        flatness = sorted_spread[2] / longest

        # How much the patch's own normals disagree: a cone curves, a panel does not.
        mean_normal = normals[members].mean(axis=0)
        curvature = 1.0 - float(np.linalg.norm(mean_normal))

        row = {
            "area": patch_area / total_area,
            "extent": longest / diagonal,
            "elongation": elongation,
            "flatness": flatness,
            "relief": float(np.mean(fields["relief"][members])),
            "occlusion": float(np.mean(fields["occlusion"][members])),
            "roughness": float(np.mean(fields["roughness"][members])),
            "thickness": float(np.mean(fields["thickness"][members])),
            "height": float((points[:, 2].mean() - low) / span),
            "curvature": curvature,
        }
        rows[patch] = [row[name] for name in DESCRIPTORS]
        stats.append({"faces": int(len(members)), "centre": points.mean(axis=0).tolist(),
                      **{k: round(float(v), 5) for k, v in row.items()}})
    return rows, stats


def standardise(rows):
    """Rank-normalise each descriptor so no single scale dominates the clustering."""
    out = np.zeros_like(rows)
    for column in range(rows.shape[1]):
        values = rows[:, column]
        finite = np.isfinite(values)
        if not finite.any():
            continue
        ranks = np.argsort(np.argsort(values[finite])).astype(float)
        ranks /= max(len(ranks) - 1, 1)
        out[finite, column] = ranks
    return out


def cluster(rows, groups, seed=7, iterations=40):
    """k-means with deterministic k-means++ seeding."""
    rng = np.random.default_rng(seed)
    count = len(rows)
    groups = max(1, min(int(groups), count))

    centres = [rows[int(rng.integers(count))]]
    for _ in range(groups - 1):
        distance = np.min([np.linalg.norm(rows - c, axis=1) for c in centres], axis=0)
        total = distance.sum()
        if total <= 0:
            centres.append(rows[int(rng.integers(count))])
            continue
        centres.append(rows[int(np.searchsorted(np.cumsum(distance / total),
                                                rng.random()))])
    centres = np.array(centres)

    assignment = np.zeros(count, dtype=np.int32)
    for _ in range(iterations):
        distance = np.linalg.norm(rows[:, None, :] - centres[None, :, :], axis=2)
        updated = np.argmin(distance, axis=1).astype(np.int32)
        if (updated == assignment).all():
            break
        assignment = updated
        for index in range(groups):
            members = rows[assignment == index]
            if len(members):
                centres[index] = members.mean(axis=0)
    return assignment, centres


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--patches", default=None, help="patch labels .npy")
    parser.add_argument("--groups", type=int, default=8, help="how many kinds of thing")
    parser.add_argument("--output", default=None, help="groups.json")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    labels = np.load(args.patches or os.path.join(args.session, "mesh_patches.npy"))
    vertices, faces, areas = session["vertices"], session["faces"], session["areas"]
    centres = vertices[faces].mean(axis=1)
    diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0))) or 1.0

    relief_path = os.path.join(args.session, "relief.npy")
    fields = {"relief": np.load(relief_path) if os.path.exists(relief_path)
              else np.zeros(len(faces)),
              "occlusion": session["occlusion"], "roughness": session["roughness"],
              "thickness": session["thickness"]}

    rows, stats = describe_patches(labels, centres, session["normals"], areas,
                                   fields, diagonal)
    columns = [DESCRIPTORS.index(name) for name in CLUSTER_ON]
    assignment, _centres = cluster(standardise(rows)[:, columns], args.groups)

    print("%d patches described, grouped into %d kinds\n" % (len(rows), args.groups))
    order = sorted(range(args.groups),
                   key=lambda g: -float(areas[np.isin(labels, np.flatnonzero(assignment == g))].sum()))
    summary = []
    for rank, group in enumerate(order, start=1):
        members = np.flatnonzero(assignment == group)
        if not len(members):
            continue
        face_mask = np.isin(labels, members)
        share = float(areas[face_mask].sum() / areas.sum())
        picked = [stats[m] for m in members if stats[m]]
        mean = lambda key: float(np.mean([p[key] for p in picked]))    # noqa: E731
        entry = {"group": rank, "patches": len(members),
                 "area": round(share, 4),
                 "extent_mm": round(mean("extent") * diagonal, 2),
                 "elongation": round(mean("elongation"), 2),
                 "relief": round(mean("relief"), 3),
                 "occlusion": round(mean("occlusion"), 3),
                 "roughness": round(mean("roughness"), 3),
                 "height": round(mean("height"), 3)}
        summary.append(entry)
        print("  group %-2d %5d patches  %6.2f%% area  size %5.1fmm  elong %4.1f  "
              "relief %+6.3f  cavity %.2f  rough %.2f  height %.2f"
              % (rank, len(members), 100 * share, entry["extent_mm"],
                 entry["elongation"], entry["relief"], entry["occlusion"],
                 entry["roughness"], entry["height"]))

    out = args.output or os.path.join(args.session, "groups.json")
    with open(out, "w") as handle:
        json.dump({"groups": summary,
                   "patch_group": [int(v) for v in assignment]}, handle, indent=2)
    np.save(os.path.join(args.session, "patch_group.npy"), assignment)
    print("\nwrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
