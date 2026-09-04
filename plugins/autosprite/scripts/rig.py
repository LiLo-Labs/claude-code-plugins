#!/usr/bin/env python3
"""Build, inspect, or re-render a rig on its own.

    rig.py --input hero.png --out hero-sprites/ --backend claude
    rig.py --input hero.png --rig hero-sprites/hero.rig.json --preview
"""

import argparse
import json
import os
import sys

import _bootstrap  # noqa: F401
from spritepipe import cutout, image, ingest, rig as rig_module, vision


def overlay(reference, built, scale=6):
    """The reference with every part tinted, so a wrong box is visible at a glance."""
    tints = [(255, 90, 90), (90, 200, 255), (255, 210, 90), (150, 255, 150),
             (220, 140, 255), (255, 160, 60), (120, 255, 220), (255, 120, 180)]
    canvas = image.scale_nearest(reference.pixels, scale)
    for index, part in enumerate(built.parts):
        tint = tints[index % len(tints)]
        x0, y0, x1, y1 = [value * scale for value in part.box]
        for x in range(x0, min(x1, canvas.shape[1])):
            for y in (y0, min(y1, canvas.shape[0]) - 1):
                if 0 <= y < canvas.shape[0]:
                    canvas[y, x] = list(tint) + [255]
        for y in range(y0, min(y1, canvas.shape[0])):
            for x in (x0, min(x1, canvas.shape[1]) - 1):
                if 0 <= x < canvas.shape[1]:
                    canvas[y, x] = list(tint) + [255]
        px, py = part.pivot[0] * scale, part.pivot[1] * scale
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                y, x = py + dy, px + dx
                if 0 <= y < canvas.shape[0] and 0 <= x < canvas.shape[1]:
                    canvas[y, x] = [255, 255, 255, 255]
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--rig", help="an existing rig.json to inspect instead of building")
    parser.add_argument("--backend", default="template", choices=("template", "claude"))
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--class", dest="character_class", default="auto",
                        choices=("auto", "humanoid", "creature", "prop"))
    parser.add_argument("--facing", default="right",
                        choices=("right", "left", "front", "back"))
    parser.add_argument("--intent", default="")
    parser.add_argument("--preview", action="store_true",
                        help="write rig-overlay.png showing every box and pivot")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    reference = ingest.ingest(args.input)

    if args.rig:
        built = rig_module.Rig.load(args.rig)
        path = args.rig
    else:
        backend = vision.make_backend(args.backend, os.path.join(args.out, ".work"),
                                      model=args.model)
        built = backend.rig(reference, args.character_class, args.facing, args.intent)
        name = os.path.splitext(os.path.basename(args.input))[0]
        path = os.path.join(args.out, "%s.rig.json" % name)
        built.save(path)

    problems = rig_module.validate(built)
    pieces = cutout.cut(built, reference.pixels)
    exact = image.equal(pieces.rest(), reference.pixels)

    written = {"rig": path}
    if args.preview:
        overlay_path = os.path.join(args.out, "rig-overlay.png")
        image.save(overlay(reference, built), overlay_path)
        written["overlay"] = overlay_path

    report = {"rig": built.to_dict(), "problems": problems,
              "rest_pose_exact": exact, "strays": pieces.strays,
              "written": written, "reference": reference.summary()}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("%s: %s, %d parts, by %s"
              % (path, built.character_class, len(built.parts), built.actor))
        for part in built.draw_order():
            print("  z=%-3d %-10s %-10s box=%-20s pivot=%s conf=%.2f"
                  % (part.z, part.name, part.role, list(part.box),
                     list(part.pivot), part.confidence))
        for note in built.notes:
            print("  note: %s" % note)
        print("  rest pose reconstructs the source exactly: %s" % exact)
        if pieces.strays:
            share = pieces.strays / max(1, int(image.alpha_mask(reference.pixels).sum()))
            print("  %d opaque pixels (%.0f%%) fall outside every box; the root "
                  "carries them" % (pieces.strays, share * 100))
        for problem in problems:
            print("  PROBLEM: %s" % problem)
        for key, value in written.items():
            print("  %s: %s" % (key, value))
    return 0 if exact and not problems else 1


if __name__ == "__main__":
    sys.exit(main())
