"""Ten times the runs, across ten scales -- the 'more zoom levels and overlaps' pass.

A patch scale is a zoom level: at 400 patches a whole rib is one object, at 12,000
a single barnacle cone is several. A boundary that survives across that whole range
is a real edge; one that appears only at a single scale is an artefact of how the
surface happened to be cut.
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

SCALES = [400, 700, 1200, 1800, 2600, 3600, 5000, 7000, 9500, 13000]
REPEATS = 6
together = np.zeros(len(pairs), dtype=np.int32)
runs = 0
start = time.time()
log = open(os.path.join(S, "ensemble10x.log"), "w", buffering=1)
for scale in SCALES:
    for repeat in range(REPEATS):
        labels = superpatches(centres, sess["normals"], pairs, target_patches=scale,
                              fields=fields, iterations=1,
                              seed=1009 + runs * 37 + repeat)
        together += labels[pairs[:, 0]] == labels[pairs[:, 1]]
        runs += 1
        log.write("run %2d/%d  scale %5d  %d patches  %.0fs\n"
                  % (runs, len(SCALES) * REPEATS, scale, int(labels.max()) + 1,
                     time.time() - start))
        np.save(os.path.join(S, "support10x.npy"), together / float(runs))
log.write("done: %d runs over %d scales in %.0fs\n" % (runs, len(SCALES), time.time() - start))
support = together / float(runs)
np.save(os.path.join(S, "support10x.npy"), support)
log.write("boundary support: %.1f%% of pairs agreed in every run, %.1f%% in under half\n"
          % (100 * (support == 1).mean(), 100 * (support < 0.5).mean()))
log.close()
