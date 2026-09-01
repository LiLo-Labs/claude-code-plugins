"""Each engine file must be the thing that engine's importer actually reads."""

import io
import json
import os
import re
import zipfile

import numpy as np
import pytest

from PIL import Image as PILImage

from spritepipe import atlas, image, pack


def frames(count, width, height, colour):
    out = []
    for index in range(count):
        frame = image.blank(height, width)
        frame[1:, 1:] = colour
        frame[0, index % width] = colour
        out.append(frame)
    return out


@pytest.fixture
def clips():
    return [pack.Clip("idle", frames(3, 8, 10, [200, 40, 40, 255]), 6, True,
                      anchor=(4, 10)),
            pack.Clip("walk", frames(4, 8, 10, [40, 90, 200, 255]), 12, True,
                      anchor=(4, 10))]


@pytest.fixture
def sheet(clips):
    return pack.pack(clips, layout="grid", padding=1, extrude=1)


def test_the_native_atlas_records_every_clip_with_its_timing(sheet):
    document = atlas.native(sheet, "hero")
    assert document["format"] == "autosprite-atlas/1"
    assert {c["key"] for c in document["clips"]} == {"idle", "walk"}
    walk = next(c for c in document["clips"] if c["key"] == "walk")
    assert walk["fps"] == 12 and walk["loop"] is True
    assert walk["duration_ms"] == 83
    assert len(walk["frames"]) == 4


def test_texturepacker_hash_is_keyed_by_filename(sheet):
    document = atlas.texturepacker(sheet, "hero", "hash")
    assert isinstance(document["frames"], dict)
    assert "walk_000.png" in document["frames"]
    entry = document["frames"]["walk_000.png"]
    assert set(entry) >= {"frame", "rotated", "trimmed", "spriteSourceSize",
                          "sourceSize", "pivot"}


def test_texturepacker_array_carries_the_filename_inside_each_entry(sheet):
    document = atlas.texturepacker(sheet, "hero", "array")
    assert isinstance(document["frames"], list)
    assert all("filename" in entry for entry in document["frames"])


def test_texturepacker_pivot_is_normalised_from_the_top_left(sheet):
    document = atlas.texturepacker(sheet, "hero", "hash")
    entry = document["frames"]["idle_000.png"]
    assert 0.0 <= entry["pivot"]["x"] <= 1.0
    assert entry["pivot"]["y"] == pytest.approx(1.0, abs=0.2)


def test_aseprite_tags_each_clip_as_a_frame_range(sheet):
    document = atlas.aseprite(sheet, "hero")
    tags = document["meta"]["frameTags"]
    assert [t["name"] for t in tags] == ["idle", "walk"]
    assert tags[0]["from"] == 0 and tags[0]["to"] == 2
    assert tags[1]["from"] == 3 and tags[1]["to"] == 6


def test_unreal_declares_itself_as_texturepacker_so_paper2d_accepts_it(sheet):
    document = atlas.unreal_paper2d(sheet, "hero")
    assert "texturepacker" in document["meta"]["app"]
    assert isinstance(document["frames"], list)


def test_unity_flips_y_because_its_texture_origin_is_bottom_left(sheet):
    """Not flipping renders every sprite mirrored in its cell, silently."""
    text = atlas.unity_meta(sheet, "hero")
    height = sheet.size[1]
    found = {}
    for match in re.finditer(
            r"name: (\S+)\s*\n\s*rect:\s*\n\s*serializedVersion: 2\s*\n"
            r"\s*x: (-?\d+)\s*\n\s*y: (-?\d+)\s*\n\s*width: (\d+)\s*\n\s*height: (\d+)",
            text):
        found[match.group(1)] = tuple(int(v) for v in match.groups()[1:])
    for placement in sheet.placements:
        x, y, w, h = found[placement.name]
        assert (x, w, h) == (placement.x, placement.width, placement.height)
        assert y == height - placement.y - placement.height


def test_unity_uses_custom_alignment_or_the_pivot_is_ignored(sheet):
    text = atlas.unity_meta(sheet, "hero")
    assert "spriteMode: 2" in text
    assert text.count("alignment: 9") == len(sheet.placements)


def test_unity_guids_are_stable_across_exports(sheet):
    first = atlas.unity_meta(sheet, "hero")
    second = atlas.unity_meta(sheet, "hero")
    assert first == second
    assert atlas.unity_meta(sheet, "other") != first


def test_godot_puts_the_frame_rate_on_the_animation_not_the_frame(sheet):
    """Per-frame durations leave every AnimatedSprite2D at Godot's default 5fps."""
    text = atlas.godot_tres(sheet, "hero")
    assert '"speed": 12' in text
    assert text.count('"duration": 1.0') == len(sheet.placements)


def test_godot_declares_one_animation_per_clip_with_its_loop_flag(sheet):
    text = atlas.godot_tres(sheet, "hero")
    assert '&"idle"' in text and '&"walk"' in text
    assert '"loop": true' in text


