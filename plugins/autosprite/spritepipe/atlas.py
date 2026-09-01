"""Write the sheet in the form each engine actually reads.

The formats here are the ones the engines' own importers parse, not a house
JSON with an engine's name on it:

  autosprite.json          this pipeline's own record: everything, losslessly
  texturepacker-hash.json  Phaser 3 `load.atlas`, PixiJS
  texturepacker-array.json the array variant, same consumers
  aseprite.json            Aseprite's export, with frameTags per animation
  unity.png.meta           a TextureImporter with one sprite rect per frame
  godot.tres               a Godot 4 SpriteFrames with per-animation fps and loop
  unreal-paper2d.json      what Unreal's PaperJsonImporter accepts
  gamemaker.json           GameMaker's strip parameters plus a frame manifest
  rpgmaker/                MV/MZ character sheets, which are a LAYOUT, not an atlas

Two coordinate conventions bite here and both are silent when wrong:

- **Unity's texture origin is bottom-left.** Every rect y must be flipped
  against the sheet height, and a sheet that looks right in the inspector with
  unflipped y is one where every sprite is vertically mirrored in its cell.
- **Pivots are normalised 0..1 from the BOTTOM-left in Unity and Godot's atlas
  region is top-left in pixels.** They do not share a convention with each
  other or with TexturePacker, whose pivot is top-left normalised.
"""

import hashlib
import json
import os
import zipfile

import numpy as np

from . import image as img

APP = "autosprite (LiLo Labs)"


def _duration_ms(fps):
    return int(round(1000.0 / max(0.001, float(fps))))


def native(sheet, name, reference_report=None, extra=None, sources=None):
    """This pipeline's own atlas: the complete record, and the one `verify` reads."""
    clips = []
    for clip_key, placements in sorted(sheet.by_clip().items()):
        clip = sheet.clip(clip_key)
        clips.append({
            "key": clip_key,
            "animation": clip.name,
            "direction": clip.direction,
            "fps": clip.fps,
            "loop": clip.loop,
            "loop_start": clip.loop_start if clip.loop_start is not None else 0,
            "loop_end": (clip.loop_end if clip.loop_end is not None
                         else len(placements) - 1),
            "duration_ms": _duration_ms(clip.fps),
            "fidelity": clip.fidelity,
            "note": clip.note,
            "anchor": list(clip.anchor),
            "frames": [placement.to_dict() for placement in placements],
        })
    document = {
        "format": "autosprite-atlas/1",
        "generator": APP,
        "image": "%s.png" % name,
        "size": {"w": sheet.size[0], "h": sheet.size[1]},
        "layout": sheet.layout,
        "cell": list(sheet.cell) if sheet.cell else None,
        "padding": sheet.padding,
        "extrude": sheet.extrude,
        "scale": sheet.scale,
        "clips": clips,
    }
    if reference_report:
        document["source"] = reference_report
    if sources:
        # Every image a pixel of this sheet is allowed to have come from, with
        # the ingest parameters it was read at and a digest of the file. The
        # PALETTE check rebuilds its allowed set from this rather than from one
        # `--reference`, which is what a build with a front view or an attached
        # item needs -- and it is a digest rather than a bare path so the check
        # can tell "this file changed" from "this sheet is wrong".
        document["sources"] = sources
    if extra:
        document.update(extra)
    return document


def _frame_entries(sheet):
    for clip_key, placements in sorted(sheet.by_clip().items()):
        clip = sheet.clip(clip_key)
        for placement in placements:
            yield clip, placement


