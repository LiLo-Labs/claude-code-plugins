#!/usr/bin/env python3
"""Rebuild the ground-truth corpus from its CC0 sources, and write `truth.json`.

**Why this exists.** Every measurement in HANDOFF.md rests on an artist's own
animation frames, and until this script the whole set lived in `/tmp`, rebuilt by
hand from notes. A container is reclaimed and the evidence goes with it -- which
means a number nobody can reproduce, which is the one thing this project has
been strict about everywhere else. No art is committed (`.gitignore` excludes
PNGs deliberately); what is committed is the RECIPE.

**The licence is checked on every run, not trusted from this table.** Each entry
records the OpenGameArt page it came from, and the fetch refuses a subject whose
page no longer carries CC0 in its licence field. That is the standing rule of
this project written down as code: verify the licence yourself, use only CC0.

**The cuts are exact and they have to be.** `scripts/ground_truth.py` proves the
rest pose is byte-identical to the source before it reports anything, so a crop
that is one pixel out reports nothing at all rather than reporting a wrong
number. Every `rows`/`cell`/`pad` below was derived from the art and is recorded
with the reason: `pad` exists where a character's feet sit on the last row, since
a subject flush with the frame edge cannot be planted.

Usage:
    python3 scripts/fetch_truth.py [workdir] [--corpus DIR] [--out truth.json]

Then:
    python3 scripts/ground_truth.py truth.json
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

import numpy as np
from PIL import Image

CC0_DEED = "creativecommons.org/publicdomain/zero"
AGENT = "autosprite-ground-truth/1.0 (+https://github.com/LiLo-Labs/claude-code-plugins)"

# Every subject: where it came from, how it was cut, and which cells of which
# sheet are the artist's own frames for each clip. `member` is the path inside
# the archive, or None when the download is the image itself.
SUBJECTS = [
    dict(name="sumohulk", slug="platformer-sumohulk-16",
         page="https://opengameart.org/content/sprite-sheet-sidescoller-cycles",
         url="https://opengameart.org/sites/default/files/SumoHulkBrawler_byEris.zip",
         member="SumoHulkBrawler/sumoHulk_spriteSheet.png",
         cell=16, source_rows=[0, 16], source_column=0, pad=0,
         facing="front", character_class="humanoid",
         clips={"walk":   dict(rows=[16, 32], columns=[0, 1, 2, 3, 4, 5]),
                "idle":   dict(rows=[0, 16], columns=[1, 2, 3]),
                "jump":   dict(rows=[32, 48], columns=[0, 1, 2]),
                "attack": dict(rows=[96, 112], columns=[0, 1, 2])},
         note="A frog-like brawler hopping AT the camera; `front` is read off "
              "its own strip and the corpus meta disagreed with the truth file "
              "about this until 2026-09-02."),
    dict(name="horse", slug="creature-horse-scratchio",
         page="https://opengameart.org/content/animated-horse",
         url="https://opengameart.org/sites/default/files/Horse.zip",
         member="Horse/Horse_Idle.png",
         cell=60, source_rows=[0, 33], source_column=0, pad=3,
         facing="left", character_class="auto",
         clips={"idle": dict(member="Horse/Horse_Idle.png", rows=[0, 33],
                             columns=list(range(1, 13))),
                "walk": dict(member="Horse/Horse_Walk.png", rows=[0, 33],
                             columns=list(range(0, 8))),
                "run":  dict(member="Horse/Horse_Run.png", rows=[0, 33],
                             columns=list(range(0, 6)))},
         note="Padded 3 rows because the hooves sit on the last row."),
    dict(name="forest", slug="platformer-forest-64",
         page="https://opengameart.org/content/forest-platformer-64x64-cc-0",
         url="https://opengameart.org/sites/default/files/character_10.png",
         member=None,
         cell=64, source_rows=[14, 68], source_column=0, pad=0,
         facing="right", character_class="humanoid",
         clips={"run": dict(rows=[14, 68], columns=[1, 2, 3, 4, 5])}),
    dict(name="mv-male", slug="platformer-mv-male",
         page="https://opengameart.org/content/mv-platformer-male-32x64",
         url="https://opengameart.org/sites/default/files/maleBase_0.zip",
         member="maleBase/full/advnt_full.png",
         cell=32, source_rows=[12, 68], source_column=0, pad=0,
         facing="right", character_class="humanoid",
         clips={"walk":   dict(rows=[12, 68], columns=[1, 2, 3, 4, 5, 6]),
                "crouch": dict(rows=[12, 68], columns=[7, 8, 9]),
                "attack": dict(rows=[12, 68], columns=[4, 5, 6])},
         note="The crop runs 4px past the feet into the empty row below."),
    dict(name="eldiran", slug="topdown-eldiran-rpg",
         page="https://opengameart.org/content/32x32-rpg-character-sprites",
         url="https://opengameart.org/sites/default/files/RPGCharacterSprites32x32.png",
         member=None,
         cell=32, source_rows=[128, 160], source_column=0, pad=0,
         facing="front", character_class="humanoid",
         clips={"walk": dict(rows=[128, 160], columns=[1, 2, 3])},
         note="ROW 128, and the row matters: the download is a 384x672 sheet of "
              "twenty-one 32x32 characters and only the fifth row down is the "
              "knight every number in HANDOFF was measured against. Until this "
              "script that row lived only in a hand-composed intermediate sheet "
              "in /tmp, so the one subject whose provenance was undocumented is "
              "the one this recipe caught. The background is a MAGENTA key "
              "rather than alpha -- `ingest.remove_background` takes it, which "
              "is why the frame is 1024 opaque pixels on disk and 676 after "
              "loading."),

    # -- added 2026-09-02, and each one closes a gap the set could not answer --
    dict(name="deer", slug="creature-deer-batteryman",
         page="https://opengameart.org/content/animated-wild-animals",
         url="https://opengameart.org/sites/default/files/Deer_0.zip",
         member="Deer/Deer_Idle.png",
         cell=72, source_rows=[0, 52], source_column=0, pad=3,
         facing="left", character_class="auto",
         clips={"idle": dict(member="Deer/Deer_Idle.png", rows=[0, 52],
                             columns=list(range(1, 10))),
                "walk": dict(member="Deer/Deer_Walk.png", rows=[0, 52],
                             columns=list(range(0, 8))),
                "run":  dict(member="Deer/Deer_Run.png", rows=[0, 52],
                             columns=list(range(0, 6)))},
         note="A 51px side-on quadruped WITH an artist's idle -- the set had a "
              "quadruped and it had idles, and no subject with both. The cell "
              "width of 72 is proved, not guessed: every boundary at 72 falls "
              "inside a fully transparent column and no other divisor of 720 "
              "does. Its idle is a GRAZING CYCLE, head to the ground."),
    dict(name="boar", slug="creature-boar-batteryman",
         page="https://opengameart.org/content/animated-wild-animals",
         url="https://opengameart.org/sites/default/files/Boar.zip",
         member="Boar/Boar_Idle.png",
         cell=64, source_rows=[0, 40], source_column=0, pad=3,
         facing="left", character_class="auto",
         clips={"idle": dict(member="Boar/Boar_Idle.png", rows=[0, 40],
                             columns=list(range(1, 8))),
                "walk": dict(member="Boar/Boar_Walk.png", rows=[0, 40],
                             columns=list(range(0, 8))),
                "run":  dict(member="Boar/Boar_Run.png", rows=[0, 40],
                             columns=list(range(0, 6)))},
         note="A SECOND quadruped at half the deer's height, which is what "
              "separates a size effect from a subject effect. Its idle is a "
              "TAIL FLICK and nothing else -- 59 disturbed pixels of 669 -- "
              "and that single fact is the most useful thing in this file."),
    dict(name="shieldmaiden", slug="platformer-shieldmaiden-anim",
         page="https://opengameart.org/content/viking-shieldmaiden-animated",
         url="https://opengameart.org/sites/default/files/Shieldmaiden.zip",
         member="1x/idle_0.png", frames_dir="1x",
         cell=40, source_rows=[0, 29], source_column=0, pad=0,
         facing="front", character_class="humanoid",
         clips={"idle":   dict(frames="idle", columns=[1, 2, 3], rows=[0, 29]),
                "run":    dict(frames="run", columns=list(range(0, 6)), rows=[0, 29]),
                "attack": dict(frames="attack", columns=[0, 1, 2], rows=[0, 29]),
                "jump":   dict(frames="jump", columns=list(range(0, 6)), rows=[0, 29])},
         note="Ships one PNG per frame at five scales; 1x is the native art and "
              "the rest are integer upscales of it, so only 1x is worth "
              "measuring. A humanoid with an artist's idle ABOVE 20px, which "
              "the set did not have. Faces FRONT by her own run: the shield "
              "stays circular and centred in all six frames, both helmet horns "
              "stay symmetric, and the body never turns."),
    dict(name="samurai", slug="platformer-samurai-anim",
         page="https://opengameart.org/content/samurai-animated",
         url="https://opengameart.org/sites/default/files/Samurai.zip",
         member="1x/idle_0.png", frames_dir="1x",
         cell=40, source_rows=[0, 29], source_column=0, pad=0,
         facing="front", character_class="humanoid",
         clips={"idle":   dict(frames="idle", columns=[1, 2, 3], rows=[0, 29]),
                "run":    dict(frames="run", columns=list(range(0, 6)), rows=[0, 29]),
                "attack": dict(frames="attack", columns=list(range(0, 8)), rows=[0, 29])},
         note="Same author and rig as the shieldmaiden. Carries a chain weapon "
              "that extends well past the silhouette, which no other corpus "
              "humanoid does."),
    dict(name="slime", slug="creature-slime-anim",
         page="https://opengameart.org/content/pixel-art-animated-slime",
         url="https://opengameart.org/sites/default/files/Slime_0.zip",
         member="Individual Sprites/slime1.png", frames_glob="Individual Sprites/slime%d.png",
         cell=32, source_rows=[0, 25], source_column=0, pad=2,
         facing="right", character_class="auto",
         clips={"idle": dict(frames="slime", columns=list(range(1, 10)),
                             rows=[0, 25])},
         note="LEGLESS, which is the case the silhouette rigger gets wrong by "
              "cutting one mass down the middle and calling the halves a pair "
              "of legs. Its 17 frames are not one clip -- 1-10 are a breathing "
              "wobble and 11-17 rear up and splat -- so only 1-10 are taken. "
              "Facing is meaningless for a radially symmetric blob and is "
              "recorded as `right` because the field is not optional."),
]


def fetch(url, cache):
    """`url`'s bytes, cached on disk so a re-run costs nothing."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1]) or "download"
    path = os.path.join(cache, name)
    if os.path.exists(path):
        return open(path, "rb").read()
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    os.makedirs(cache, exist_ok=True)
    open(path, "wb").write(data)
    return data


