"""Regions whose boundaries are the surface's, not the tessellation's.

Everything in this project has selected by snapping to SLIC patches, and that is the
foundation defect under all the rest. SLIC seeds evenly and grows compactly, so on a
sculpted surface its cell walls fall wherever the seeding happened to put them rather
than on the edge of anything. Two consequences, both measured. Cell-shape statistics
reproduce at r=0.26 under a reseed, so nothing built on them survives re-tessellation
(partition ARI 0.130 / 0.193, landmark grouping at chance). And a selection can only
be as clean as the cells it is assembled from, which is why the painted renders show
sawtooth colour edges running across the middle of a smooth surface.

So do not snap to cells. Segment the scale-space index itself, and let the boundaries
fall where that field changes.

Edge weight between two touching faces is how differently the surface behaves at the
two of them: how far apart their characteristic scales are (in log-radius, because
scale is multiplicative), how differently they sit against their surroundings, and how
sharply the surface turns between them. All three are properties of geometry measured
in millimetres, so this graph is identical every time it is built -- there is no seed
anywhere in it.

The merge is Felzenszwalb-Huttenlocher: walk the edges from weakest to strongest and
join two regions when the edge between them is weaker than the internal variation each
already tolerates, with a size term that lets a small region resist absorption. It is
the right algorithm here for the reason it was invented -- it adapts the threshold to
each region rather than applying one everywhere, so a smooth panel can be one large
region while a barnacle field a millimetre away stays many small ones, which is exactly
the panel-versus-rib tension that defeated every fixed-threshold attempt. It is also
deterministic and seedless: sorting edges is the only ordering it needs.

    index_regions.py --session work/ --k 40
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402

PALETTE_SIZE = 24


def edge_weights(session, index):
    """Dissimilarity per adjacent face pair, from the index and the surface itself."""
    pairs = session["pairs"]
    left, right = pairs[:, 0], pairs[:, 1]

    scale = np.log(np.maximum(index["characteristic_mm"], 1e-6))
    scale_gap = np.abs(scale[left] - scale[right])
    scale_gap /= max(float(scale.std()), 1e-9)

    signed = np.asarray(index["signed"], dtype=np.float64)
    form_gap = np.abs(signed[left] - signed[right])
    form_gap /= max(float(signed.std()), 1e-9)

    # The dihedral angle is what a crease is, and it is the one cue that is local
    # enough to place a boundary exactly. It cannot carry the segmentation alone --
    # crease-based methods put 625,884 of this model's 626,766 triangles in one region
    # -- but as a term it sharpens edges the index only blurs across.
    normals = session["normals"]
    turn = 1.0 - np.einsum("ij,ij->i", normals[left], normals[right])
    turn /= max(float(turn.std()), 1e-9)

    return (scale_gap + form_gap + 2.0 * turn).astype(np.float64)


def felzenszwalb(pairs, weights, count, k, min_faces):
    """Adaptive-threshold agglomeration. Returns a label per face."""
    parent = np.arange(count)
    size = np.ones(count, dtype=np.int64)
    internal = np.zeros(count)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    order = np.argsort(weights, kind="stable")
    for edge in order:
        a, b = find(pairs[edge, 0]), find(pairs[edge, 1])
        if a == b:
            continue
        w = weights[edge]
        if w <= min(internal[a] + k / size[a], internal[b] + k / size[b]):
            if size[a] < size[b]:
                a, b = b, a
            parent[b] = a
            size[a] += size[b]
            internal[a] = w

    # A second pass absorbs specks into whichever neighbour they are most like, so the
    # map is regions rather than regions plus confetti. Weakest edge first, so a speck
    # joins its most similar neighbour rather than an arbitrary one.
    for edge in order:
        a, b = find(pairs[edge, 0]), find(pairs[edge, 1])
        if a == b:
            continue
        if size[a] < min_faces or size[b] < min_faces:
            if size[a] < size[b]:
                a, b = b, a
            parent[b] = a
            size[a] += size[b]

    roots = np.array([find(i) for i in range(count)])
    _unique, labels = np.unique(roots, return_inverse=True)
    return labels.astype(np.int32)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--k", type=float, default=40.0,
                        help="how much internal variation a region tolerates; larger "
                             "gives fewer, larger regions")
    parser.add_argument("--min-faces", type=int, default=200,
                        help="regions smaller than this are absorbed by a neighbour")
    parser.add_argument("--views", default="iso,front")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    index_path = os.path.join(args.session, "scale_space.npz")
    if not os.path.exists(index_path):
        raise SystemExit("index_regions: no scale_space.npz; run scale_space.py first")
    index = np.load(index_path)

    faces, areas = session["faces"], session["areas"]
    weights = edge_weights(session, index)
    labels = felzenszwalb(session["pairs"], weights, len(faces), args.k, args.min_faces)

    counts = np.bincount(labels)
    shares = np.bincount(labels, weights=areas) / float(areas.sum())
    print("%d regions over %d faces (k=%g)" % (len(counts), len(faces), args.k))
    print("  faces per region: median %d, smallest %d"
          % (int(np.median(counts)), int(counts.min())))
    print("  largest region: %.2f%% of area; top five %s"
          % (100 * shares.max(),
             ", ".join("%.1f%%" % (100 * s) for s in np.sort(shares)[::-1][:5])))
    print("  regions holding 50%% of the area: %d"
          % int(np.searchsorted(np.cumsum(np.sort(shares)[::-1]), 0.5) + 1))
    np.save(os.path.join(args.session, "index_regions.npy"), labels)

    import trimesh
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    rng = np.random.default_rng(11)
    palette = rng.uniform(0.15, 0.95, size=(PALETTE_SIZE, 3))
    colours = palette[labels % PALETTE_SIZE]
    out = os.path.join(args.session, "indexregions")
    os.makedirs(out, exist_ok=True)
    for view in args.views.split(","):
        if view.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()], 900)
            raster.save_png(os.path.join(out, "k%g-%s.png" % (args.k, view.strip())),
                            image)
    print("  %s/k%g-*.png -- LOOK at where the boundaries landed" % (out, args.k))
    return 0


if __name__ == "__main__":
    sys.exit(main())