def texturepacker(sheet, name, style="hash"):
    """TexturePacker JSON. Phaser 3, PixiJS, and Unreal's Paper2D importer.

    Frames are never trimmed or rotated by this packer, so spriteSourceSize
    equals frame and sourceSize equals the cell. Emitting those fields anyway
    matters: importers that support trimming read them unconditionally, and a
    missing sourceSize is a null-dereference in more than one of them.
    """
    entries = []
    for clip, placement in _frame_entries(sheet):
        anchor_x = placement.anchor[0] / float(max(1, placement.width))
        anchor_y = placement.anchor[1] / float(max(1, placement.height))
        entries.append(("%s.png" % placement.name, {
            "frame": {"x": placement.x, "y": placement.y,
                      "w": placement.width, "h": placement.height},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0,
                                 "w": placement.width, "h": placement.height},
            "sourceSize": {"w": placement.width, "h": placement.height},
            "duration": _duration_ms(clip.fps),
            # TexturePacker's pivot is normalised from the TOP-left.
            "pivot": {"x": round(anchor_x, 6), "y": round(anchor_y, 6)},
        }))

    meta = {
        "app": "https://www.codeandweb.com/texturepacker",
        "version": "1.0",
        "image": "%s.png" % name,
        "format": "RGBA8888",
        "size": {"w": sheet.size[0], "h": sheet.size[1]},
        "scale": str(sheet.scale),
        "smartupdate": "autosprite",
    }
    if style == "array":
        frames = [dict(entry, filename=filename) for filename, entry in entries]
        return {"frames": frames, "meta": meta}
    return {"frames": dict(entries), "meta": meta}


def aseprite(sheet, name):
    """Aseprite's exported JSON, whose frameTags are how most tools find clips."""
    document = texturepacker(sheet, name, style="array")
    tags, cursor = [], 0
    for clip_key, placements in sorted(sheet.by_clip().items()):
        clip = sheet.clip(clip_key)
        tags.append({"name": clip_key, "from": cursor,
                     "to": cursor + len(placements) - 1,
                     "direction": "forward",
                     "repeat": "0" if clip.loop else "1"})
        # A clip that is raised once and then held is two tags, not one: the
        # whole thing under its own name, and the part that actually repeats
        # under "<name>_loop". Aseprite has no in/out points on a tag, and two
        # tags is what every importer that reads them already understands.
        if clip.loop and clip.loop_start:
            tags.append({"name": "%s_loop" % clip_key,
                         "from": cursor + clip.loop_start,
                         "to": cursor + (clip.loop_end if clip.loop_end is not None
                                         else len(placements) - 1),
                         "direction": "forward", "repeat": "0"})
        cursor += len(placements)
    document["meta"]["app"] = "https://www.aseprite.org/"
    document["meta"]["frameTags"] = tags
    document["meta"]["layers"] = [{"name": "sprite", "opacity": 255, "blendMode": "normal"}]
    return document


def _deterministic_guid(text):
    """A stable Unity GUID, so re-exporting does not detach existing references."""
    return hashlib.md5(("autosprite:" + text).encode("utf-8")).hexdigest()


