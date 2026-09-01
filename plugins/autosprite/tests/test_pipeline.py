"""End to end, on every fixture, with the verifier as the judge."""

import json
import os

import pytest

from spritepipe import image, ingest, motion, pipeline


def build(path, out, **kwargs):
    kwargs.setdefault("animations", ["basic"])
    kwargs.setdefault("engines", ("all",))
    return pipeline.build_sheet(path, str(out), **kwargs)


def test_a_character_builds_and_verifies(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["full"])
    assert result.verification.ok, result.verification.report()
    assert len(result.clips) == 7
    assert os.path.exists(result.written["sheet"])
    assert os.path.exists(result.written["rig"])


def test_a_creature_builds_and_verifies(beast_path, tmp_path):
    result = build(beast_path, tmp_path / "out", animations=["idle", "walk"])
    assert result.verification.ok, result.verification.report()
    assert result.rigs["side"].character_class == "creature"


def test_a_prop_builds_and_verifies(gem_path, tmp_path):
    result = build(gem_path, tmp_path / "out", kind="prop", animations=["pickup"])
    assert result.verification.ok, result.verification.report()
    assert [c.name for c in result.clips] == ["bob", "spin"]
    assert len(result.rigs["side"].parts) == 1


def test_every_output_frame_is_drawn_from_the_source_palette(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["full"])
    allowed = {tuple(c) for c in ingest.ingest(hero_path).palette}
    assert {tuple(c) for c in image.unique_colors(result.sheet.pixels)} <= allowed


def test_each_clip_gets_its_own_tight_box(hero_path, tmp_path):
    """Cropping everything to the death rotation's box doubles the texture."""
    result = build(hero_path, tmp_path / "out", animations=["idle", "die"])
    sizes = {clip.key: clip.frames[0].shape[:2] for clip in result.clips}
    assert sizes["idle"] != sizes["die"]
    assert sizes["idle"][1] < sizes["die"][1]


def test_the_grid_still_puts_every_anchor_on_one_pixel(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["full"], layout="grid")
    assert len({tuple(p.anchor) for p in result.sheet.placements}) == 1


def test_packed_is_smaller_than_grid(hero_path, tmp_path):
    grid = build(hero_path, tmp_path / "g", animations=["full"], layout="grid")
    packed = build(hero_path, tmp_path / "p", animations=["full"], layout="packed")
    assert (packed.sheet.size[0] * packed.sheet.size[1]
            < grid.sheet.size[0] * grid.sheet.size[1])


def test_four_directions_produce_four_clips_each(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["walk"], direction_set="4")
    assert sorted(clip.key for clip in result.clips) == [
        "walk_E", "walk_N", "walk_S", "walk_W"]
    assert result.verification.ok, result.verification.report()


def test_four_directions_write_an_rpgmaker_sheet(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["walk"], direction_set="4")
    assert result.written["rpgmaker_report"]["written"]
    assert os.path.basename(result.written["rpgmaker"]).startswith("$")


def test_one_direction_says_why_rpgmaker_was_skipped(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["walk"])
    report = result.written["rpgmaker_report"]
    assert not report["written"] and "--directions 4" in report["reason"]


def test_approximated_directions_are_warned_about(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["idle"], direction_set="8")
    assert any("foreshortened" in warning for warning in result.report["warnings"])


def test_a_front_reference_is_used_for_south(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["idle"],
                   direction_set="4", front=hero_path)
    south = next(d for d in result.report["directions"] if d["name"] == "S")
    assert south["fidelity"] == "drawn" and south["source"] == "front"


def test_a_custom_animation_joins_the_built_ins(hero_path, tmp_path):
    spec = [{"name": "taunt", "frames": 4, "fps": 8, "loop": False,
             "tracks": {"arm_near": [{"t": 0, "angle": 0}, {"t": 1, "angle": -95}]}}]
    path = str(tmp_path / "custom.json")
    open(path, "w").write(json.dumps(spec))
    result = build(hero_path, tmp_path / "out", animations=["idle"],
                   custom_animations=motion.load_custom(path))
    assert "taunt" in [clip.name for clip in result.clips]
    assert result.verification.ok, result.verification.report()


def test_the_atlas_on_disk_describes_what_was_built(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["idle", "walk"])
    with open(result.written["atlas"]) as handle:
        document = json.load(handle)
    assert {c["key"] for c in document["clips"]} == {"idle", "walk"}
    assert document["size"] == {"w": result.sheet.size[0], "h": result.sheet.size[1]}
    assert document["source"]["palette_size"] == len(result.references["side"].palette)


def test_a_gif_and_a_contact_sheet_are_written_for_review(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["idle", "walk"])
    assert set(result.previews["gifs"]) == {"idle", "walk"}
    for path in list(result.previews["gifs"].values()) + [result.previews["contact_sheet"]]:
        assert os.path.getsize(path) > 0


def test_an_upscaled_source_is_rigged_at_native_size(tmp_path):
    import make_fixture
    art = make_fixture.humanoid()
    path = str(tmp_path / "big.png")
    make_fixture.write(path, make_fixture.on_background(art, upscale=4))
    result = build(path, tmp_path / "out", animations=["walk"])
    assert result.references["side"].scale == 4
    assert result.rigs["side"].size == image.trim(art)[0].shape[:2][::-1]
    assert result.verification.ok, result.verification.report()


def test_scale_upscales_the_art_but_not_the_gutter(hero_path, tmp_path):
    """The gutter exists to stop the GPU sampling a neighbour. One pixel of it
    is one pixel of it whatever the art is scaled to, so scaling it too would
    just waste texture."""
    plain = build(hero_path, tmp_path / "a", animations=["idle"])
    big = build(hero_path, tmp_path / "b", animations=["idle"], scale=4)
    assert big.sheet.cell == (plain.sheet.cell[0] * 4, plain.sheet.cell[1] * 4)
    assert big.sheet.size[0] < plain.sheet.size[0] * 4
    assert big.verification.ok, big.verification.report()


def test_a_named_sheet_names_every_file(hero_path, tmp_path):
    result = build(hero_path, tmp_path / "out", animations=["idle"], name="knight")
    assert os.path.basename(result.written["sheet"]) == "knight.png"
    assert os.path.basename(result.written["atlas"]) == "knight.autosprite.json"


def test_an_invalid_rig_is_refused_rather_than_animated(hero_path, tmp_path):
    class Broken:
        actor = "test:broken"

        def rig(self, reference, **kwargs):
            from spritepipe import rig as R
            return R.Rig(reference.size, [R.Part("a", "torso", (0, 0, 2, 2), "b", (1, 1)),
                                          R.Part("b", "head", (0, 0, 2, 2), "a", (1, 1))])

    with pytest.raises(ValueError) as error:
        build(hero_path, tmp_path / "out", backend=Broken())
    assert "not usable" in str(error.value)


def test_no_animations_selected_is_refused(hero_path, tmp_path):
    with pytest.raises(ValueError):
        build(hero_path, tmp_path / "out", animations=[])