def test_godot_regions_match_the_placements(sheet):
    text = atlas.godot_tres(sheet, "hero")
    regions = {tuple(int(v) for v in m)
               for m in re.findall(r"region = Rect2\((\d+), (\d+), (\d+), (\d+)\)", text)}
    assert regions == {p.rect for p in sheet.placements}


def test_gamemaker_gives_strip_parameters_for_a_grid(sheet):
    document = atlas.gamemaker(sheet, "hero")
    assert document["importAs"] == "strip"
    assert document["strip"]["frameWidth"] == sheet.cell[0]
    assert document["strip"]["rows"] == 2


def test_gamemaker_falls_back_to_frames_for_a_packed_sheet(clips):
    packed = pack.pack(clips, layout="packed")
    document = atlas.gamemaker(packed, "hero")
    assert document["importAs"] == "frames"
    assert "strip" not in document


def test_rpgmaker_needs_all_four_cardinals_and_says_which_are_missing():
    clips = [pack.Clip("walk", frames(3, 8, 10, [1, 2, 3, 255]), direction="E")]
    pixels, report = atlas.rpgmaker_sheet(clips)
    assert pixels is None
    assert not report["written"]
    assert "--directions 4" in report["reason"]


def test_rpgmaker_lays_out_three_columns_by_four_rows_in_mv_order():
    clips = [pack.Clip("walk", frames(8, 8, 10, [1, 2, 3, 255]), direction=d)
             for d in ("S", "W", "E", "N")]
    pixels, report = atlas.rpgmaker_sheet(clips)
    assert report["written"]
    assert report["rows"] == ["S", "W", "E", "N"]
    assert pixels.shape[1] == report["cell"][0] * 3
    assert pixels.shape[0] == report["cell"][1] * 4
    assert "$" in report["filename_note"]


def test_rpgmaker_samples_one_stride_not_one_cycle():
    """MV plays the columns 0,1,2,1, so three columns must span half the loop."""
    clips = [pack.Clip("walk", frames(8, 8, 10, [1, 2, 3, 255]), direction=d)
             for d in ("S", "W", "E", "N")]
    _, report = atlas.rpgmaker_sheet(clips)
    assert report["frames_used"]["S"] == [0, 2, 4]


def test_the_zip_holds_exactly_the_atlas_frames_cut_from_the_sheet(sheet, tmp_path):
    path = str(tmp_path / "frames.zip")
    count = atlas.write_frames_zip(sheet, path)
    assert count == len(sheet.placements)
    with zipfile.ZipFile(path) as archive:
        names = {n[:-4] for n in archive.namelist()}
        assert names == {p.name for p in sheet.placements}


def test_write_produces_every_requested_engine(sheet, tmp_path, clips):
    written = atlas.write(sheet, str(tmp_path), "hero", engines=("all",), clips=clips)
    for key in ("sheet", "atlas", "unity", "godot", "phaser", "aseprite",
                "gamemaker", "unreal", "frames_zip"):
        assert key in written, key


def test_write_refuses_an_unknown_engine(sheet, tmp_path):
    with pytest.raises(ValueError) as error:
        atlas.write(sheet, str(tmp_path), "hero", engines=("unity6",))
    assert "unity6" in str(error.value)


def test_the_web_set_writes_only_web_formats(sheet, tmp_path):
    written = atlas.write(sheet, str(tmp_path), "hero", engines=("web",))
    assert "unity" not in written and "godot" not in written
    assert "phaser" in written


# -- the compressed sheet --------------------------------------------------

def test_an_indexed_sheet_is_pixel_identical(sheet, tmp_path, clips):
    """Lossless, not quantised: the sheet's palette is the source art's own."""
    written = atlas.write(sheet, str(tmp_path), "hero", engines=("web",),
                          clips=clips, compress=True)
    assert image.equal(image.load(written["sheet"]), sheet.pixels)


def test_an_indexed_sheet_is_only_kept_when_it_is_smaller(sheet, tmp_path, clips):
    """A 256-entry palette table is a fixed cost that a tiny sheet loses on."""
    plain_dir, small_dir = str(tmp_path / "a"), str(tmp_path / "b")
    plain = atlas.write(sheet, plain_dir, "hero", engines=("web",), clips=clips)
    packed = atlas.write(sheet, small_dir, "hero", engines=("web",), clips=clips,
                         compress=True)
    assert os.path.getsize(packed["sheet"]) <= os.path.getsize(plain["sheet"])
    assert "indexed" in packed["sheet_format"] or "full RGBA" in packed["sheet_format"]


def test_a_sheet_with_too_many_colours_stays_rgba(tmp_path):
    rng = np.random.default_rng(11)
    noisy = image.blank(40, 40)
    noisy[:, :, :3] = rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)
    noisy[:, :, 3] = 255
    assert not image.save_indexed(noisy, str(tmp_path / "x.png"))