def licensed_cc0(page, cache):
    """Whether `page`'s LICENCE FIELD says CC0. Not a search of the whole page.

    A page can mention CC0 in a comment, in a list of the author's other work,
    or in a licence the asset is dual-listed under. The field is the only place
    that binds, so that is the only place this looks.
    """
    try:
        html = fetch(page, cache).decode("utf-8", "replace")
    except Exception as exc:                                  # pragma: no cover
        return None, "could not read the licence page: %s" % exc
    block = re.search(r"field-name-field-art-licenses.*?(?=<div class=\"field field-name-)",
                      html, re.S)
    if not block:
        return None, "no licence field found on the page"
    names = re.findall(r"license-name'>([^<]+)<", block.group(0))
    deeds = re.findall(r"href='(http[^']*)'", block.group(0))
    ok = names == ["CC0"] and any(CC0_DEED in d for d in deeds)
    return ok, "licence field says %s" % (names or "nothing")


def _image(data, member):
    if member is None:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = {n.replace("\\", "/"): n for n in archive.namelist()}
        for key, real in names.items():
            if key.endswith(member):
                return Image.open(io.BytesIO(archive.read(real))).convert("RGBA")
    raise KeyError("%s not in the archive" % member)


def _padded(cell, pad):
    if not pad:
        return cell
    out = np.zeros((cell.shape[0] + 2 * pad, cell.shape[1], 4), np.uint8)
    out[pad:pad + cell.shape[0]] = cell
    return out


