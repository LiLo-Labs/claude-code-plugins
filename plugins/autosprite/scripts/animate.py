#!/usr/bin/env python3
"""Render ONE animation from an existing rig, for iterating on how it looks.

The full build is the wrong loop when the user says "the walk is too stiff".
This renders one clip against a rig that is already settled and writes a GIF, so
a change to the keyframes can be seen in a second rather than a minute.

    animate.py --input hero.png --rig out/hero.rig.json --animation walk --out look/
    animate.py --input hero.png --rig out/hero.rig.json \\
               --custom my-walk.json --animation my-walk --out look/
"""

import argparse
import json
import os
import sys

import _bootstrap  # noqa: F401
from spritepipe import (cutout, ingest, motion, pack, palette, preview, props,
                        render, rig as rig_module, stabilize)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True)
    parser.add_argument("--rig", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--animation", required=True)
    parser.add_argument("--custom", help="JSON file holding the animation, if custom")
    parser.add_argument("--frames", type=int, help="override the frame count")
    parser.add_argument("--fps", type=float, help="override the frame rate")
    parser.add_argument("--scale", type=int, default=0,
                        help="preview upscale; 0 picks one that fits a ~128px GIF")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    reference = ingest.ingest(args.input)
    built = rig_module.Rig.load(args.rig)
    problems = rig_module.validate(built)
    if problems:
        print("the rig is not usable: %s" % "; ".join(problems), file=sys.stderr)
        return 2
    if tuple(built.size) != tuple(reference.size):
        print("the rig is %dx%d but %s works out at %dx%d; rebuild the rig"
              % (built.size[0], built.size[1], args.input,
                 reference.size[0], reference.size[1]), file=sys.stderr)
        return 2

    library = dict(motion.LIBRARY)
    library.update(props.LIBRARY)
    if args.custom:
        for animation in motion.load_custom(args.custom):
            library[animation.name] = animation
    if args.animation not in library:
        print("no animation %r; have %s" % (args.animation, ", ".join(sorted(library))),
              file=sys.stderr)
        return 2

    animation = library[args.animation]
    if args.frames:
        animation.frames = args.frames
    if args.fps:
        animation.fps = args.fps
    animation = motion.scale_motion([animation], built.size[1])[0]

    pieces = cutout.cut(built, reference.pixels)
    margin = render.suggest_margin(built)
    locked = palette.lock(reference.pixels)
    frames = [palette.enforce(render.render_pose(pieces, pose, margin=margin), locked)
              for pose in animation.poses(built)]

    anchor = rig_module.anchor_of(built)
    frames, box, anchor, report = stabilize.stabilise(
        frames, (anchor[0] + margin, anchor[1] + margin))
    clip = pack.Clip(animation.name, frames, animation.fps, animation.loop,
                     anchor=anchor, note=animation.note)

    scale = args.scale or max(1, min(8, 128 // max(1, frames[0].shape[0])))
    gif = os.path.join(args.out, "%s.gif" % animation.name)
    preview.write_gif(frames, gif, animation.fps, animation.loop, scale=scale)
    contact = preview.contact_sheet([clip], os.path.join(args.out, "%s-frames.png"
                                                         % animation.name), scale=scale)

    out = {"animation": animation.name, "frames": len(frames), "fps": animation.fps,
           "loop": animation.loop, "size": report.get("size"),
           "anchor": list(anchor), "holds": stabilize.duplicate_runs(frames),
           "drift": stabilize.anchor_drift(frames, anchor),
           "written": {"gif": gif, "contact_sheet": contact},
           "keyframes": animation.to_dict()}
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print("%s: %d frames at %gfps, %s, %dx%d"
              % (animation.name, len(frames), animation.fps,
                 "looping" if animation.loop else "one-shot",
                 out["size"][0], out["size"][1]))
        if animation.note:
            print("  %s" % animation.note)
        if out["holds"]:
            print("  ! frames repeat: %s -- the motion may be too small for this "
                  "character" % out["holds"])
        print("  %s" % gif)
        print("  %s" % contact)
    return 0


if __name__ == "__main__":
    sys.exit(main())
