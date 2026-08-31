"""Run the paint-look-fix loop on one model. The whole method, from a shell.

    python3 scripts/paint_loop.py samples/scallop-shell-barricade.stl \
        --intent "a scallop shell barricade" --out /tmp/shell-run

Every run has been driven by a throwaway heredoc until now, which is why no
two of them were quite the same experiment. This is the one entry point, so a
result can be reproduced and a regression can be seen.
"""

import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--out", required=True)
    parser.add_argument("--intent", default="")
    parser.add_argument("--views", type=int, default=3)
    parser.add_argument("--rounds", type=int, default=6,
                        help="looks per colour before moving on")
    parser.add_argument("--max-parts", type=int, default=8)
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--up", default="",
                        help="override the up axis; default is the model's own")
    parser.add_argument("--size-mm", type=float, default=None,
                        help="longest dimension in mm, if the file has no units")
    parser.add_argument("--no-camera-evidence", action="store_true",
                        help="skip the render-only edge pass (faster, blinder)")
    args = parser.parse_args(argv)

    import trimesh
    from paintpipe import (field as field_module, frame as frame_module, loop,
                           policy as policy_module, segment3d, vision)

    # THE SUBSTRATE, not the file. An STL stores every triangle with its own
    # copies of its corners, so a mesh loaded raw has no face adjacency at all
    # -- and a segmenter with no adjacency hands back one region per face,
    # which is what a replay of this against a raw load did: 626766 regions on
    # 626766 faces, every claim reaching nothing. pipeline.py welds first; so
    # does this.
    source = trimesh.load(args.input, process=False, force="mesh")
    frame = frame_module.build_frame(source, target_size_mm=args.size_mm)
    working = frame.working_mesh(source)
    mesh = field_module.LabelField(working, frame,
                                   policy_module.DEFAULT).substrate
    # THE MODEL'S OWN UP, not an assumption. A print-ready mesh stands the way
    # it will be printed, and the working mesh lives in a rotated frame, so
    # the file's +Z has to be carried into that frame rather than guessed at
    # as (0,0,1) -- which is what put the shell's flat open top in the middle
    # of every picture.
    from paintpipe import preview
    up = tuple(float(v) for v in args.up.split(",")) if args.up else None
    if up is None:
        up = tuple(float(v) for v in preview.up_axis(frame))
    print("  up axis %s" % (np.round(up, 3).tolist(),))
    os.makedirs(args.out, exist_ok=True)

    started = time.time()
    print("segmenting %s: %d faces welded from %d"
          % (args.input, len(mesh.faces), len(source.faces)))
    # CAMERA EVIDENCE FIRST, as pipeline.py does. Geometry alone does not see a
    # boundary that is soft relief rather than a crease, and every claim below
    # is a union of base regions -- so an edge the substrate never drew cannot
    # be recovered by any amount of looking afterwards. Renders only: no model
    # calls, no cost but time.
    from paintpipe import rig as rig_module
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
    print("calls %d  failures %d  $%.2f  %ds"
          % (backend.calls, backend.failures, backend.cost_usd,
             time.time() - started))
    return 0 if field is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
