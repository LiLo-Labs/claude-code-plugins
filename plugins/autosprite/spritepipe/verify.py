"""Prove the sheet says what the pipeline thinks it says.

This exists because every failure mode of a sprite-sheet generator is silent.
A rect off by one row produces a sheet that looks perfect and animates with a
one-pixel jitter. A pivot flipped in the Unity meta produces sprites that sit
underground. An engine file that disagrees with the atlas produces a game that
works in Phaser and not in Godot. None of it is visible in the PNG.

So every check below compares two artefacts that were produced independently and
must agree, and the exit status is the answer:

  RECT      every atlas rect lies inside the sheet and has content
  ZIP       every frame in the ZIP is byte-identical to its crop from the sheet
  PALETTE   every colour in the sheet came from the source art
  ENGINES   every engine file's rects and frame counts match the native atlas
  ANCHOR    every frame of a clip shares one anchor
  REST      the rig's rest pose reconstructs the source image exactly

REST is the one that checks the CUT rather than the export: it proves that
splitting the art into parts lost and duplicated nothing, so every frame is
built from all of the user's pixels and only theirs.

What it does not check is whether the parts are named correctly. A rig that
calls the head a leg reassembles perfectly, because reassembly is about which
pixels went where, not what they were called. Only the preview render answers
that, which is why the skill insists on looking at it.
"""

import io
import json
import os
import re
import zipfile

import numpy as np
from PIL import Image as PILImage

from . import image as img


class Result:
    def __init__(self):
        self.checks = []

    def add(self, name, ok, detail="", skipped=False):
        self.checks.append({"check": name, "ok": bool(ok), "skipped": bool(skipped),
                            "detail": detail})
        return ok

    @property
    def failed(self):
        return [check for check in self.checks if not check["ok"] and not check["skipped"]]

    @property
    def ok(self):
        return not self.failed

    def to_dict(self):
        return {"ok": self.ok, "checks": self.checks,
                "failed": len(self.failed),
                "passed": sum(1 for c in self.checks if c["ok"] and not c["skipped"]),
                "skipped": sum(1 for c in self.checks if c["skipped"])}

    def report(self):
        lines = []
        for check in self.checks:
            mark = "SKIP" if check["skipped"] else ("PASS" if check["ok"] else "FAIL")
            lines.append("%-5s %-8s %s" % (mark, check["check"], check["detail"]))
        summary = self.to_dict()
        lines.append("")
        lines.append("%d passed, %d failed, %d skipped"
                     % (summary["passed"], summary["failed"], summary["skipped"]))
        return "\n".join(lines)


def verify_directory(outdir, name=None, reference_path=None, rig_path=None):
    """Run every check against what is actually on disk."""
    result = Result()
    name = name or _guess_name(outdir)
    if name is None:
        result.add("ATLAS", False, "no *.autosprite.json in %s" % outdir)
        return result

    atlas_path = os.path.join(outdir, "%s.autosprite.json" % name)
    sheet_path = os.path.join(outdir, "%s.png" % name)
    if not os.path.exists(atlas_path) or not os.path.exists(sheet_path):
        result.add("ATLAS", False, "expected %s and %s" % (atlas_path, sheet_path))
        return result

    with open(atlas_path) as handle:
        atlas = json.load(handle)
    sheet = img.load(sheet_path)
    result.add("ATLAS", True, "%s: %d clips, %d frames, sheet %dx%d"
               % (name, len(atlas["clips"]),
                  sum(len(clip["frames"]) for clip in atlas["clips"]),
                  sheet.shape[1], sheet.shape[0]))

    _check_rects(result, atlas, sheet)
    _check_zip(result, outdir, name, atlas, sheet)
    _check_palette(result, sheet, reference_path)
    _check_engines(result, outdir, name, atlas, sheet)
    _check_anchors(result, atlas)
    _check_rest(result, rig_path, reference_path)
    return result


def _guess_name(outdir):
    for entry in sorted(os.listdir(outdir)):
        if entry.endswith(".autosprite.json"):
            return entry[:-len(".autosprite.json")]
    return None