def unity_meta(sheet, name, pixels_per_unit=None):
    """A Unity `.png.meta` with one sprite per frame.

    `spriteMode: 2` is Multiple. `alignment: 9` is Custom, which is what makes
    the per-sprite pivot below be read at all -- with any other alignment Unity
    silently ignores it and centres everything.
    """
    sheet_w, sheet_h = sheet.size
    if pixels_per_unit is None:
        pixels_per_unit = max(1, (sheet.cell[1] if sheet.cell else 32))
    guid = _deterministic_guid(name)

    lines = [
        "fileFormatVersion: 2",
        "guid: %s" % guid,
        "TextureImporter:",
        "  internalIDToNameTable: []",
        "  externalObjects: {}",
        "  serializedVersion: 12",
        "  mipmaps:",
        "    mipMapMode: 0",
        "    enableMipMap: 0",
        "  isReadable: 0",
        "  streamingMipmaps: 0",
        "  alphaTestReferenceValue: 0.5",
        "  alphaIsTransparency: 1",
        "  spriteMode: 2",
        "  spritePixelsToUnits: %d" % pixels_per_unit,
        "  spriteMeshType: 0",
        "  spriteExtrude: %d" % max(0, sheet.extrude),
        "  spriteGenerateFallbackPhysicsShape: 1",
        "  textureType: 8",
        "  textureShape: 1",
        "  filterMode: 0",
        "  wrapU: 1",
        "  wrapV: 1",
        "  npotScale: 0",
        "  textureCompression: 0",
        "  maxTextureSize: %d" % max(2048, sheet_w, sheet_h),
        "  spriteSheet:",
        "    serializedVersion: 2",
        "    sprites:",
    ]
    for _, placement in _frame_entries(sheet):
        # Unity's texture space starts at the bottom-left.
        unity_y = sheet_h - placement.y - placement.height
        pivot_x = placement.anchor[0] / float(max(1, placement.width))
        pivot_y = 1.0 - placement.anchor[1] / float(max(1, placement.height))
        lines += [
            "    - serializedVersion: 2",
            "      name: %s" % placement.name,
            "      rect:",
            "        serializedVersion: 2",
            "        x: %d" % placement.x,
            "        y: %d" % unity_y,
            "        width: %d" % placement.width,
            "        height: %d" % placement.height,
            "      alignment: 9",
            "      pivot: {x: %.6f, y: %.6f}" % (pivot_x, pivot_y),
            "      border: {x: 0, y: 0, z: 0, w: 0}",
            "      outline: []",
            "      physicsShape: []",
            "      spriteID: %s" % _deterministic_guid("%s/%s" % (name, placement.name)),
            "      internalID: 0",
        ]
    lines += [
        "    outline: []",
        "    physicsShape: []",
        "    bones: []",
        "    spriteID: ",
        "    internalID: 0",
        "    vertices: []",
        "    indices: ",
        "    edges: []",
        "    weights: []",
        "  spritePackingTag: %s" % name,
        "  userData: ",
        "  assetBundleName: ",
        "  assetBundleVariant: ",
        "",
    ]
    return "\n".join(lines)


def godot_tres(sheet, name, texture_path=None):
    """A Godot 4 SpriteFrames resource, one animation per clip.

    Godot's `speed` is frames per second and `duration` is a per-frame
    multiplier of it, so a uniform clip is every frame at duration 1.0 and the
    clip's own fps in `speed`. Encoding the fps per frame instead -- which is
    tempting, since our data has it there -- makes every AnimatedSprite2D in the
    project play at Godot's default 5fps until someone notices.
    """
    texture_path = texture_path or "res://%s.png" % name
    steps, subresources, animations = [], [], []

    for clip_key, placements in sorted(sheet.by_clip().items()):
        clip = sheet.clip(clip_key)
        frame_refs = []
        for placement in placements:
            sub_id = "AtlasTexture_%s_%03d" % (_safe(clip_key), placement.index)
            subresources.append(
                '[sub_resource type="AtlasTexture" id="%s"]\n'
                'atlas = ExtResource("1_sheet")\n'
                'region = Rect2(%d, %d, %d, %d)\n'
                % (sub_id, placement.x, placement.y, placement.width, placement.height))
            frame_refs.append(
                '{\n"duration": 1.0,\n"texture": SubResource("%s")\n}' % sub_id)
        animations.append(
            '{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %s\n}'
            % (", ".join(frame_refs), "true" if clip.loop else "false",
               clip_key, _number(clip.fps)))
        steps.append(len(placements))

    header = ('[gd_resource type="SpriteFrames" load_steps=%d format=3]\n\n'
              '[ext_resource type="Texture2D" path="%s" id="1_sheet"]\n\n'
              % (sum(steps) + 2, texture_path))
    body = "\n".join(subresources)
    tail = "\n[resource]\nanimations = [%s]\n" % ", ".join(animations)
    return header + body + tail


def _safe(text):
    return "".join(char if char.isalnum() else "_" for char in str(text))


