"""Label from the scale-space index: size classes, and their connected instances.

Three earlier level-0 designs clustered patch descriptors and all three died the same
death -- re-tessellate the model and the partition changes (ARI 0.130 / 0.193, landmark
grouping at chance), because the coordinates being clustered were statistics of the
SLIC cell rather than of the surface. This builds the same map out of `scale_space.py`,
whose only inputs are geometry, so there is no seed to vary and nothing to reshuffle.

A face's characteristic scale says how big the thing it belongs to is, in millimetres.
Quantising that gives SIZE CLASSES -- every barnacle throat on the model lands in one
class wherever it sits, the smooth whorl bands in another. Splitting a class into
connected components gives INSTANCES -- this colony, that colony. Class and instance are
the two things the earlier attempts conflated, and here they fall out of one field
rather than needing separate machinery: "all barnacles orange" addresses the class,
"this one colony darker" addresses a component of it.

Two details that are not arbitrary:

The field is diffused before quantising. A per-face argmax over 14 radii is noisy at the
single-triangle level, and quantising raw would shatter every band into thousands of
specks. A few rounds of averaging on the same operator the index itself uses costs
nothing and is not a threshold in disguise -- it changes which side of a band edge a
borderline face falls, never how many bands there are.

Components below a floor are absorbed into the nearest labelled region across the
surface, never into a global default. A single global fallback was measured painting
42.4% of a rock base as shell.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from resolve_parts import fill_nearest                               # noqa: E402
from scale_space import diffusion_operator                           # noqa: E402

PALETTE = np.array([
    [0.90, 0.24, 0.20], [0.20, 0.55, 0.90], [0.30, 0.75, 0.35], [0.95, 0.65, 0.15],
    [0.65, 0.35, 0.85], [0.10, 0.70, 0.70], [0.95, 0.45, 0.65], [0.55, 0.45, 0.25],
    [0.45, 0.80, 0.20], [0.20, 0.35, 0.70], [0.85, 0.35, 0.45], [0.40, 0.65, 0.60],
])


def components(mask, pairs, count):
    """Connected components of `mask` on the face graph, as labels (-1 outside)."""
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components
    keep = np.flatnonzero(mask)
    if not len(keep):
        return np.full(count, -1, dtype=np.int32), 0
    index = np.full(count, -1, dtype=np.int64)
    index[keep] = np.arange(len(keep))
    inside = mask[pairs[:, 0]] & mask[pairs[:, 1]]
    rows, cols = index[pairs[inside, 0]], index[pairs[inside, 1]]
    graph = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)),
                              shape=(len(keep), len(keep)))
    total, labels = connected_components(graph, directed=False)
    out = np.full(count, -1, dtype=np.int32)
    out[keep] = labels
    return out, total


def build(session, index, bands, smooth, min_area, sign_split=0.35):
    faces, areas, pairs = session["faces"], session["areas"], session["pairs"]
    count = len(faces)
    scale = np.log(np.maximum(index["characteristic_mm"], 1e-6)).astype(np.float64)

    operator = diffusion_operator(pairs, count)
    for _ in range(max(0, int(smooth))):
        scale = operator @ scale

    low, high = scale.min(), scale.max()
    edges = np.linspace(low, high + 1e-9, bands + 1)
    band_of = np.clip(np.digitize(scale, edges[1:-1]), 0, bands - 1).astype(np.int32)

    # Size alone cannot tell a ridge from the flat band beside it -- both are the same
    # size, which is why a size-only map scored the shell's ribs at 38% of their area
    # against 80% for the descriptor baseline it otherwise beat. The sign of the relief
    # at the face's own scale is the missing axis, and it is scale-invariant in its own
    # right: +1 is a ridge or a boss, -1 a groove or a throat, whatever their size.
    if "signed" in index and sign_split > 0:
        signed = np.asarray(index["signed"], dtype=np.float64)
        for _ in range(max(0, int(smooth))):
            signed = operator @ signed
        spread = float(np.percentile(np.abs(signed), 90)) or 1.0
        form = np.digitize(signed / spread, [-sign_split, sign_split]).astype(np.int32)
        band_of = band_of * 3 + form
        bands = bands * 3

    total_area = float(areas.sum())
    label = np.full(count, -1, dtype=np.int32)
    nodes = []
    for band in range(bands):
        mask = band_of == band
        if not mask.any():
            continue
        comp, found = components(mask, pairs, count)
        for c in range(found):
            piece = comp == c
            share = float(areas[piece].sum() / total_area)
            if share < min_area:
                continue
            label[piece] = len(nodes)
            nodes.append({"band": int(band), "component": int(c), "area": round(share, 5),
                          "faces": int(piece.sum()),
                          "scale_mm": [round(float(np.exp(edges[band // 3])), 3),
                                       round(float(np.exp(edges[band // 3 + 1])), 3)]})
    stranded = float(areas[label < 0].sum() / total_area)
    if (label < 0).any():
        label = fill_nearest(label, pairs)
    return label, nodes, band_of, stranded


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--bands", type=int, default=6,
                        help="how many size classes to cut the scale range into")
    parser.add_argument("--smooth", type=int, default=6,
                        help="diffusion rounds before quantising")
    parser.add_argument("--min-area", type=float, default=0.002,
                        help="components below this share are absorbed by a neighbour")
    parser.add_argument("--sign-split", type=float, default=0.35,
                        help="how pronounced relief must be to count as ridge or "
                             "groove rather than flat; 0 disables the sign axis")
    parser.add_argument("--by", choices=["class", "instance"], default="class",
                        help="colour the render by size class or by connected instance")
    parser.add_argument("--views", default="iso,front")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    index_path = os.path.join(args.session, "scale_space.npz")
    if not os.path.exists(index_path):
        raise SystemExit("scale_label: no scale_space.npz; run scale_space.py first")
    index = np.load(index_path)

    label, nodes, band_of, stranded = build(session, index, args.bands,
                                            args.smooth, args.min_area,
                                            args.sign_split)
    faces, areas = session["faces"], session["areas"]
    total = float(areas.sum())

    classes = sorted({n["band"] for n in nodes})
    print("%d size x form classes, %d regions kept, %.2f%% absorbed by neighbours"
          % (len(classes), len(nodes), 100 * stranded))
    for band in classes:
        members = [n for n in nodes if n["band"] == band]
        if not members:
            continue
        share = sum(n["area"] for n in members)
        form = ("groove", "flat", "ridge")[band % 3] if args.sign_split > 0 else ""
        print("  %5.2f-%5.2fmm %-7s %5.2f%% of area  %3d instance(s)"
              % (members[0]["scale_mm"][0], members[0]["scale_mm"][1], form,
                 100 * share, len(members)))

    with open(os.path.join(args.session, "scale_labels.json"), "w") as handle:
        json.dump({"bands": args.bands, "smooth": args.smooth, "nodes": nodes}, handle,
                  indent=2)
    np.save(os.path.join(args.session, "scale_labels.npy"), label)

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    colours = np.tile(np.array([0.88, 0.88, 0.90]), (len(faces), 1))
    if args.by == "class":
        for node_id, node in enumerate(nodes):
            colours[label == node_id] = PALETTE[node["band"] % len(PALETTE)]
    else:
        for node_id in range(len(nodes)):
            colours[label == node_id] = PALETTE[node_id % len(PALETTE)]
    out = os.path.join(args.session, "scalelabels")
    os.makedirs(out, exist_ok=True)
    for view in args.views.split(","):
        if view.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()], 900)
            raster.save_png(os.path.join(out, "%s-%s.png" % (args.by, view.strip())),
                            image)
    print("  %s/%s-*.png" % (out, args.by))
    return 0


if __name__ == "__main__":
    sys.exit(main())