def strip_from_frames(data, spec, subject, out_dir):
    """Compose one clip's individual frame files into a strip this harness can cut.

    Some authors ship a PNG per frame rather than a sheet. `ground_truth.cells`
    cuts columns out of a sheet, so the frames are laid side by side into one --
    which also keeps every frame in the SAME coordinate space, the thing the
    alignment check exists to enforce.
    """
    stem = spec["frames"]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n.replace("\\", "/") for n in archive.namelist()]
        if subject.get("frames_glob"):
            wanted = [n for n in names if re.search(r"%s\d+\.png$" % stem, n)]
            key = lambda n: int(re.search(r"(\d+)\.png$", n).group(1))
        else:
            folder = subject["frames_dir"]
            wanted = [n for n in names
                      if "/%s/" % folder in "/" + n and re.search(r"/%s_\d+\.png$" % stem, n)]
            key = lambda n: int(re.search(r"_(\d+)\.png$", n).group(1))
        wanted = sorted(set(wanted), key=key)
        if not wanted:
            raise KeyError("no frames matching %r" % stem)
        frames = [np.array(Image.open(io.BytesIO(
            archive.read(next(o for o in archive.namelist()
                              if o.replace("\\", "/") == n)))).convert("RGBA"))
            for n in wanted]
    tall = max(f.shape[0] for f in frames)
    wide = max(f.shape[1] for f in frames)
    canvas = np.zeros((tall, wide * len(frames), 4), np.uint8)
    for index, frame in enumerate(frames):
        canvas[:frame.shape[0], index * wide:index * wide + frame.shape[1]] = frame
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "%s-%s.png" % (subject["name"], stem))
    Image.fromarray(canvas).save(path)
    return path


