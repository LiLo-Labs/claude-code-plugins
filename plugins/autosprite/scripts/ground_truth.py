#!/usr/bin/env python3
"""Measure the CHARACTER clips against an artist's own frames of the same motion.

Sixteen of the thirty clips here are character clips and for a long time not one
had been compared to a real animation: `quality.footprint` existed and worked,
but it needs the artist's own frames and the corpus had those only for a torch
and a flag, both subject clips. Several corpus characters were cut from ANIMATED
sheets, so the ground truth was there the whole time.

Three things this script insists on, each of which changed an answer:

1. **The alignment is proved, not assumed.** The rest pose, rendered and placed
   back into the artist's coordinate space, must be byte-identical to the
   source. Nothing is reported otherwise. On a flag, one pixel out either way
   reads 16.6% or 15.7% where the truth is 11.0%.
2. **Both footprints from the same rest.** Our clips all start from the source
   image and an artist's strips usually do not, so their frame 0 counts as
   motion too. Getting this wrong reported `attack` at 78.9% where the parallel
   figure is 48.4%.
3. **Compared at matched coverage.** `footprint` is one-sided and so rewards
   moving less -- the error rises monotonically with coverage on every clip and
   every character measured -- so the comparable row is the one whose
   disturbed-pixel count comes closest to the artist's.

Two readings are printed, and they answer different questions. **Shipped** is
what a user actually gets, with the coverage beside it so it cannot be read
alone. **Matched** is how clips compare to each other and to the artist. They
are not the same operating point and neither is a substitute: the forest run
ships at 4.8% error while disturbing 78% of what the artist disturbs, and
pushing it to full coverage costs error rather than saving it.

Usage:
    python3 scripts/ground_truth.py path/to/truth.json

where the JSON is a list of subjects:

    [{"name": "sumohulk",
      "source": "/tmp/corpus/platformer-sumohulk-16/frame.png",
      "rig": null,
      "sheet": "/tmp/gt/.../sumoHulk_spriteSheet.png",
      "cell": 16,
      "clips": {"walk": {"rows": [16, 32], "columns": [0,1,2,3,4,5]}}}]
"""
import copy
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from spritepipe import (cutout, image as img, ingest, motion, quality, render,
                        rig as rig_module, skeleton as skel, vision)
from spritepipe.motion import CHANNELS, REST, Track

FACTORS = (0.25, 0.35, 0.5, 0.65, 0.8, 1.0, 1.3, 1.7, 2.2, 3.0)


def cells(sheet_path, rows, columns, cell_width, pad=0):
    """Artist frames from a sheet, cropped exactly as the corpus source was.

    `pad` adds transparent rows above and below, which is how some corpus
    sources were cut -- a strip whose cells are flush with the character's feet
    gets padding so the feet are not on the frame edge. Cropping the artist's
    frames any other way than the source was cropped puts the two in different
    coordinate spaces, and the alignment check will refuse to report.
    """
    sheet = np.array(Image.open(sheet_path).convert("RGBA"))
    top, bottom = rows
    out = []
    for column in columns:
        cell = sheet[top:bottom, column * cell_width:(column + 1) * cell_width]
        if pad:
            canvas = img.blank(cell.shape[0] + 2 * pad, cell.shape[1])
            canvas[pad:pad + cell.shape[0], :] = cell
            cell = canvas
        out.append(cell)
    return out


def quieter(clip, factor):
    """The whole clip smaller, ROOT INCLUDED -- `damp` addresses selectors and a
    root track has none, which silently left `idle` and `jump` untouched the
    first time this sweep was run."""
    out = copy.deepcopy(clip)

    def shrink(track):
        keys = []
        for key in track.to_list():
            new = {"t": key["t"]}
            if "easing" in key:
                new["easing"] = key["easing"]
            for channel in CHANNELS:
                if channel in key:
                    rest = REST[channel]
                    new[channel] = rest + (float(key[channel]) - rest) * factor
            keys.append(new)
        return Track(keys, track.easing, spread=track.spread, along=track.along)

    out.tracks = {name: shrink(track) for name, track in out.tracks.items()}
    if out.root is not None:
        out.root = shrink(out.root)
    return out