def _number(value):
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def gamemaker(sheet, name):
    """GameMaker imports strips and loose frames, not atlases.

    So this is a manifest rather than a project file: the grid parameters for
    "Import Strip" when the layout is a grid, and the frame list plus timings
    for anyone importing the ZIP. Pretending GameMaker reads a JSON atlas would
    produce a file that imports as nothing.
    """
    clips = []
    for clip_key, placements in sorted(sheet.by_clip().items()):
        clip = sheet.clip(clip_key)
        clips.append({
            "name": clip_key,
            "frames": len(placements),
            "fps": clip.fps,
            "loop": clip.loop,
            "playbackSpeed": clip.fps,
            "playbackSpeedType": "FramesPerSecond",
            "origin": {"x": clip.anchor[0], "y": clip.anchor[1]},
            "row": placements[0].y if placements else 0,
            "frameNames": ["%s.png" % placement.name for placement in placements],
        })
    document = {
        "format": "autosprite-gamemaker/1",
        "image": "%s.png" % name,
        "importAs": "strip" if sheet.layout == "grid" else "frames",
        "note": ("GameMaker has no sprite-atlas importer. With the grid layout, "
                 "use Import Strip with the cell size and count below; otherwise "
                 "import frames.zip and set the playback speed per animation."),
        "clips": clips,
    }
    if sheet.cell:
        gutter = sheet.padding + sheet.extrude
        document["strip"] = {
            "cellWidth": sheet.cell[0] + 2 * gutter,
            "cellHeight": sheet.cell[1] + 2 * gutter,
            "offsetX": gutter, "offsetY": gutter,
            "frameWidth": sheet.cell[0], "frameHeight": sheet.cell[1],
            "columns": max(len(p) for p in sheet.by_clip().values()),
            "rows": len(sheet.by_clip()),
        }
    return document


def unreal_paper2d(sheet, name):
    """Unreal's PaperJsonImporter reads TexturePacker's ARRAY format.

    It dispatches on `meta.app` containing "texturepacker", so the array
    document is emitted verbatim under a name that says what it is for. A
    bespoke "unreal.json" would import as nothing at all.
    """
    document = texturepacker(sheet, name, style="array")
    document["meta"]["note"] = (
        "Import into Unreal with Paper2D's sprite-sheet importer: it reads "
        "TexturePacker JSON (array). The flipbook frame rates are per clip in "
        "%s.autosprite.json." % name)
    return document


# --------------------------------------------------------------------------
# RPG Maker: a fixed layout rather than an atlas
# --------------------------------------------------------------------------

RPGMAKER_ROWS = ("S", "W", "E", "N")   # MV/MZ character sheet row order


def rpgmaker_sheet(clips, animation="walk", columns=3):
    """Build an MV/MZ single-character sheet from four directional walk clips.

    MV and MZ do not read an atlas. A character file is a grid: 3 columns of
    walk poses by 4 rows of facings, in the fixed order down, left, right, up,
    and the engine derives the cell size by dividing the image. A `$`-prefixed
    filename tells it the file holds one character rather than eight.

    Returns (pixels, report) or (None, report) when the directions are missing.
    """
    wanted = {clip.direction: clip for clip in clips
              if clip.name == animation and clip.direction}
    missing = [row for row in RPGMAKER_ROWS if row not in wanted]
    if missing:
        return None, {
            "written": False,
            "reason": ("RPG Maker needs the %s animation in all four cardinal "
                       "directions (%s); missing %s. Re-run with --directions 4."
                       % (animation, ", ".join(RPGMAKER_ROWS), ", ".join(missing))),
        }

    cell_w = max(frame.shape[1] for clip in wanted.values() for frame in clip.frames)
    cell_h = max(frame.shape[0] for clip in wanted.values() for frame in clip.frames)
    pixels = img.blank(cell_h * 4, cell_w * columns)

    picked = {}
    for row, direction in enumerate(RPGMAKER_ROWS):
        frames = wanted[direction].frames
        # MV's three columns are one STRIDE, not one cycle: left foot forward,
        # passing, right foot forward -- and the engine plays them 0,1,2,1, which
        # completes the cycle by running the middle column twice. So the columns
        # are sampled across HALF the loop. Spreading them over the whole cycle
        # instead lands the middle column on a contact pose, and the character
        # then appears to skip every second step.
        count = len(frames)
        span = count / 2.0
        divisor = max(1, columns - 1)
        indices = [int(round(index * span / divisor)) % count
                   for index in range(columns)]
        picked[direction] = indices
        for column, index in enumerate(indices):
            frame = frames[index]
            x = column * cell_w + (cell_w - frame.shape[1]) // 2
            y = row * cell_h + (cell_h - frame.shape[0])
            img.paste(pixels, frame, x, y)

    return pixels, {
        "written": True,
        "rows": list(RPGMAKER_ROWS),
        "columns": columns,
        "cell": [cell_w, cell_h],
        "frames_used": picked,
        "filename_note": ("Name the file with a leading $ (for example "
                          "$hero.png) so RPG Maker reads it as a single "
                          "character rather than an eight-character page."),
    }


