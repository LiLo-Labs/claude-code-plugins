"""Build a Monte Carlo ensemble of segmentations and cache it beside the session.

A single segmentation is one arbitrary draw. Its patch boundaries depend on where
the seeds happened to land and on how many patches were asked for, and a selection
grown on it inherits every one of those accidents with no way to tell which parts
of the answer were structural and which were luck.

So draw many. Each run re-seeds and re-scales: the patch count is jittered
log-uniformly around the target, because scale is a zoom level and the right zoom
for a feature is not known in advance. Every run is a different, equally defensible
tiling of the same surface.

What this buys is measurable later, in face space. Patch ids mean nothing across
runs -- patch 40 in one run is not patch 40 in the next -- but a *face* is the same
face in every run, so "how often was this face selected" is a well-posed question
and "how often did these two faces land together" is the overlap statistic the
consensus selection is built on.

Cache it once. The sweep is the expensive part (minutes); every later click reads
the ensemble and costs seconds.
"""

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib.mesh_slic import superpatches
from oversegment import load_fields


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--runs", type=int, default=16,
                        help="how many segmentations to draw")
    parser.add_argument("--patches", type=int, default=2500,
                        help="target patch count each run is jittered around")
    parser.add_argument("--jitter", type=float, default=0.6,
                        help="log-uniform scale spread; 0.6 means roughly "
                             "0.6x to 1.6x the target patch count")
    parser.add_argument("--iterations", type=int, default=1,
                        help="re-seed rounds per run; 1 keeps the sweep affordable "
                             "and the ensemble averages out the roughness")
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--output", default=None,
                        help="default: <session>/mc_labels.npy")
    args = parser.parse_args()

    session_path = os.path.join(args.session, "session.npz")
    if not os.path.exists(session_path):
        parser.error("no session.npz in %s; run inspect_model.py first" % args.session)
    session = np.load(session_path)
    faces = session["faces"]
    centres = session["vertices"][faces].mean(axis=1)
    fields = load_fields(args.session, session)

    output = args.output or os.path.join(args.session, "mc_labels.npy")
    rng = np.random.default_rng(args.seed)
    spread = abs(float(args.jitter))
    labels = np.zeros((args.runs, len(faces)), dtype=np.int32)

    print("drawing %d segmentations of %d faces around ~%d patches"
          % (args.runs, len(faces), args.patches))
    start = time.time()
    for run in range(args.runs):
        scale = int(round(args.patches * float(np.exp(rng.uniform(-spread, spread)))))
        scale = max(16, scale)
        labels[run] = superpatches(centres, session["normals"], session["pairs"],
                                   target_patches=scale, fields=fields,
                                   iterations=args.iterations,
                                   seed=int(rng.integers(1, 2 ** 31 - 1)))
        print("  run %2d/%d  %5d patches  %.0fs"
              % (run + 1, args.runs, labels[run].max() + 1, time.time() - start))
        sys.stdout.flush()

    np.save(output, labels)
    print("wrote %s (%d runs x %d faces, %.0f MB)"
          % (output, args.runs, len(faces), labels.nbytes / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
