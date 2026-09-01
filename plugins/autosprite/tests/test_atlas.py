"""Each engine file must be the thing that engine's importer actually reads."""

import re
import zipfile

import pytest

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