def _check_rects(result, atlas, sheet):
    height, width = sheet.shape[:2]
    outside, empty = [], []
    for clip in atlas["clips"]:
        for frame in clip["frames"]:
            x, y, w, h = frame["x"], frame["y"], frame["w"], frame["h"]
            if x < 0 or y < 0 or x + w > width or y + h > height:
                outside.append(frame["name"])
                continue
            if not img.alpha_mask(sheet[y:y + h, x:x + w]).any():
                empty.append(frame["name"])
    if outside:
        return result.add("RECT", False, "%d rects fall outside the sheet: %s"
                          % (len(outside), ", ".join(outside[:5])))
    if empty:
        return result.add("RECT", False, "%d rects are empty: %s"
                          % (len(empty), ", ".join(empty[:5])))
    total = sum(len(clip["frames"]) for clip in atlas["clips"])
    return result.add("RECT", True, "%d rects inside the sheet, all with content" % total)


def _check_zip(result, outdir, name, atlas, sheet):
    zip_path = os.path.join(outdir, "%s-frames.zip" % name)
    if not os.path.exists(zip_path):
        return result.add("ZIP", True, "no frames ZIP written", skipped=True)

    expected = {frame["name"]: frame for clip in atlas["clips"] for frame in clip["frames"]}
    mismatched, missing = [], []
    with zipfile.ZipFile(zip_path) as archive:
        present = {entry[:-4] for entry in archive.namelist() if entry.endswith(".png")}
        for frame_name, frame in expected.items():
            if frame_name not in present:
                missing.append(frame_name)
                continue
            with archive.open("%s.png" % frame_name) as handle:
                stored = np.array(PILImage.open(io.BytesIO(handle.read())).convert("RGBA"),
                                  dtype=np.uint8)
            crop = sheet[frame["y"]:frame["y"] + frame["h"],
                         frame["x"]:frame["x"] + frame["w"]]
            if not img.equal(stored, crop):
                mismatched.append(frame_name)
        extra = present - set(expected)

    if missing or mismatched or extra:
        return result.add("ZIP", False,
                          "%d missing, %d differ from the sheet, %d extra%s"
                          % (len(missing), len(mismatched), len(extra),
                             (": " + ", ".join((missing + mismatched + sorted(extra))[:5]))
                             if (missing or mismatched or extra) else ""))
    return result.add("ZIP", True, "%d frames byte-identical to their sheet crops"
                      % len(expected))


def _check_palette(result, sheet, reference_path):
    if not reference_path or not os.path.exists(reference_path):
        return result.add("PALETTE", True, "no reference given", skipped=True)
    from . import ingest as ingest_module
    reference = ingest_module.ingest(reference_path)
    allowed = {tuple(int(v) for v in colour) for colour in reference.palette}
    present = img.unique_colors(sheet)
    escaped = [tuple(int(v) for v in colour) for colour in present
               if tuple(int(v) for v in colour) not in allowed]
    if escaped:
        return result.add("PALETTE", False,
                          "%d colours in the sheet are not in the source art: %s"
                          % (len(escaped), escaped[:4]))
    return result.add("PALETTE", True,
                      "all %d sheet colours are drawn from the source's %d"
                      % (len(present), len(allowed)))


_UNITY_SPRITE = re.compile(
    r"- serializedVersion: 2\s*\n\s*name: (?P<name>\S+)\s*\n\s*rect:\s*\n"
    r"\s*serializedVersion: 2\s*\n\s*x: (?P<x>-?\d+)\s*\n\s*y: (?P<y>-?\d+)\s*\n"
    r"\s*width: (?P<w>\d+)\s*\n\s*height: (?P<h>\d+)")
_GODOT_REGION = re.compile(r'id="AtlasTexture_(?P<id>[^"]+)"\]\s*\n'
                           r'atlas = ExtResource\("1_sheet"\)\s*\n'
                           r'region = Rect2\((?P<x>\d+), (?P<y>\d+), '
                           r'(?P<w>\d+), (?P<h>\d+)\)')


