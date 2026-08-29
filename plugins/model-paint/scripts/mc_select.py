"""Select by example over a Monte Carlo ensemble: keep what survives resegmentation.

Blocking individual patch edges does not stop a runaway, and the reason is
topological rather than statistical. Measured on the shell: the strongest available
edge statistic blocked 339 of 7,281 patch contacts at its default threshold, while
the patch adjacency graph has mean degree 5.8. Cutting a scattered 5% of edges in a
graph that dense disconnects nothing -- growth simply routes around the gap. To wall
a region off you need the cut edges to close a curve around it, and a scattered
subset never closes. That is the same reason merging on ensemble agreement leaked
until 89% of the model was one patch.

So stop trying to bound a single flood and ask a different question. Growth is a
chain of individually-plausible steps, and a runaway is a chain that drifted: every
link looked fine locally and the far end is on a different feature. What separates
drift from structure is not any one link, it is **stability**.

Draw many segmentations (`mc_ensemble.py`), grow from the same clicked point in each,
and count per face how often it was selected. A face on the feature is reached in
nearly every draw, because it is genuinely similar to the exemplar and genuinely
adjacent. A face out on a drift tail is reached only when a particular chain of
marginal steps happens to line up, and the next resegmentation breaks a link
somewhere along it. The core is stable; the tail is luck, and luck does not repeat.

The vote is taken in face space on purpose. Patch ids are meaningless across runs --
patch 40 in one draw has nothing to do with patch 40 in the next -- but a face is
the same face every time, so overlap between runs is well defined. Faces are the
only common frame the draws share.

This also returns something a single growth cannot: a per-face probability. The
threshold is then an honest dial (how sure must you be) rather than a similarity
tolerance standing in for one, and the profile printed at the end says how much the
answer moves as that dial turns. A selection whose area barely changes between
probability 0.3 and 0.9 is one the ensemble agrees about. One that collapses across
that range was never a feature -- and that is worth knowing before it is painted.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster                                          # noqa: E402
from patch_features import (DESCRIPTORS, CLUSTER_ON, describe_patches,   # noqa: E402
                            standardise)
from patch_select import patch_contacts, grow_local, load_context      # noqa: E402

HIGHLIGHT = (1.0, 0.30, 0.10)
EXEMPLAR = (0.10, 0.85, 1.0)
DIMMED = (0.86, 0.86, 0.88)
PROFILE = (0.3, 0.5, 0.7, 0.9)
COHERENT = 0.7


def vote(session, mc_labels, fields, click_faces, tolerance, jitter, seed,
         progress=None):
    """Per-face selection probability across the ensemble.

    Each run gets its own tolerance, drawn log-uniformly around the requested one.
    A single fixed tolerance is exactly the brittleness this is meant to average
    out: on the recorded trial one value gave sensible selections for nine features
    and ran away on two, and no single better value exists because features differ
    in scale. Jittering it means the vote reflects what is robust to the choice
    rather than what one choice happened to produce.
    """
    faces = session["faces"]
    centres = session["vertices"][faces].mean(axis=1)
    normals, areas, pairs = session["normals"], session["areas"], session["pairs"]
    diagonal = float(np.linalg.norm(np.ptp(session["vertices"], axis=0))) or 1.0
    columns = [DESCRIPTORS.index(name) for name in CLUSTER_ON]
    scale = float(np.sqrt(len(columns)))

    rng = np.random.default_rng(seed)
    votes = np.zeros(len(faces), dtype=np.int32)
    for run, labels in enumerate(mc_labels):
        rows, _stats = describe_patches(labels, centres, normals, areas, fields,
                                        diagonal)
        space = standardise(rows)[:, columns]
        chosen = sorted({int(labels[face]) for face in click_faces})
        distance = np.min([np.linalg.norm(space - space[patch], axis=1)
                           for patch in chosen], axis=0)
        run_tolerance = tolerance * float(np.exp(rng.uniform(-jitter, jitter)))
        similar = distance <= (run_tolerance * scale)

        touching, _ = patch_contacts(labels, pairs, None)
        keep = grow_local(chosen, similar, touching, {}, 0)
        votes += keep[labels]
        if progress:
            progress(run + 1, len(mc_labels), run_tolerance,
                     float(areas[keep[labels]].sum() / areas.sum()))
    return votes / float(len(mc_labels))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True)
    parser.add_argument("--at", action="append", required=True,
                        help="view:x,y pointing at an example; repeat for several")
    parser.add_argument("--name", required=True)
    parser.add_argument("--tolerance", type=float, default=0.30,
                        help="centre of the per-run tolerance draw")
    parser.add_argument("--tolerance-jitter", type=float, default=0.35,
                        help="log-uniform spread of the per-run tolerance")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="keep faces selected in at least this fraction of runs")
    parser.add_argument("--max-share", type=float, default=0.35)
    parser.add_argument("--seed", type=int, default=4242)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    session, _labels, fields = load_context(args.session)
    mc_path = os.path.join(args.session, "mc_labels.npy")
    if not os.path.exists(mc_path):
        raise SystemExit("mc_select: no mc_labels.npy; run mc_ensemble.py first")
    mc_labels = np.load(mc_path)

    vertices, faces, areas = session["vertices"], session["faces"], session["areas"]
    click_faces = []
    for spec in args.at:
        try:
            view, coords = spec.split(":", 1)
            x, y = (int(part) for part in coords.split(","))
        except ValueError:
            parser.error("--at wants view:x,y, got %r" % spec)
        key = "pick_%s" % view
        if key not in session.files:
            parser.error("session has no view %r" % view)
        face = raster.region_at(None, session[key], x, y)
        if face is None:
            parser.error("nothing under %s -- that pixel is background" % spec)
        click_faces.append(int(face))

    def progress(run, total, tolerance, share):
        if not args.quiet:
            sys.stderr.write("  run %2d/%d  tolerance %.2f  %.2f%%\n"
                             % (run, total, tolerance, 100 * share))

    probability = vote(session, mc_labels, fields, click_faces,
                       args.tolerance, args.tolerance_jitter, args.seed, progress)

    mask = probability >= args.threshold
    share = float(areas[mask].sum() / areas.sum()) if mask.any() else 0.0
    if share > args.max_share:
        sys.stderr.write(
            "mc_select: %r matched %.1f%% of the model, past the %.0f%% limit.\n"
            % (args.name, 100 * share, 100 * args.max_share))
        return 2

    parts_path = os.path.join(args.session, "mc_parts.json")
    document = {"parts": []}
    if os.path.exists(parts_path):
        with open(parts_path) as handle:
            document = json.load(handle)
    if any(p["name"] == args.name for p in document.get("parts", [])) and not args.replace:
        sys.stderr.write("mc_select: %r already exists; pass --replace\n" % args.name)
        return 2
    document["parts"] = [p for p in document.get("parts", []) if p["name"] != args.name]
    document["parts"].append({
        "name": args.name, "faces": int(mask.sum()), "area": round(share, 5),
        "threshold": args.threshold, "runs": int(len(mc_labels)),
        "tolerance": args.tolerance, "exemplars": list(args.at),
        "face_indices": [int(v) for v in np.flatnonzero(mask)]})
    with open(parts_path, "w") as handle:
        json.dump(document, handle, indent=2)

    import trimesh
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    colours = np.tile(np.array(DIMMED), (len(faces), 1))
    colours[mask] = HIGHLIGHT
    for face in click_faces:
        colours[face] = EXEMPLAR
    checks = os.path.join(args.session, "selections")
    os.makedirs(checks, exist_ok=True)
    slug = "".join(ch if ch.isalnum() else "-" for ch in args.name).strip("-").lower()
    views = list(dict.fromkeys([spec.split(":", 1)[0] for spec in args.at] + ["iso"]))
    for view in views:
        if view in raster.VIEWS:
            image, _ = raster.render_view(mesh, colours, *raster.VIEWS[view], 900)
            raster.save_png(os.path.join(checks, "mc-%s-%s.png" % (slug, view)), image)

    # Reported in the same shape as patch_select so the trial scorer reads either.
    print("%s: %d patches, %d triangles, %.2f%% of surface area"
          % (args.name, int(mask.sum() and len(np.unique(mc_labels[0][mask]))),
             mask.sum(), 100 * share))
    print("  %d runs, threshold %.2f, tolerance %.2f +/- %.2f"
          % (len(mc_labels), args.threshold, args.tolerance, args.tolerance_jitter))
    profile = "  stability: " + "  ".join(
        "p>=%.1f %.2f%%" % (p, 100 * areas[probability >= p].sum() / areas.sum())
        for p in PROFILE)
    print(profile)

    # Coherence: how much of the selection survives from the majority threshold to
    # near-unanimity. This is the number that says whether the answer is a feature,
    # and area is not -- measured on the shell, five selections whose areas all sat
    # in the sensible band split cleanly on it. The two that looked like one clean
    # thing scored 0.56 and 0.58; the mixture of cracked plate and barnacles scored
    # 0.21, the speckle across three features 0.20, and the fragmentary crack slivers
    # 0.06. A low score means the draws agreed only on where to start, not on what
    # was being selected.
    high = float(areas[probability >= COHERENT].sum())
    kept = float(areas[mask].sum())
    coherence = high / kept if kept > 0 else 0.0
    print("  coherence %.2f  (area at p>=%.1f over area at p>=%.1f)"
          % (coherence, COHERENT, args.threshold))
    if coherence < 0.35:
        print("  ^ low: the draws agree on the seed but not on the feature. "
              "LOOK before painting -- this is usually a mixture or a fragment.")
    print("  check %s/mc-%s-*.png" % (checks, slug))
    return 0


if __name__ == "__main__":
    sys.exit(main())
