"""Tile the surface into patches, and cache the result beside the session.

Every later step -- describing patches, clicking one to select a feature, painting
what was selected -- reads `mesh_patches.npy` from the session directory. Until now
the only way to produce it was a multi-line `python3 -c` incantation quoted in the
handoff, which is easy to get subtly wrong and impossible to re-run from memory.

The patch count is the one parameter that matters, and it is a zoom level rather
than a quality setting: at 400 patches a whole rib is a single object, at 13,000 a
single barnacle cone is split across several. A feature is only cleanly separable
near its own scale, so the right count depends on what is being selected, not on
the model. 2,500 is a sensible default for a detailed 600k-triangle sculpt.
"""

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib.mesh_slic import superpatches


def load_fields(session_dir, session):
    """The per-face signals segmentation trades off against distance.

    `relief` is cached beside the session by whichever step needed it first; it
    costs about two seconds on 600k faces, so compute it here rather than quietly
    segmenting on a zero field and producing worse patches with no warning.
    """
    relief_path = os.path.join(session_dir, "relief.npy")
    if os.path.exists(relief_path):
        relief = np.load(relief_path)
    else:
        from paintlib.signals import relief as compute_relief
        relief = compute_relief(session["vertices"], session["faces"])
        try:
            np.save(relief_path, relief)
        except OSError:
            pass
    return {"relief": relief,
            "occlusion": session["occlusion"],
            "roughness": session["roughness"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True,
                        help="session directory from inspect_model.py")
    parser.add_argument("--patches", type=int, default=2500,
                        help="roughly how many patches to cut the surface into")
    parser.add_argument("--iterations", type=int, default=2,
                        help="re-seed rounds; 1 is noticeably rougher, 3 rarely helps")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", default=None,
                        help="where to write the labels "
                             "(default: <session>/mesh_patches.npy)")
    args = parser.parse_args()

    session_path = os.path.join(args.session, "session.npz")
    if not os.path.exists(session_path):
        parser.error("no session.npz in %s; run inspect_model.py first" % args.session)
    session = np.load(session_path)

    faces = session["faces"]
    centres = session["vertices"][faces].mean(axis=1)
    fields = load_fields(args.session, session)

    output = args.output or os.path.join(args.session, "mesh_patches.npy")
    print("segmenting %d faces into ~%d patches" % (len(faces), args.patches))
    start = time.time()
    labels = superpatches(centres, session["normals"], session["pairs"],
                          target_patches=args.patches, fields=fields,
                          iterations=args.iterations, seed=args.seed)
    np.save(output, labels)

    # Report what actually came out, not what was asked for. A patch count well
    # under the target, or a patch covering a large share of the surface, means the
    # segmentation failed to divide something and every selection built on it will
    # inherit that.
    areas = session["areas"]
    counts = np.bincount(labels)
    sizes = np.bincount(labels, weights=areas)
    share = sizes / max(float(areas.sum()), 1e-9)
    print("%d patches in %.0fs -> %s" % (len(counts), time.time() - start, output))
    print("  faces per patch: median %d, smallest %d"
          % (int(np.median(counts)), int(counts.min())))
    print("  largest patch:   %.2f%% of surface area" % (100 * share.max()))
    singles = int((counts == 1).sum())
    if singles:
        print("  %d single-face patches" % singles)
    return 0


if __name__ == "__main__":
    sys.exit(main())
