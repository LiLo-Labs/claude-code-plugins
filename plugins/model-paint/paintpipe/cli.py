"""One command: a model and a brief in, a painted 3MF out.

    python3 -m paintpipe.cli --input shell.stl --out shell-paint/ \
        --intent "a giant ammonite barricade on a rocky base" \
        --filaments "bone:#E8E0D0, rust:#8C4A2F, slate:#4A5560, moss:#5A6B3B"

Everything between those two ends is the agent looking at the model:

    LOOK    where to stand, chosen by what the views can see rather than by
            an orbit, so nothing is painted that was never looked at
    SEE     what parts this piece has, how much detail each has, and in what
            order a painter would lay them
    PAINT   one colour at a time, marked in every view that shows it, a little
            each round, looking after every stroke until that colour is right
    REVIEW  the whole painting at once, which is the only pass allowed to say
            that a later coat ruined an earlier one
    CHOOSE  which of your filaments each part prints in

Nothing in here solves for a boundary, fills a gap, or picks an extent. Every
one of those was tried and measured, and every one of them guessed: the merge
tree has no node the size of a rib (0.13% then 33.99% of the surface, nothing
between), and no rule for filling between marks does better than a distance
band. The geometry supplies real edges to snap to and the agent supplies every
decision about which of them matter.
"""

import argparse
import json
import os
import time


def parse_filaments(text):
    """`name:#RRGGBB, ...` or just `#RRGGBB, ...` into Paint objects."""
    from . import inputs as inputs_module
    from .colour import hex_to_lab
    out = []
    for index, chunk in enumerate((text or "").split(",")):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, value = chunk.split(":", 1) if ":" in chunk else (
            "filament-%d" % (index + 1), chunk)
        out.append(inputs_module.Paint("FIL-%d" % (index + 1), name.strip(),
                                       hex_to_lab(value.strip())))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="STL or 3MF")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--intent", default="",
                        help="what the piece is, in your own words -- a grey "
                             "render is genuinely ambiguous and this is the "
                             "cheapest way to say what it is")
    parser.add_argument("--filaments", default="",
                        help="name:#RRGGBB pairs; what is loaded in the printer")
    parser.add_argument("--size-mm", type=float, default=None,
                        help="longest dimension, if the file carries no units")
    parser.add_argument("--views", type=int, default=6,
                        help="how many looks to cover the model with")
    parser.add_argument("--rounds", type=int, default=6,
                        help="looks per colour before moving on")
    parser.add_argument("--max-parts", type=int, default=12)
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--up", default="",
                        help="override the up axis; default is the model's own")
    parser.add_argument("--no-camera-evidence", action="store_true",
                        help="skip the render-only edge pass: faster, blinder")
    args = parser.parse_args(argv)

    import numpy as np
    import trimesh
    from . import (field as field_module, frame as frame_module, loop,
                   policy as policy_module, preview, rig as rig_module,
                   segment3d, vision)

    os.makedirs(args.out, exist_ok=True)
    started = time.time()

    # THE SUBSTRATE, not the file. An STL gives every triangle its own copies
    # of its corners, so a mesh loaded raw has no face adjacency at all and
    # segments to one region per face.
    source = trimesh.load(args.input, process=False, force="mesh")
    frame = frame_module.build_frame(source, target_size_mm=args.size_mm)
    mesh = field_module.LabelField(frame.working_mesh(source), frame,
                                   policy_module.DEFAULT).substrate
    # The model's own up. A print-ready mesh stands the way it will be
    # printed, and assuming (0,0,1) rendered one sample upside down for a
    # whole day of runs.
    up = (tuple(float(v) for v in args.up.split(",")) if args.up
          else tuple(float(v) for v in preview.up_axis(frame)))
    print("%s: %d faces, up %s"
          % (os.path.basename(args.input), len(mesh.faces),
             np.round(up, 3).tolist()))

    evidence = None
    if not args.no_camera_evidence:
        evidence = rig_module.edge_evidence(mesh, pixels=768, log=None)
        print("  edge evidence: %d of %d face pairs seen"
              % (int((evidence["seen"] > 0).sum()), len(evidence["seen"])))
    _atoms, tree = segment3d.atoms(mesh, log=print, evidence=evidence)

    backend = vision.HeadlessBackend(os.path.join(args.out, "cache"),
                                     model=args.model)
    field, labels = loop.paint(backend, mesh, tree, up, args.intent, args.out,
                               views=args.views, rounds=args.rounds,
                               max_parts=args.max_parts, log=print)
    if field is None:
        print("nothing identified; giving up rather than guessing")
        return 1

    # THE CONTINUOUS COLOURING FIRST, and always. Rendered in eleven arbitrary
    # hues a wrong boundary is one stripe among eleven; rendered in the
    # colours the object should really be, a rib in rock colour is obviously
    # wrong. It is the picture to judge the segmentation by, and it costs one
    # call. Collapsing onto four filaments hides the question, because two
    # parts sharing a filament cannot disagree.
    directions = loop.look_from(mesh, tree, up, views=args.views)
    designed = loop.design_colours(backend, mesh, up, field, labels,
                                   args.intent, args.out, directions,
                                   views=len(directions), log=print)
    loop.show(mesh, up, field, labels, args.out, "continuous",
              views=len(directions), directions=directions, pixels=760,
              colours=np.asarray([designed[name] for name in labels]))
    with open(os.path.join(args.out, "continuous.json"), "w") as handle:
        json.dump({name: "#%02X%02X%02X"
                   % tuple(int(round(v * 255)) for v in designed[name])
                   for name in labels}, handle, indent=2)

    filaments = parse_filaments(args.filaments)
    result = {"written": False}
    if filaments:
        chosen = loop.choose_filaments(
            backend, mesh, up, field, labels, [p.name for p in filaments],
            args.intent, args.out, directions, views=len(directions),
            log=print)
        with open(os.path.join(args.out, "filaments.json"), "w") as handle:
            json.dump({"chosen": chosen,
                       "loaded": [p.name for p in filaments]}, handle, indent=2)
        from . import export
        result = export.write_3mf(args.input, args.out, field, labels, chosen,
                                  filaments, log=print)

    print("calls %d  failures %d  $%.2f  %ds"
          % (backend.calls, backend.failures, backend.cost_usd,
             time.time() - started))
    return 0 if (not filaments or result.get("geometry_identical", True)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