# --------------------------------------------------------------------------
# writing it all out
# --------------------------------------------------------------------------

def write_frames_zip(sheet, path):
    """Every frame as its own PNG, cut back out of the sheet.

    Cut out of the sheet rather than kept from before packing: if the two ever
    disagree, the ZIP is what the user opens to find out, so it has to be the
    sheet's own truth.
    """
    import io
    count = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for _, placement in _frame_entries(sheet):
            crop = sheet.pixels[placement.y:placement.y + placement.height,
                                placement.x:placement.x + placement.width]
            buffer = io.BytesIO()
            from PIL import Image as PILImage
            PILImage.fromarray(np.ascontiguousarray(crop), mode="RGBA").save(buffer, "PNG")
            archive.writestr("%s.png" % placement.name, buffer.getvalue())
            count += 1
    return count


def write_animation_zip(sheet, path, name):
    """One folder per animation: a strip, its own atlas, and its own frames.

    autosprite.io's download is shaped this way -- `<anim>/spritesheet.png`,
    `<anim>/atlas.json`, `<anim>/frames/01.png` -- and a user who wants only the
    walk, or who is feeding an importer one animation at a time (GameMaker's
    multi-select flow is exactly that), should not have to sort a flat archive
    of every frame of every clip first.

    Every frame is cut out of the finished sheet rather than kept from before
    packing, and each strip is those crops laid side by side, so the bytes in
    here and the bytes in the master sheet cannot disagree. `verify` checks that
    they do not.
    """
    import io as _io
    from PIL import Image as PILImage

    def encode(pixels):
        buffer = _io.BytesIO()
        PILImage.fromarray(np.ascontiguousarray(pixels), mode="RGBA").save(buffer, "PNG")
        return buffer.getvalue()

    written = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for clip_key, placements in sorted(sheet.by_clip().items()):
            clip = sheet.clip(clip_key)
            crops = [sheet.pixels[p.y:p.y + p.height, p.x:p.x + p.width]
                     for p in placements]
            if not crops:
                continue
            width = sum(crop.shape[1] for crop in crops)
            height = max(crop.shape[0] for crop in crops)
            strip = img.blank(height, width)
            frames, x = [], 0
            for index, (crop, placement) in enumerate(zip(crops, placements)):
                img.paste(strip, crop, x, 0)
                frames.append({
                    "name": "%02d" % (index + 1),
                    "x": x, "y": 0,
                    "w": crop.shape[1], "h": crop.shape[0],
                    "anchor": list(placement.anchor),
                })
                archive.writestr("%s/frames/%02d.png" % (clip_key, index + 1),
                                 encode(crop))
                written += 1
                x += crop.shape[1]
            archive.writestr("%s/spritesheet.png" % clip_key, encode(strip))
            archive.writestr("%s/atlas.json" % clip_key, json.dumps({
                "format": "autosprite-atlas/1",
                "generator": APP,
                "image": "spritesheet.png",
                "size": {"w": width, "h": height},
                "layout": "strip",
                "animation": clip.name,
                "direction": clip.direction,
                "fps": clip.fps,
                "loop": clip.loop,
                "duration_ms": _duration_ms(clip.fps),
                "fidelity": clip.fidelity,
                "note": clip.note,
                "frames": frames,
            }, indent=2))
    return written


