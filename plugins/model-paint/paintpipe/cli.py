"""One command: a mesh and a brief in, a painted 3MF and guide renders out.

This is the plugin's interface. A user does not write Python and does not get a
bespoke script; they name a model, say what it is, and list the filament they
have loaded. Everything else happens behind that -- 3D segmentation, agentic
naming, the recovery ladder, unconstrained colour, palette limiting, the
critic, and a geometry-verified 3MF export (see pipeline.py for the order and
the reasons).

    python3 -m paintpipe.cli --input dragon.stl --intent "a baby dragon" \
        --colors "white:#FFFFFF, black:#000000, orange:#FF8000, grey:#808080" \
        --size-mm 187 --out dragon-paint/

The two colour stages are kept separate in the output because they answer
different questions. The CONTINUOUS renders show what the model should look
like and are the honest test of whether the segmentation found real parts. The
LIMITED and FINAL renders show what this printer can actually lay down.
Judging the second without the first tells you nothing about which stage a
disappointment came from.
"""

import argparse


def parse_colors(text):
    """`name:#RRGGBB, ...` or just `#RRGGBB, ...` into Paint objects."""
    from . import inputs as inputs_module
    from .agents import _hex_to_lab
    out = []
    for index, chunk in enumerate((text or "").split(",")):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            name, value = chunk.split(":", 1)
        else:
            name, value = "filament-%d" % (index + 1), chunk
        name, value = name.strip(), value.strip()
        out.append(inputs_module.Paint("FIL-%d" % (index + 1), name,
                                       _hex_to_lab(value)))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="STL or 3MF")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--intent", default="",
                        help="what the piece is, in the user's own words; this "
                             "is the cheapest disambiguation available for a "
                             "grey render")
    parser.add_argument("--size-mm", type=float, default=None,
                        help="real printed height; inferred and flagged when absent")
    parser.add_argument("--colors", default="",
                        help="loaded filaments as 'name:#RRGGBB, ...'; the LAST "
                             "one is the default body filament. Without any, "
                             "the run produces a design rather than a plan and "
                             "says so")
    parser.add_argument("--nozzle-mm", type=float, default=0.4)
    parser.add_argument("--viewing-mm", type=float, default=500.0)
    parser.add_argument("--pixels", type=int, default=900,
                        help="naming render resolution")
    parser.add_argument("--cap", type=int, default=250,
                        help="most atoms offered in one id render; a "
                             "legibility bound, never a boundary")
    parser.add_argument("--workers", type=int, default=4,
                        help="concurrent vision calls")
    parser.add_argument("--model", default="claude-opus-5",
                        help="vision model for the naming, painter and critic "
                             "agents")
    parser.add_argument("--no-vision", action="store_true",
                        help="segment only and write the atom atlas; naming "
                             "is an act of looking, so no painting happens")
    parser.add_argument("--repaint", default="",
                        help="'part:filament, ...' -- re-map a finished run in "
                             "--out to different filaments and re-export, "
                             "without re-running any vision")
    args = parser.parse_args(argv)

    from . import pipeline
    if args.repaint:
        overrides = {}
        for chunk in args.repaint.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            part, _, filament = chunk.partition(":")
            overrides[part.strip()] = filament.strip()
        pipeline.repaint(args.input, args.out, parse_colors(args.colors),
                         overrides, size_mm=args.size_mm)
        return 0
    manifest = pipeline.paint(
        args.input, args.out, intent=args.intent, size_mm=args.size_mm,
        palette=parse_colors(args.colors), model=args.model,
        nozzle_mm=args.nozzle_mm, viewing_mm=args.viewing_mm,
        pixels=args.pixels, cap=args.cap, workers=args.workers,
        no_vision=args.no_vision)
    return 0 if manifest else 1


if __name__ == "__main__":
    raise SystemExit(main())