def _check_engines(result, outdir, name, atlas, sheet):
    """Every engine file must describe the same rectangles as the native atlas."""
    height = sheet.shape[0]
    expected = {frame["name"]: (frame["x"], frame["y"], frame["w"], frame["h"])
                for clip in atlas["clips"] for frame in clip["frames"]}
    problems, checked = [], []

    for suffix, style in (("texturepacker-hash.json", "hash"),
                          ("phaser.json", "hash"),
                          ("texturepacker-array.json", "array"),
                          ("unreal-paper2d.json", "array"),
                          ("aseprite.json", "array")):
        path = os.path.join(outdir, "%s.%s" % (name, suffix))
        if not os.path.exists(path):
            continue
        with open(path) as handle:
            document = json.load(handle)
        frames = document["frames"]
        entries = (frames.items() if style == "hash"
                   else [(entry["filename"], entry) for entry in frames])
        found = {key[:-4] if key.endswith(".png") else key:
                 (entry["frame"]["x"], entry["frame"]["y"],
                  entry["frame"]["w"], entry["frame"]["h"])
                 for key, entry in entries}
        checked.append(suffix)
        if found != expected:
            problems.append("%s: %d of %d rects differ from the atlas"
                            % (suffix, sum(1 for k in expected if found.get(k) != expected[k]),
                               len(expected)))

    unity_path = os.path.join(outdir, "%s.png.meta" % name)
    if os.path.exists(unity_path):
        checked.append("png.meta")
        found = {}
        for match in _UNITY_SPRITE.finditer(open(unity_path).read()):
            # Unity's origin is bottom-left; convert back to compare.
            found[match.group("name")] = (
                int(match.group("x")), height - int(match.group("y")) - int(match.group("h")),
                int(match.group("w")), int(match.group("h")))
        if found != expected:
            problems.append("png.meta: %d sprites, %d rects differ"
                            % (len(found),
                               sum(1 for k in expected if found.get(k) != expected[k])
                               + len(set(found) - set(expected))))

    godot_path = os.path.join(outdir, "%s.tres" % name)
    if os.path.exists(godot_path):
        checked.append("tres")
        text = open(godot_path).read()
        regions = [(int(m.group("x")), int(m.group("y")),
                    int(m.group("w")), int(m.group("h")))
                   for m in _GODOT_REGION.finditer(text)]
        if sorted(regions) != sorted(expected.values()):
            problems.append("tres: %d regions against %d atlas rects"
                            % (len(regions), len(expected)))
        for clip in atlas["clips"]:
            if ('&"%s"' % clip["key"]) not in text:
                problems.append("tres: no animation named %s" % clip["key"])

    if not checked:
        return result.add("ENGINES", True, "no engine files written", skipped=True)
    if problems:
        return result.add("ENGINES", False, "; ".join(problems))
    return result.add("ENGINES", True, "%s agree with the atlas" % ", ".join(checked))


def _check_anchors(result, atlas):
    drifting = []
    for clip in atlas["clips"]:
        anchors = {tuple(frame["anchor"]) for frame in clip["frames"]}
        if len(anchors) > 1:
            drifting.append("%s has %d different anchors" % (clip["key"], len(anchors)))
    if drifting:
        return result.add("ANCHOR", False, "; ".join(drifting))
    return result.add("ANCHOR", True, "every clip has one anchor across all its frames")


def _check_rest(result, rig_path, reference_path):
    if not rig_path or not reference_path or not os.path.exists(rig_path):
        return result.add("REST", True, "no rig given", skipped=True)
    from . import cutout as cutout_module
    from . import ingest as ingest_module
    from . import rig as rig_module

    reference = ingest_module.ingest(reference_path)
    built = rig_module.Rig.load(rig_path)
    problems = rig_module.validate(built)
    if problems:
        return result.add("REST", False, "the rig is invalid: %s" % "; ".join(problems[:3]))
    if tuple(built.size) != tuple(reference.size):
        return result.add("REST", False, "the rig is %dx%d but the reference is %dx%d"
                          % (built.size[0], built.size[1],
                             reference.size[0], reference.size[1]))

    pieces = cutout_module.cut(built, reference.pixels)
    rebuilt = pieces.rest()
    if not img.equal(rebuilt, reference.pixels):
        differing = int((rebuilt != reference.pixels).any(axis=2).sum())
        return result.add("REST", False,
                          "reassembling the parts differs from the source in %d pixels"
                          % differing)
    return result.add("REST", True,
                      "the %d parts reassemble into the source image exactly"
                      % len(built.parts))