class Subject:
    def __init__(self, source_path, rig_path=None, workdir="/tmp/ground-truth",
                 facing="right", character_class="auto"):
        self.raw = np.array(Image.open(source_path).convert("RGBA"))
        self.reference = ingest.ingest(source_path)
        box = img.content_box(self.raw)
        self.content_height = box[3] - box[1]
        # The facing is NOT optional and defaulting it silently is how this
        # harness reported a whole character's numbers off a mirrored rig. The
        # corpus horse is drawn facing LEFT; rigged as right-facing, its head
        # box lands on the rump and its tail box on the head, so `head dy`
        # bobbed the hindquarters and `tail angle` swung the head around like a
        # tail. It still scored 14.7% on the run, because a mirrored quadruped
        # still moves legs and a body and so overlaps the artist's footprint --
        # which is the same lesson `footprint` keeps teaching: it rewards
        # overlap, not correctness. The critic caught it; no measurement here
        # could have.
        self.rig = (rig_module.Rig.from_dict(json.load(open(rig_path)))
                    if rig_path else
                    vision.make_backend("template", workdir).rig(
                        self.reference, character_class=character_class,
                        facing=facing))
        self.cutout = cutout.cut(self.rig, self.reference.pixels)
        self.margin = render.suggest_margin(self.rig)
        self.offset = (self.margin - box[0], self.margin - box[1])
        self.shape = self.raw.shape[:2]

    def place(self, frame):
        out = img.blank(*self.shape)
        img.paste(out, frame, -self.offset[0], -self.offset[1])
        return out

    def aligned(self):
        rest = render.render_pose(self.cutout, skel.Pose(), margin=self.margin)
        return img.equal(self.place(rest), self.raw)

    def frames(self, clip_name, factor=1.0):
        clip = list(motion.scale_motion([motion.LIBRARY[clip_name]],
                                        self.reference.pixels.shape[0]))[0]
        if factor != 1.0:
            clip = quieter(clip, factor)
        poses = skel.posed(self.rig, clip, self.cutout.ground_points())
        return [self.place(render.render_pose(self.cutout, pose,
                                              margin=self.margin))
                for pose in poses]


def measure(subject, clip_name, artist_frames, factors=FACTORS):
    truth = quality.disturbed(artist_frames, subject.raw, shape=subject.shape)
    theirs = int(truth.sum())
    rows = []
    for factor in factors:
        frames = subject.frames(clip_name, factor)
        ours = quality.disturbed(frames, subject.raw, shape=subject.shape)
        total = int(ours.sum())
        wrong = int((ours & ~truth).sum())
        rows.append({"scale": factor, "ours": total, "theirs": theirs,
                     "error": (wrong / total * 100) if total else 0.0,
                     "distinct": len({f.tobytes() for f in frames}),
                     "frames": len(frames)})
    shipped = next(row for row in rows if row["scale"] == 1.0)
    matched = min(rows, key=lambda row: abs(row["ours"] - theirs))
    return shipped, matched, rows


def main(path):
    subjects = json.load(open(path))
    # Two readings, because the error rises with coverage on every clip and
    # character measured: `footprint` alone always favours doing less. The
    # matched column is how clips compare to each other; the shipped column is
    # what a user actually gets.
    print("%-12s %-8s %5s | %8s %8s | %8s %8s %8s"
          % ("subject", "clip", "px", "shipped", "coverage",
             "matched", "at scale", "distinct"))
    failures = 0
    for entry in subjects:
        subject = Subject(entry["source"], entry.get("rig"),
                          facing=entry.get("facing", "right"),
                          character_class=entry.get("class", "auto"))
        if not subject.aligned():
            print("%-12s ALIGNMENT FAILED -- nothing reported" % entry["name"])
            failures += 1
            continue
        for clip_name, spec in entry["clips"].items():
            artist = cells(spec.get("sheet", entry.get("sheet")),
                           spec["rows"], spec["columns"], entry["cell"],
                           entry.get("pad", 0))
            shipped, matched, _rows = measure(subject, clip_name, artist)
            print("%-12s %-8s %5d | %7.1f%% %8.2f | %7.1f%% %8.2f %6d/%d"
                  % (entry["name"], clip_name, subject.content_height,
                     shipped["error"],
                     shipped["ours"] / float(shipped["theirs"] or 1),
                     matched["error"], matched["scale"],
                     matched["distinct"], matched["frames"]))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "truth.json"))
