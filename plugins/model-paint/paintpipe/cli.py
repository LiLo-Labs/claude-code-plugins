"""Command line entry point for a full run."""

import argparse
import json
import os

from . import entities as entities_module
from . import inputs as inputs_module
from . import pipeline as pipeline_module
from . import policy as policy_module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, action="append")
    parser.add_argument("--out", required=True)
    parser.add_argument("--intent", default="")
    parser.add_argument("--size-mm", type=float, default=None,
                        help="real printed height; inferred and flagged when absent")
    parser.add_argument("--pixels", type=int, default=700)
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--rigs", default="zenithal,raking_a,flat")
    args = parser.parse_args(argv)

    bundle = inputs_module.ObjectBundle(paths=args.input, intent=args.intent,
                                        target_size_mm=args.size_mm)
    profile = inputs_module.PainterProfile()
    manifest, store, field, colours = pipeline_module.run(
        bundle, profile, policy_module.DEFAULT, root=args.out,
        rigs=tuple(args.rigs.split(",")), pixels=args.pixels, max_rounds=args.rounds)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "scheme.json"), "w") as handle:
        # Everything in the manifest passes through the same plain-value conversion the
        # entity records use, so a numpy scalar or array never reaches the encoder.
        json.dump(entities_module._plain(manifest), handle, indent=2)
    print("wrote %s" % os.path.join(args.out, "scheme.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
