"""Edge strength = the coarsest scale at which two faces end up in different patches.

Counting how often an ensemble puts two faces together is dominated by whichever
scales are coarsest: cut a model into 400 pieces and almost every adjacent pair
lands together, so agreement sits near 1.0 whether or not there is an edge between
them.

The informative question is at what scale they first come apart. A crease between
a barnacle field and the rib beside it separates them even at 400 patches, because
no sensible coarse segmentation would span it. A boundary that only appears at
13,000 patches is the segmentation running out of things to cut, not a feature.

So sweep from coarse to fine and record, per adjacent pair, the coarsest scale
that separated them. Low number means a major edge.
"""
import sys, os, time, numpy as np
sys.path.insert(0, "/home/user/claude-code-plugins/plugins/model-paint/scripts")
from paintlib.mesh_slic import superpatches

S = "/tmp/claude-0/-home-user-claude-code-plugins/dd7e4c10-659b-5f82-8ae8-30b06c7449d3/scratchpad/shell/session"
sess = np.load(os.path.join(S, "session.npz"))
V, F, pairs = sess["vertices"], sess["faces"], sess["pairs"]
centres = V[F].mean(axis=1)
fields = {"relief": np.load(os.path.join(S, "relief.npy")),
          "occlusion": sess["occlusion"], "roughness": sess["roughness"]}

SCALES = [250, 400, 650, 1000, 1500, 2200, 3200, 4600]
REPEATS = 3
# For each pair, how many of the runs at each scale separated it.
separated = {scale: np.zeros(len(pairs), dtype=np.int16) for scale in SCALES}
log = open(os.path.join(S, "edgestrength.log"), "w", buffering=1)
start = time.time()
done = 0
for scale in SCALES:
    for repeat in range(REPEATS):
        labels = superpatches(centres, sess["normals"], pairs, target_patches=scale,
                              fields=fields, iterations=1, seed=5501 + done * 53 + repeat)
        separated[scale] += labels[pairs[:, 0]] != labels[pairs[:, 1]]
        done += 1
        log.write("run %2d/%d  scale %4d  %.0fs\n"
                  % (done, len(SCALES) * REPEATS, scale, time.time() - start))

# Coarsest scale that separated the pair in a majority of its runs.
strength = np.full(len(pairs), np.inf)
for scale in SCALES:
    majority = separated[scale] > (REPEATS / 2.0)
    strength = np.where(np.isfinite(strength), strength,
                        np.where(majority, float(scale), np.inf))
    strength = np.minimum(strength, np.where(majority, float(scale), np.inf))
np.save(os.path.join(S, "edge_strength.npy"), strength)
finite = np.isfinite(strength)
log.write("done in %.0fs; %.1f%% of pairs separate at some scale\n"
          % (time.time() - start, 100 * finite.mean()))
for scale in SCALES:
    log.write("  separated by scale %4d: %6.2f%% of pairs\n"
              % (scale, 100 * (strength <= scale).mean()))
log.close()
