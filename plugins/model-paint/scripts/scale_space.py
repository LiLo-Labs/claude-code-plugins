"""A per-face, scale-invariant index: what size of thing is this face part of?

Everything this project has tried to identify features with has been a statistic of
the SLIC patch a face happened to land in, and that is why none of it reproduced. The
worst offender, patch elongation, correlates 0.26 with itself when the segmenter is
merely reseeded: it is the bounding box of an arbitrary cell, not a property of the
surface. Partitions built on such quantities do not survive re-tessellation (ARI 0.130
on the dragon, 0.193 on the shell, landmark grouping at chance), and no amount of
clustering repairs a coordinate that is measuring the coordinate system.

So measure the surface instead, at a radius stated in millimetres. This file computes,
for every face, how much the surface turns within a geodesic ball of radius r, for a
ladder of r. Nothing here knows what a patch is. Two runs give bitwise identical
answers because there is no seed and no tessellation choice anywhere in it, and two
different models are directly comparable because the radii are in millimetres rather
than in patches.

The construction is difference-of-Gaussians, on the mesh instead of on an image.
Diffusing the face-normal field is a random walk on the face graph, so t rounds of
neighbour averaging reach a geodesic radius of about sqrt(t) times the mean edge; the
dispersion of the smoothed normal, 1 - |n_t|, says how much the surface turns inside
that radius. Dispersion alone only ever increases with r, so it cannot say what size a
thing is. Its derivative across log-radius can: the response peaks at the radius where
the neighbourhood stops being flat and starts containing the whole feature, which is
that feature's own scale. This is Lindeberg's characteristic scale, and it is the same
reason SIFT looks for extrema across scale rather than within one.

What it buys, both of which the project needed and did not have:

**Features become findable rather than guessable.** A barnacle cup, a pleated rosette
and a whorl ridge are different sizes, so they peak at different radii. Thresholding the
response at one radius surfaces the things of that size wherever they are on the model,
including the ones nobody thought to look at -- the pleated rosette at the coil centre
was the most prominent thing on the shell and all three labelling agents walked past it.

**Rounds become overlayable.** A face's characteristic scale is a number in millimetres
attached to that face, not to a run, so two passes -- at different rungs, with different
clicks, in different sessions -- can be laid on top of each other and compared directly.
That is what a patch label can never do: patch 40 of one run has nothing to do with
patch 40 of the next.

    scale_space.py --session work/                 # build the index, render it
    scale_space.py --session work/ --peaks 2.0     # what is ~2mm across, wherever it is
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402

INDEX = "scale_space.npz"


def diffusion_operator(pairs, count):
    """Row-normalised averaging over the face graph, as a sparse matrix.

    A matrix multiply rather than the scatter-add the rest of the codebase uses: the
    ladder needs hundreds of rounds to reach the coarse radii, and np.add.at over two
    million pairs that many times is minutes where this is seconds.
    """
    from scipy import sparse
    left, right = pairs[:, 0], pairs[:, 1]
    rows = np.concatenate([left, right, np.arange(count)])
    cols = np.concatenate([right, left, np.arange(count)])
    data = np.ones(len(rows))
    adjacency = sparse.csr_matrix((data, (rows, cols)), shape=(count, count))
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    inverse = sparse.diags(1.0 / np.maximum(degree, 1.0))
    return (inverse @ adjacency).tocsr()


def build(session, radii_mm=None, scales=14):
    vertices, faces = session["vertices"], session["faces"]
    normals = session["normals"].astype(np.float64)
    triangles = vertices[faces]
    edge = float(np.mean(np.linalg.norm(triangles[:, 1] - triangles[:, 0], axis=1)))
    count = len(faces)

    # Radii from one edge up to a fifth of the model, geometrically spaced: a feature
    # ladder is multiplicative, not additive -- the interesting jump is 1mm to 2mm, not
    # 20mm to 21mm.
    diagonal = float(np.linalg.norm(np.ptp(vertices, axis=0)))
    if radii_mm is None:
        radii_mm = np.geomspace(edge * 1.5, diagonal * 0.2, scales)
    rounds = np.maximum(1, np.round((np.asarray(radii_mm) / edge) ** 2).astype(int))

    operator = diffusion_operator(session["pairs"], count)
    dispersion = np.zeros((len(rounds), count), dtype=np.float32)
    # Signed relief: how far the face sits outside its own smoothed neighbourhood,
    # along its normal, in millimetres. Scale says how BIG a thing is; it cannot say
    # whether the thing bulges or dips, and those are different features at identical
    # size -- a whorl ridge and the flat band beside it are both ~15mm, which is
    # exactly why a size-only index scored the ribs at 38% against the baseline's 80%.
    offset = np.zeros((len(rounds), count), dtype=np.float32)
    centres = triangles.mean(axis=1)
    field = normals.copy()
    smoothed_centres = centres.copy()
    done = 0
    for index, target in enumerate(rounds):
        while done < target:
            field = operator @ field
            smoothed_centres = operator @ smoothed_centres
            done += 1
        dispersion[index] = 1.0 - np.linalg.norm(field, axis=1)
        offset[index] = np.einsum("ij,ij->i", centres - smoothed_centres, normals)
        sys.stdout.write("\r  radius %6.2fmm (%5d rounds)" % (radii_mm[index], target))
        sys.stdout.flush()
    sys.stdout.write("\n")

    # Response = d(dispersion)/d(log r). The peak is where the ball first contains the
    # whole feature; past that the surface inside is just more of the same and the curve
    # flattens, which is what makes the peak a size rather than an amount of roughness.
    log_r = np.log(np.asarray(radii_mm))
    response = np.gradient(dispersion, log_r, axis=0)
    peak = np.argmax(response, axis=0)
    characteristic = np.asarray(radii_mm)[peak]
    # Sign as a BAND-PASS, not a raw offset. The raw offset at a 15mm radius says a
    # smooth panel on this shell bulges outward, because the shell as a whole does --
    # measured, it labelled 89% of the panel a ridge and 58% of the ribs flat, exactly
    # backwards, and found no grooves at all. Subtracting the offset at a coarser
    # radius cancels whatever the object is doing globally and leaves only what this
    # face does against its own surroundings. Normalised by the face's own scale, so
    # it stays a shape rather than a size: +1 a ridge or boss, -1 a groove or throat.
    rows = np.arange(count)
    coarser = np.minimum(peak + 2, len(radii_mm) - 1)
    local = offset[peak, rows] - offset[coarser, rows]
    signed = local / np.maximum(characteristic, 1e-6)
    return {"radii_mm": np.asarray(radii_mm, dtype=np.float32),
            "dispersion": dispersion, "response": response.astype(np.float32),
            "characteristic_mm": characteristic.astype(np.float32),
            "signed": signed.astype(np.float32),
            "mean_edge_mm": np.float32(edge)}


def colour_by_scale(characteristic, radii):
    """Small things cool, large things warm, on a log ramp."""
    low, high = float(np.log(radii[0])), float(np.log(radii[-1]))
    t = np.clip((np.log(np.maximum(characteristic, 1e-6)) - low) / max(high - low, 1e-9),
                0.0, 1.0)
    return np.stack([np.clip(1.6 * t - 0.3, 0, 1),
                     np.clip(1.0 - np.abs(2.0 * t - 1.0) * 1.2, 0, 1),
                     np.clip(1.3 - 1.8 * t, 0, 1)], axis=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--scales", type=int, default=14)
    parser.add_argument("--peaks", type=float, default=None,
                        help="highlight faces whose characteristic scale is nearest "
                             "this radius in mm, wherever they are on the model")
    parser.add_argument("--tolerance", type=float, default=0.35,
                        help="log-radius half-width of the --peaks band")
    parser.add_argument("--views", default="iso,front")
    args = parser.parse_args()

    session = np.load(os.path.join(args.session, "session.npz"))
    path = os.path.join(args.session, INDEX)

    if args.peaks is None or not os.path.exists(path):
        print("building scale-space index over %d faces" % len(session["faces"]))
        index = build(session, scales=args.scales)
        np.savez_compressed(path, **index)
        print("mean edge %.3fmm; radii %.2f .. %.2fmm"
              % (index["mean_edge_mm"], index["radii_mm"][0], index["radii_mm"][-1]))
        characteristic = index["characteristic_mm"]
        for low, high in zip(index["radii_mm"][:-1], index["radii_mm"][1:]):
            share = float(((characteristic >= low) & (characteristic < high)).mean())
            if share > 0.01:
                print("  %5.2f-%5.2fmm  %5.1f%% of faces" % (low, high, 100 * share))
    index = np.load(path)

    import trimesh
    faces = session["faces"]
    mesh = trimesh.Trimesh(vertices=session["vertices"], faces=faces, process=False)
    out = os.path.join(args.session, "scalespace")
    os.makedirs(out, exist_ok=True)

    if args.peaks is not None:
        characteristic = index["characteristic_mm"]
        band = np.abs(np.log(np.maximum(characteristic, 1e-6)) - np.log(args.peaks))
        hit = band <= args.tolerance
        colours = np.tile(np.array([0.88, 0.88, 0.90]), (len(faces), 1))
        colours[hit] = (1.0, 0.30, 0.10)
        tag = "peaks-%.1fmm" % args.peaks
        print("%.2fmm +/- %.2f log: %.2f%% of surface area"
              % (args.peaks, args.tolerance,
                 100 * session["areas"][hit].sum() / session["areas"].sum()))
    else:
        colours = colour_by_scale(index["characteristic_mm"], index["radii_mm"])
        tag = "characteristic"

    for view in args.views.split(","):
        if view.strip() in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view.strip()], 900)
            raster.save_png(os.path.join(out, "%s-%s.png" % (tag, view.strip())), image)
    print("  %s/%s-*.png" % (out, tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
