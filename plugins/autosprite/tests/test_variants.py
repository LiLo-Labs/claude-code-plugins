"""Recolouring by ramp, so the shading survives."""

import numpy as np
import pytest

import make_fixture
from spritepipe import image, palette, variants


@pytest.fixture
def art():
    return image.trim(make_fixture.humanoid())[0]


@pytest.fixture
def ramps(art):
    return palette.ramps(palette.lock(art))


def test_describe_ranks_by_how_much_of_the_sprite_a_ramp_covers(art, ramps):
    described = variants.describe(art, ramps)
    assert described[0]["pixels"] >= described[-1]["pixels"]
    assert sum(entry["share"] for entry in described) == pytest.approx(1.0, abs=1e-3)


def test_describe_locates_each_ramp_so_a_model_need_not_guess(art, ramps):
    for entry in variants.describe(art, ramps):
        if entry["pixels"]:
            assert 0.0 <= entry["centroid"][0] <= 1.0
            assert 0.0 <= entry["centroid"][1] <= 1.0


def test_the_ramp_atlas_shows_one_ramp_lit_and_the_rest_dimmed(art, ramps):
    frames = variants.ramp_atlas(art, ramps)
    assert len(frames) == len(ramps)
    for frame, ramp in zip(frames, ramps):
        present = {tuple(c) for c in image.unique_colors(frame)}
        assert {tuple(c) for c in ramp["colours"]} <= present
        assert image.alpha_mask(frame).sum() == image.alpha_mask(art).sum()


def test_retint_keeps_the_value_so_the_shading_survives():
    dark = variants.retint([90, 20, 20, 255], hue=210)
    light = variants.retint([240, 120, 120, 255], hue=210)
    assert palette.luminance(dark) < palette.luminance(light)


def test_retint_changes_the_hue_it_was_given():
    import colorsys
    out = variants.retint([180, 40, 40, 255], hue=210)
    hue = colorsys.rgb_to_hsv(*[v / 255.0 for v in out[:3]])[0] * 360
    assert abs(hue - 210) < 3


def test_retint_keeps_alpha():
    assert variants.retint([180, 40, 40, 128], hue=90)[3] == 128


def test_a_whole_ramp_moves_together(art, ramps):
    target = ramps[0]
    names = {ramp["id"]: ("target" if ramp is target else "other") for ramp in ramps}
    out, report = variants.variant(art, {"target": {"hue": 300}}, names, ramps)
    assert report["colours_changed"] == len(target["colours"])
    assert image.alpha_mask(out).sum() == image.alpha_mask(art).sum()


def test_a_recolour_keeps_the_silhouette_exactly(art, ramps):
    names = {ramp["id"]: str(ramp["id"]) for ramp in ramps}
    out, _ = variants.variant(art, {"0": {"hue": 120}}, names, ramps)
    assert (image.alpha_mask(out) == image.alpha_mask(art)).all()


def test_an_unmatched_ramp_name_is_reported_with_what_does_exist(art, ramps):
    out, report = variants.variant(art, {"cape": {"hue": 30}},
                                   {ramp["id"]: "cloak" for ramp in ramps}, ramps)
    assert report["unmatched"] == ["cape"]
    assert "cloak" in report["hint"]
    assert image.equal(out, art)


def test_explicit_colours_must_be_given_shade_for_shade(ramps, art):
    biggest = max(ramps, key=lambda ramp: len(ramp["colours"]))
    names = {biggest["id"]: "cloth"}
    with pytest.raises(ValueError) as error:
        variants.variant(art, {"cloth": {"colours": [[1, 2, 3, 255]]}}, names, ramps)
    assert "shade for shade" in str(error.value)


def test_explicit_colours_replace_the_ramp_in_order(art, ramps):
    biggest = max(ramps, key=lambda ramp: len(ramp["colours"]))
    replacement = [[10 * (i + 1), 20, 30, 255] for i in range(len(biggest["colours"]))]
    out, _ = variants.variant(art, {"x": {"colours": replacement}},
                              {biggest["id"]: "x"}, ramps)
    present = {tuple(c) for c in image.unique_colors(out)}
    assert {tuple(c) for c in replacement} <= present


def test_a_grey_ramp_can_be_refused_a_hue():
    """Steel to gold wants the tint; an outline never does."""
    steel = np.array([[40, 40, 40, 255], [160, 160, 160, 255]], dtype=np.uint8)
    kept = variants.retint(steel[1], hue=45, grey_to_hue=False)
    assert kept[0] == kept[1] == kept[2]
    tinted = variants.retint(steel[1], hue=45, grey_to_hue=True)
    assert not tinted[0] == tinted[1] == tinted[2]
