#!/usr/bin/env python3
"""Outfit and skin variants, by moving whole shading ramps.

Two steps, because naming a ramp is the part worth looking at:

    variants.py --input hero.png --out work/ --describe
        writes work/ramps/ramp-N.png -- the character with one ramp lit and the
        rest dimmed -- and prints each ramp's share and position. Look at those,
        then name them.

    variants.py --input hero.png --out work/ --name 0=skin,1=cloak,2=boots \\
                --variant '{"cloak": {"hue": 0, "saturation": 1.15}}' \\
                --variant-name red-cloak
        writes work/hero-red-cloak.png, which is an ordinary character image.
        Feed it straight back into build.py to get that variant's sheet.
"""

import argparse
import json
import os
import sys

import _bootstrap  # noqa: F401
from spritepipe import image, ingest, palette, variants


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--describe", action="store_true",
                        help="list the ramps and write the ramp atlas, then stop")
    parser.add_argument("--name", default="",
                        help="comma list of id=name, e.g. 0=skin,1=cloak")
    parser.add_argument("--variant", help="JSON object of ramp name -> change")
    parser.add_argument("--variant-name", default="variant")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    reference = ingest.ingest(args.input)
    ramps = palette.ramps(reference.palette, reference.pixels)
    described = variants.describe(reference.pixels, ramps)

    names = {}
    for pair in args.name.split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            names[int(key.strip())] = value.strip()

    if args.describe or not args.variant:
        atlas_dir = os.path.join(args.out, "ramps")
        os.makedirs(atlas_dir, exist_ok=True)
        written = []
        scale = max(1, min(8, 128 // max(1, reference.size[1])))
        for ramp, frame in zip(ramps, variants.ramp_atlas(reference.pixels, ramps)):
            path = os.path.join(atlas_dir, "ramp-%d.png" % ramp["id"])
            image.save(image.scale_nearest(frame, scale), path)
            written.append(path)
        report = {"ramps": described, "atlas": written, "names": names}
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("%d ramps in %s (look at %s before naming them):"
                  % (len(ramps), args.input, atlas_dir))
            for entry in described:
                print("  ramp %-2d %5.1f%% of the sprite  %d shade%s  at %-12s %s"
                      % (entry["id"], entry["share"] * 100, entry["shades"],
                         "" if entry["shades"] == 1 else "s",
                         entry.get("centroid", "-"),
                         " ".join("#%02x%02x%02x" % tuple(c[:3])
                                  for c in entry["colours"])))
                print("          %s" % os.path.join(atlas_dir,
                                                    "ramp-%d.png" % entry["id"]))
        return 0

    try:
        spec = json.loads(args.variant)
    except json.JSONDecodeError as error:
        print("--variant is not valid JSON: %s" % error, file=sys.stderr)
        return 2

    try:
        pixels, report = variants.variant(reference.pixels, spec, names, ramps)
    except ValueError as error:
        print("variant failed: %s" % error, file=sys.stderr)
        return 2

    stem = os.path.splitext(os.path.basename(args.input))[0]
    path = os.path.join(args.out, "%s-%s.png" % (stem, args.variant_name))
    # Written at the SOURCE's resolution, not the working one, so the variant is
    # a drop-in replacement for the file the user started with.
    image.save(image.scale_nearest(pixels, reference.scale)
               if reference.scale > 1 else pixels, path)
    report["written"] = path

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("%s: %d of %d colours changed across %d ramps"
              % (path, report["colours_changed"],
                 len(reference.palette), report["ramps"]))
        if report["unmatched"]:
            print("  ! %s" % report.get("hint", report["unmatched"]))
        print("  feed it back in: build.py --input %s --out <dir>" % path)
    return 1 if report["unmatched"] else 0


if __name__ == "__main__":
    sys.exit(main())
