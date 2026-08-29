"""Edge strength = the coarsest scale at which two faces end up in different patches.

Counting how often an ensemble puts two faces together is dominated by whichever
scales are coarsest: cut a model into 400 pieces and almost every adjacent pair
lands together, so agreement sits near 1.0 whether or not there is an edge between
them. Measured on the shell, 0.0% of pairs scored below the 0.5 blocking threshold,
so blocking on that statistic blocked nothing at all.

The informative question is at what scale they first come apart. A crease between
a barnacle field and the rib beside it separates them even at 400 patches, because
no sensible coarse segmentation would span it. A boundary that only appears at
13,000 patches is the segmentation running out of things to cut, not a feature.

So sweep from coarse to fine and record, per adjacent pair, the coarsest scale
that separated them. Low number means a major edge. Pairs that never separate are
left as infinity, which reads correctly as "no edge here at any scale".
"""

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts"))

from paintlib.mesh_slic import superpatches

DEFAULT_SCALES = [250, 400, 650, 1000, 1500, 2200, 3200, 4600]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True,
                        help="session directory from inspect_model.py")
    parser.add_argument("--scales", default=",".join(str(s) for s in DEFAULT_SCALES),
                        help="patch counts to sweep, coarse first")
    parser.add_argument("--repeats", type=int, default=3,
                        help="runs per scale; a pair counts as separated at a scale "
                             "when a majority of its runs separate it")
    parser.add_argument("--output", default=None,
                        help="default: <session>/edge_strength.npy")
    args = parser.parse_args()

    scales = [int(part) for part in args.scales.split(",") if part.strip()]
    session_path = os.path.join(args.session, "session.npz")
    if not os.path.exists(session_path):
        parser.error("no session.npz in %s; run inspect_model.py first" % args.session)
    session = np.load(session_path)
    pairs = session["pairs"]
    centres = session["vertices"][session["faces"]].mean(axis=1)

    relief_path = os.path.join(args.session, "relief.npy")
    fields = {"relief": np.load(relief_path) if os.path.exists(relief_path)
              else np.zeros(len(session["faces"])),
              "occlusion": session["occlusion"],
              "roughness": session["roughness"]}

    output = args.output or os.path.join(args.session, "edge_strength.npy")
    log_path = os.path.join(args.session, "edgestrength.log")
    log = open(log_path, "w", buffering=1)

    def say(line):
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        log.write(line + "\n")

    # For each pair, how many of the runs at each scale separated it.
    separated = {scale: np.zeros(len(pairs), dtype=np.int16) for scale in scales}
    total_runs = len(scales) * args.repeats
    start = time.time()
    done = 0
    for scale in scales:
        for repeat in range(args.repeats):
            labels = superpatches(centres, session["normals"], pairs,
                                  target_patches=scale, fields=fields, iterations=1,
                                  seed=5501 + done * 53 + repeat)
            separated[scale] += labels[pairs[:, 0]] != labels[pairs[:, 1]]
            done += 1
            say("run %2d/%d  scale %4d  %.0fs" % (done, total_runs, scale,
                                                  time.time() - start))

    # The coarsest scale that separated the pair in a majority of its runs. Scales
    # are swept coarse first, so the minimum over the scales that separated it is
    # exactly that; pairs no scale separated stay at infinity.
    strength = np.full(len(pairs), np.inf)
    for scale in scales:
        majority = separated[scale] > (args.repeats / 2.0)
        strength = np.minimum(strength, np.where(majority, float(scale), np.inf))
    np.save(output, strength)

    say("done in %.0fs; %.1f%% of pairs separate at some scale"
        % (time.time() - start, 100 * np.isfinite(strength).mean()))
    for scale in scales:
        say("  separated by scale %4d: %6.2f%% of pairs"
            % (scale, 100 * (strength <= scale).mean()))
    say("wrote %s" % output)
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
