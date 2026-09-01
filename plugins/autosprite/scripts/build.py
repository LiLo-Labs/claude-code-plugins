#!/usr/bin/env python3
"""Build a sprite sheet from one character image, end to end.

    build.py --input hero.png --out hero-sprites/ \
             --animations platformer --directions 4 --backend claude
"""

import argparse
import json
import os
import sys

import _bootstrap  # noqa: F401
from spritepipe import motion, pipeline, props


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="the character image")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--name", help="sheet name; defaults to the input's stem")
    parser.add_argument("--reference-front", dest="front",
                        help="a front view, which makes the S direction exact")
    parser.add_argument("--reference-back", dest="back",
                        help="a back view, which makes the N direction exact")

    parser.add_argument("--animations", default="full",
                        help="comma list of animations or a set (%s); props use (%s)"
                             % ("/".join(sorted(motion.PRESET_SETS)),
                                "/".join(sorted(props.PRESET_SETS))))
    parser.add_argument("--custom", help="JSON file of extra keyframe animations")
    parser.add_argument("--directions", default="1",
                        help="1, 2, 4, 8 or a comma list like E,SE,S")
    parser.add_argument("--kind", default="character", choices=("character", "prop"),
                        help="props rig as one piece and use the prop animations")

    parser.add_argument("--backend", default="template", choices=("template", "claude"),
                        help="template rigs from the silhouette; claude looks at the art")
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--class", dest="character_class", default="auto",
                        choices=("auto", "humanoid", "creature", "prop"))
    parser.add_argument("--facing", default="right", choices=("right", "left"))
    parser.add_argument("--intent", default="",
                        help="what the character is, in a few words; sharpens the rig")

    parser.add_argument("--layout", default="grid", choices=("grid", "packed"))
    parser.add_argument("--padding", type=int, default=1)
    parser.add_argument("--extrude", type=int, default=1)
    parser.add_argument("--scale", type=int, default=1,
                        help="nearest-neighbour upscale of the finished sheet")
    parser.add_argument("--power-of-two", action="store_true")
    parser.add_argument("--engines", default="all",
                        help="comma list, or 'all' / 'web'")
    parser.add_argument("--tolerance", type=int, default=12,
                        help="background flood tolerance")
    parser.add_argument("--no-native", action="store_true",
                        help="do not undo an upscale in the source art")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()

    custom = motion.load_custom(args.custom) if args.custom else None

    try:
        build = pipeline.build_sheet(
            args.input, args.out,
            animations=[a.strip() for a in args.animations.split(",") if a.strip()],
            direction_set=args.directions, backend=args.backend, model=args.model,
            character_class=args.character_class, facing=args.facing,
            intent=args.intent, name=args.name, layout=args.layout,
            padding=args.padding, extrude=args.extrude, scale=args.scale,
            power_of_two=args.power_of_two,
            engines=[e.strip() for e in args.engines.split(",") if e.strip()],
            front=args.front, back=args.back, tolerance=args.tolerance,
            native=not args.no_native, custom_animations=custom, kind=args.kind)
    except (ValueError, RuntimeError) as error:
        print("build failed: %s" % error, file=sys.stderr)
        return 2

    report = dict(build.report)
    report["written"] = build.written
    report["previews"] = build.previews
    report["verification"] = build.verification.to_dict()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_human(build, report))
    return 0 if build.verification.ok else 1


def _human(build, report):
    lines = []
    side = report["references"]["side"]
    lines.append("source   %dx%d -> %dx%d working, %d colours (%s)"
                 % (side["source_size"][0], side["source_size"][1],
                    side["working_size"][0], side["working_size"][1],
                    side["palette_size"], side["art_kind"]))
    if side.get("pixel_scale", 1) > 1:
        lines.append("         %s" % side["pixel_scale_note"])
    rig = build.rigs["side"]
    lines.append("rig      %s, %d parts, by %s"
                 % (rig.character_class, len(rig.parts), report["rig_actor"]))
    for note in rig.notes:
        lines.append("         %s" % note)
    lines.append("sheet    %dx%d %s, %d clips, %d frames"
                 % (report["sheet"]["size"][0], report["sheet"]["size"][1],
                    report["sheet"]["layout"], report["sheet"]["clips"],
                    report["sheet"]["frames"]))
    lines.append("")
    for clip in build.sheet.clips:
        lines.append("  %-16s %2d frames  %4gfps  %-5s  %s"
                     % (clip.key, len(clip.frames), clip.fps,
                        "loop" if clip.loop else "once", clip.fidelity))
    lines.append("")
    for key in ("sheet", "atlas", "rig", "frames_zip"):
        if key in build.written:
            lines.append("  %-10s %s" % (key, build.written[key]))
    engines = [k for k in build.written
               if k not in ("sheet", "atlas", "rig", "frames_zip",
                            "frames_zip_count", "rpgmaker_report")]
    if engines:
        lines.append("  %-10s %s" % ("engines", ", ".join(sorted(engines))))
    if build.previews.get("contact_sheet"):
        lines.append("  %-10s %s and %d GIFs in %s"
                     % ("preview", build.previews["contact_sheet"],
                        len(build.previews["gifs"]),
                        os.path.dirname(build.previews["contact_sheet"])))
    rpg = build.written.get("rpgmaker_report")
    if rpg and not rpg.get("written"):
        lines.append("  %-10s not written: %s" % ("rpgmaker", rpg["reason"]))
    if report["warnings"]:
        lines.append("")
        for warning in report["warnings"]:
            lines.append("  ! %s" % warning)
    lines.append("")
    lines.append(build.verification.report())
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