def test_save_indexed_keeps_transparency(tmp_path):
    art = image.blank(8, 8)
    art[2:6, 2:6] = [200, 40, 40, 255]
    path = str(tmp_path / "x.png")
    assert image.save_indexed(art, path)
    assert image.equal(image.load(path), art)


# -- the strip layout ------------------------------------------------------

def test_a_strip_is_one_row_of_every_frame(clips):
    strip = pack.pack(clips, layout="strip", padding=1, extrude=1)
    total = sum(len(c.frames) for c in clips)
    assert len(strip.placements) == total
    assert len({p.y for p in strip.placements}) == 1, "a strip has exactly one row"
    assert strip.size[1] < strip.size[0]


def test_a_strip_keeps_the_grid_cell_and_anchor(clips):
    grid = pack.pack(clips, layout="grid", padding=1, extrude=1)
    strip = pack.pack(clips, layout="strip", padding=1, extrude=1)
    assert strip.cell == grid.cell
    assert {tuple(p.anchor) for p in strip.placements} == {tuple(p.anchor) for p in grid.placements}


def test_a_strip_frame_matches_the_grid_frame(clips):
    grid = pack.pack(clips, layout="grid", padding=1, extrude=1)
    strip = pack.pack(clips, layout="strip", padding=1, extrude=1)
    by_name = {p.name: p for p in grid.placements}
    for placement in strip.placements:
        other = by_name[placement.name]
        assert image.equal(
            strip.pixels[placement.y:placement.y + placement.height,
                         placement.x:placement.x + placement.width],
            grid.pixels[other.y:other.y + other.height,
                        other.x:other.x + other.width])


def test_an_unknown_layout_is_refused_by_name():
    with pytest.raises(ValueError) as error:
        pack.pack([pack.Clip("a", frames(2, 4, 4, [1, 2, 3, 255]))], layout="spiral")
    assert "spiral" in str(error.value)


# -- one folder per animation ---------------------------------------------

def test_the_per_animation_zip_has_a_folder_for_each_clip(sheet, tmp_path):
    path = tmp_path / "anim.zip"
    count = atlas.write_animation_zip(sheet, str(path), "hero")
    with zipfile.ZipFile(str(path)) as archive:
        names = set(archive.namelist())
    for clip_key in sheet.by_clip():
        assert "%s/spritesheet.png" % clip_key in names
        assert "%s/atlas.json" % clip_key in names
        assert "%s/frames/01.png" % clip_key in names
    assert count == sum(len(p) for p in sheet.by_clip().values())


def test_each_animation_folder_carries_its_own_timing(sheet, tmp_path):
    path = tmp_path / "anim.zip"
    atlas.write_animation_zip(sheet, str(path), "hero")
    with zipfile.ZipFile(str(path)) as archive:
        for clip_key in sheet.by_clip():
            local = json.loads(archive.read("%s/atlas.json" % clip_key).decode())
            clip = sheet.clip(clip_key)
            assert local["fps"] == clip.fps
            assert local["loop"] == clip.loop
            assert local["animation"] == clip.name
            assert local["image"] == "spritesheet.png"


def test_every_frame_in_the_folder_is_the_master_sheet_s_own_bytes(sheet, tmp_path):
    """A second copy of the same pixels is exactly the thing that drifts, so it
    only earns its place if it is provably the same bytes."""
    path = tmp_path / "anim.zip"
    atlas.write_animation_zip(sheet, str(path), "hero")
    with zipfile.ZipFile(str(path)) as archive:
        for clip_key, placements in sheet.by_clip().items():
            for index, placement in enumerate(placements):
                stored = np.array(PILImage.open(io.BytesIO(
                    archive.read("%s/frames/%02d.png" % (clip_key, index + 1))
                )).convert("RGBA"), dtype=np.uint8)
                master = sheet.pixels[
                    placement.y:placement.y + placement.height,
                    placement.x:placement.x + placement.width]
                assert image.equal(stored, master)


def test_the_strip_is_its_own_frames_laid_side_by_side(sheet, tmp_path):
    path = tmp_path / "anim.zip"
    atlas.write_animation_zip(sheet, str(path), "hero")
    with zipfile.ZipFile(str(path)) as archive:
        for clip_key in sheet.by_clip():
            strip = np.array(PILImage.open(io.BytesIO(
                archive.read("%s/spritesheet.png" % clip_key))).convert("RGBA"),
                dtype=np.uint8)
            local = json.loads(archive.read("%s/atlas.json" % clip_key).decode())
            assert strip.shape[1] == local["size"]["w"]
            for entry in local["frames"]:
                cut = strip[entry["y"]:entry["y"] + entry["h"],
                            entry["x"]:entry["x"] + entry["w"]]
                stored = np.array(PILImage.open(io.BytesIO(
                    archive.read("%s/frames/%s.png" % (clip_key, entry["name"]))
                )).convert("RGBA"), dtype=np.uint8)
                assert image.equal(cut, stored)