def _compress_sheet(sheet, sheet_path):
    """Rewrite the sheet as an indexed PNG when that is genuinely smaller.

    Lossless here rather than "quantised", because the sheet's palette is
    provably a subset of the source art's -- there is nothing to throw away.

    But it is not always a win. A 256-entry palette table is a fixed cost, and
    on a small sheet with four colours it outweighs what indexing saves: the
    file comes back 36% BIGGER. So write both and keep the smaller one, and say
    which happened rather than claiming a saving that did not occur.
    """
    candidate = sheet_path + ".indexed"
    if not img.save_indexed(sheet.pixels, candidate):
        return ("full RGBA: over 255 colours, so an indexed PNG could not hold "
                "the palette losslessly")
    plain = os.path.getsize(sheet_path)
    indexed = os.path.getsize(candidate)
    if indexed >= plain:
        os.remove(candidate)
        return ("full RGBA: the palette table costs more than indexing saves on a "
                "sheet this small (%d bytes indexed against %d)" % (indexed, plain))
    os.replace(candidate, sheet_path)
    return ("indexed PNG, losslessly: %d bytes against %d, %.0f%% smaller"
            % (indexed, plain, (1 - indexed / float(plain)) * 100))


WRITERS = {
    "texturepacker-hash": (lambda sheet, name: texturepacker(sheet, name, "hash"),
                           "%s.texturepacker-hash.json", "json"),
    "texturepacker-array": (lambda sheet, name: texturepacker(sheet, name, "array"),
                            "%s.texturepacker-array.json", "json"),
    "phaser": (lambda sheet, name: texturepacker(sheet, name, "hash"),
               "%s.phaser.json", "json"),
    "aseprite": (aseprite, "%s.aseprite.json", "json"),
    "unity": (unity_meta, "%s.png.meta", "text"),
    "godot": (godot_tres, "%s.tres", "text"),
    "unreal": (unreal_paper2d, "%s.unreal-paper2d.json", "json"),
    "gamemaker": (gamemaker, "%s.gamemaker.json", "json"),
}

ENGINE_SETS = {
    "all": sorted(WRITERS) + ["rpgmaker"],
    "web": ["phaser", "texturepacker-array", "aseprite"],
}


def digest(path):
    """A file's sha256, or None if it cannot be read."""
    import hashlib
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def write(sheet, outdir, name, engines=("all",), clips=None, reference_report=None,
          compress=False, sources=None):
    """Write the sheet, the native atlas, and every requested engine format."""
    os.makedirs(outdir, exist_ok=True)
    written = {}

    sheet_path = os.path.join(outdir, "%s.png" % name)
    img.save(sheet.pixels, sheet_path)
    if compress:
        written["sheet_format"] = _compress_sheet(sheet, sheet_path)
    written["sheet"] = sheet_path

    atlas_path = os.path.join(outdir, "%s.autosprite.json" % name)
    with open(atlas_path, "w") as handle:
        json.dump(native(sheet, name, reference_report, sources=sources),
                  handle, indent=2)
        handle.write("\n")
    written["atlas"] = atlas_path

    wanted = []
    for engine in engines:
        wanted.extend(ENGINE_SETS.get(engine, [engine]))
    seen = set()
    for engine in wanted:
        if engine in seen:
            continue
        seen.add(engine)
        if engine == "rpgmaker":
            pixels, report = rpgmaker_sheet(clips or sheet.clips)
            if pixels is not None:
                path = os.path.join(outdir, "$%s.png" % name)
                img.save(pixels, path)
                written["rpgmaker"] = path
            written["rpgmaker_report"] = report
            continue
        if engine not in WRITERS:
            raise ValueError("unknown engine %r; have %s"
                             % (engine, ", ".join(sorted(WRITERS)) + ", rpgmaker"))
        builder, pattern, kind = WRITERS[engine]
        path = os.path.join(outdir, pattern % name)
        document = builder(sheet, name)
        with open(path, "w") as handle:
            if kind == "json":
                json.dump(document, handle, indent=2)
                handle.write("\n")
            else:
                handle.write(document)
        written[engine] = path

    zip_path = os.path.join(outdir, "%s-frames.zip" % name)
    written["frames_zip"] = zip_path
    written["frames_zip_count"] = write_frames_zip(sheet, zip_path)

    animations_path = os.path.join(outdir, "%s-animations.zip" % name)
    written["animations_zip"] = animations_path
    written["animations_zip_count"] = write_animation_zip(sheet, animations_path, name)
    return written