def build(subject, workdir, corpus, check_licence=True):
    """One subject: verify, download, cut the source, return its truth entry."""
    cache = os.path.join(workdir, "cache")
    if check_licence:
        ok, why = licensed_cc0(subject["page"], cache)
        if ok is not True:
            return None, "REFUSED (%s): %s" % (why, subject["page"])

    data = fetch(subject["url"], cache)
    sheets = os.path.join(workdir, "sheets")
    os.makedirs(sheets, exist_ok=True)

    entry = {"name": subject["name"],
             "source": os.path.join(corpus, subject["slug"], "frame.png"),
             "rig": None, "cell": subject["cell"],
             "facing": subject["facing"], "class": subject["character_class"],
             "clips": {}}
    if subject.get("pad"):
        entry["pad"] = subject["pad"]

    # The source frame, cut exactly as every artist frame will be.
    if subject.get("frames_dir") or subject.get("frames_glob"):
        first_clip = "idle" if "idle" in subject["clips"] else sorted(subject["clips"])[0]
        source_sheet = strip_from_frames(data, subject["clips"][first_clip],
                                         subject, sheets)
        sheet_pixels = np.array(Image.open(source_sheet).convert("RGBA"))
    else:
        image = _image(data, subject["member"])
        source_sheet = os.path.join(sheets, "%s.png" % subject["name"])
        image.save(source_sheet)
        sheet_pixels = np.array(image)

    top, bottom = subject["source_rows"]
    column = subject["source_column"]
    cell = subject["cell"]
    frame = _padded(sheet_pixels[top:bottom, column * cell:(column + 1) * cell],
                    subject.get("pad", 0))
    folder = os.path.join(corpus, subject["slug"])
    os.makedirs(folder, exist_ok=True)
    Image.fromarray(frame).save(os.path.join(folder, "frame.png"))

    for clip, spec in subject["clips"].items():
        out = {"rows": spec["rows"], "columns": spec["columns"]}
        if spec.get("frames"):
            out["sheet"] = strip_from_frames(data, spec, subject, sheets)
        elif spec.get("member"):
            path = os.path.join(sheets, "%s-%s.png" % (subject["name"], clip))
            _image(data, spec["member"]).save(path)
            out["sheet"] = path
        else:
            out["sheet"] = source_sheet
        entry["clips"][clip] = out

    meta = {"slug": subject["slug"], "license": "CC0",
            "license_page": subject["page"], "download_url": subject["url"],
            "facing": subject["facing"], "kind": subject["character_class"],
            "notes": subject.get("note", "")}
    json.dump(meta, open(os.path.join(folder, "meta.json"), "w"), indent=2)
    mask = frame[..., 3] > 0
    return entry, "%dx%d, %d opaque px" % (frame.shape[1], frame.shape[0],
                                           int(mask.sum()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workdir", nargs="?", default="/tmp/gt",
                        help="where downloads and cut sheets are kept")
    parser.add_argument("--corpus", default="/tmp/corpus",
                        help="where each subject's frame.png and meta.json go")
    parser.add_argument("--out", default=None,
                        help="path for truth.json (default: WORKDIR/truth.json)")
    parser.add_argument("--only", action="append", default=None,
                        help="build only these subjects, by name")
    parser.add_argument("--skip-licence-check", action="store_true",
                        help="do not re-read the licence pages (offline re-runs)")
    args = parser.parse_args(argv)

    os.makedirs(args.workdir, exist_ok=True)
    out = args.out or os.path.join(args.workdir, "truth.json")
    entries, refused = [], 0
    for subject in SUBJECTS:
        if args.only and subject["name"] not in args.only:
            continue
        try:
            entry, why = build(subject, args.workdir, args.corpus,
                               check_licence=not args.skip_licence_check)
        except Exception as exc:
            print("%-14s FAILED: %s" % (subject["name"], exc))
            refused += 1
            continue
        if entry is None:
            print("%-14s %s" % (subject["name"], why))
            refused += 1
            continue
        entries.append(entry)
        print("%-14s %-8s %s" % (subject["name"], "ok", why))
    json.dump(entries, open(out, "w"), indent=1)
    print("\n%d subjects, %d clips -> %s"
          % (len(entries), sum(len(e["clips"]) for e in entries), out))
    if refused:
        print("%d subject(s) not built; the truth file is INCOMPLETE" % refused)
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
