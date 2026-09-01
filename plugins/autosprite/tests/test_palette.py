"""The palette guarantee, and the ramps that make a recolour keep its shading."""

import numpy as np
import pytest

import make_fixture
from spritepipe import image, palette


RED_RAMP = [[90, 20, 20, 255], [180, 40, 40, 255], [240, 120, 120, 255]]
BLUE = [40, 80, 200, 255]
GREYS = [[20, 20, 22, 255], [130, 130, 134, 255]]


@pytest.fixture
def pal():
    return np.array(RED_RAMP + [BLUE] + GREYS, dtype=np.uint8)


def test_escapes_finds_a_colour_that_is_not_in_the_palette(pal):
    frame = image.blank(4, 4)
    frame[1:3, 1:3] = [181, 41, 41, 255]
    assert len(palette.escapes(frame, pal)) == 1


def test_enforce_snaps_a_stray_colour_to_its_nearest_neighbour(pal):
    frame = image.blank(4, 4)
    frame[1:3, 1:3] = [181, 41, 41, 255]
    fixed = palette.enforce(frame, pal)
    assert len(palette.escapes(fixed, pal)) == 0
    assert tuple(fixed[1, 1]) == (180, 40, 40, 255)


def test_enforce_leaves_an_already_clean_frame_untouched(pal):
    frame = image.blank(4, 4)
    frame[1:3, 1:3] = RED_RAMP[1]
    assert image.equal(palette.enforce(frame, pal), frame)


def test_enforce_never_touches_transparency(pal):
    frame = image.blank(4, 4)
    frame[1, 1] = [181, 41, 41, 255]
    fixed = palette.enforce(frame, pal)
    assert fixed[0, 0][3] == 0


def test_shades_of_one_hue_group_into_one_ramp(pal):
    ramps = palette.ramps(pal)
    reds = [r for r in ramps if not r["grey"] and len(r["colours"]) == 3]
    assert len(reds) == 1
    assert [c[0] for c in reds[0]["colours"]] == sorted(c[0] for c in reds[0]["colours"])


def test_a_ramp_is_ordered_dark_to_light(pal):
    for ramp in palette.ramps(pal):
        values = [palette.luminance(c) for c in ramp["colours"]]
        assert values == sorted(values)


def test_greys_group_together_rather_than_by_hue(pal):
    greys = [r for r in palette.ramps(pal) if r["grey"]]
    assert len(greys) == 1
    assert len(greys[0]["colours"]) == 2


def test_every_palette_entry_lands_in_exactly_one_ramp(pal):
    ramps = palette.ramps(pal)
    placed = [tuple(c) for ramp in ramps for c in ramp["colours"]]
    assert sorted(placed) == sorted(tuple(int(v) for v in c) for c in pal)


def test_coverage_ranks_the_base_colour_first():
    art = image.trim(make_fixture.humanoid())[0]
    counts = palette.coverage(art, palette.lock(art))
    assert counts[0]["pixels"] >= counts[-1]["pixels"]
    assert sum(c["share"] for c in counts) == pytest.approx(1.0, abs=1e-3)


def test_lock_returns_only_opaque_colours():
    art = image.trim(make_fixture.humanoid())[0]
    locked = palette.lock(art)
    assert (locked[:, 3] == 255).all()


def test_an_empty_palette_enforces_nothing():
    frame = image.blank(2, 2)
    frame[0, 0] = [1, 2, 3, 255]
    assert image.equal(palette.enforce(frame, np.zeros((0, 4), np.uint8)), frame)


def test_adjacency_separates_two_materials_that_share_a_hue():
    """Brown boots and tan skin sit within a few degrees of each other on any
    real sprite. Hue alone merges them at every tolerance; not touching does not."""
    art = image.trim(make_fixture.humanoid())[0]
    locked = palette.lock(art)
    by_hue = palette.ramps(locked)
    by_touch = palette.ramps(locked, art)
    assert len(by_touch) > len(by_hue)
    boots = [r for r in by_touch if [38, 32, 28, 255] in r["colours"]]
    assert len(boots) == 1
    assert [232, 196, 152, 255] not in boots[0]["colours"]


def test_shades_that_touch_stay_in_one_ramp():
    art = image.trim(make_fixture.humanoid())[0]
    ramps = palette.ramps(palette.lock(art), art)
    cloth = [r for r in ramps if [52, 88, 172, 255] in r["colours"]]
    assert len(cloth) == 1 and len(cloth[0]["colours"]) == 3


def test_materials_of_different_hues_never_merge_even_when_touching():
    art = image.trim(make_fixture.humanoid())[0]
    for ramp in palette.ramps(palette.lock(art), art):
        hues = [palette._hue_sat(c)[0] for c in ramp["colours"]]
        assert max(hues) - min(hues) < 40


def test_every_colour_still_lands_in_exactly_one_ramp_with_adjacency():
    art = image.trim(make_fixture.humanoid())[0]
    locked = palette.lock(art)
    placed = [tuple(c) for ramp in palette.ramps(locked, art) for c in ramp["colours"]]
    assert sorted(placed) == sorted(tuple(int(v) for v in c) for c in locked)


def test_ramp_ids_are_stable_and_ordered_by_size():
    art = image.trim(make_fixture.humanoid())[0]
    ramps = palette.ramps(palette.lock(art), art)
    assert [r["id"] for r in ramps] == list(range(len(ramps)))
    sizes = [len(r["colours"]) for r in ramps]
    assert sizes == sorted(sizes, reverse=True)


# ---------------------------------------------------------------------------
# Stepping along a ramp: an operation that is not a transform at all.
# ---------------------------------------------------------------------------

def _ramped():
    """A red material of four shades, outlined in the darkest red of the same
    hue -- which is what puts the outline INSIDE the material's ramp, as
    happened on the first real gem this was run against."""
    shades = [(28, 12, 12), (60, 30, 30), (110, 55, 55), (170, 85, 85),
              (220, 140, 140)]
    pixels = image.blank(5, 5)
    for row, shade in enumerate(shades):
        pixels[row, :] = list(shade) + [255]
    return pixels


def test_a_step_lands_on_another_shade_of_the_same_ramp():
    pixels = _ramped()
    locked = palette.lock(pixels)
    table = palette.ramp_steps(locked, pixels)
    for step in (-3, -1, 1, 3):
        moved = palette.step_ramp(pixels, table, step)
        assert len(palette.escapes(moved, locked)) == 0


def test_a_step_of_zero_returns_the_art_untouched():
    pixels = _ramped()
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    assert image.equal(palette.step_ramp(pixels, table, 0), pixels)


def test_a_step_brightens_and_a_negative_step_darkens():
    pixels = _ramped()
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    before = palette.luminance(tuple(int(v) for v in pixels[2, 0][:3]))
    up = palette.luminance(tuple(int(v) for v in palette.step_ramp(pixels, table, 1)[2, 0][:3]))
    down = palette.luminance(tuple(int(v) for v in palette.step_ramp(pixels, table, -1)[2, 0][:3]))
    assert down < before < up


def test_a_step_clamps_rather_than_wrapping():
    """A highlight that brightens past white and reappears as the darkest
    shadow is not a highlight, it is a glitch.

    `keep_shading=False` because a step of fifty flattens the ramp and the
    shading rule would refuse it outright; this is about where the clamp lands,
    which is a separate question from whether the step is allowed.
    """
    pixels = _ramped()
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    far = palette.step_ramp(pixels, table, 50, keep_shading=False)
    brightest = max((tuple(int(v) for v in colour[:3])
                     for colour in palette.lock(pixels)), key=palette.luminance)
    assert all(tuple(int(v) for v in far[row, 0][:3]) == brightest
               for row in range(1, 5))


def test_nothing_steps_down_onto_the_outline_either():
    """Holding the outline still is only half of it: a fill shade darkening
    onto the outline colour thickens the outline, which reads the same way."""
    pixels = _ramped()
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    outline = tuple(int(v) for v in pixels[0, 0])
    dark = palette.step_ramp(pixels, table, -9)
    assert all(tuple(int(v) for v in dark[row, 0]) != outline for row in range(1, 5))


def test_the_darkest_shade_does_not_move_because_it_is_the_outline():
    """Ramps are found by hue and adjacency, and an outline touches everything
    it surrounds, so it lands in the ramp of whatever it outlines. Lifting it
    with the fill makes the sprite go soft at the edges, which is the most
    obvious tell there is."""
    pixels = _ramped()
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    outline = tuple(int(v) for v in pixels[0, 0])
    assert tuple(int(v) for v in palette.step_ramp(pixels, table, 3)[0, 0]) == outline
    assert tuple(int(v) for v in palette.step_ramp(pixels, table, 3, keep_outline=False)[0, 0]) \
        != outline


def test_a_transparent_pixel_is_left_transparent():
    pixels = _ramped()
    pixels[4, 4] = [0, 0, 0, 0]
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    assert palette.step_ramp(pixels, table, 2)[4, 4][3] == 0


def test_one_shade_does_not_cascade_into_the_next():
    """The bug this guards: matching against the array being written.

    Rewriting the darkest fill as the second shade, then reaching the second
    shade's turn and matching BOTH the original pixels and the ones just
    written, walks every shade in the ramp to the top. It survived a visual
    check for an hour, because a washed-out sprite is a plausible thing for a
    brightening step to produce.
    """
    pixels = _ramped()
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    stepped = palette.step_ramp(pixels, table, 1, keep_shading=False)
    # Five rows, five shades, one step up: the top two merge at the clamp and
    # everything else keeps its neighbours apart.
    assert palette._shade_count(stepped) == 4


def test_a_part_with_nowhere_to_go_is_left_exactly_as_it_was():
    """A flat block is not a brighter version of a shaded thing, so when even a
    single step would flatten one, nothing happens at all. That is the palette
    guarantee doing its job: the brighter shade was never drawn."""
    shades = [(30, 14, 14), (150, 80, 40), (230, 190, 90)]
    pixels = image.blank(3, 4)
    for row, shade in enumerate(shades):
        pixels[row, :] = list(shade) + [255]
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    # Three shades, one of which is the outline and does not move, so there are
    # two movable shades and any step at all merges them. Neither direction is
    # available and both are refused.
    assert image.equal(palette.step_ramp(pixels, table, 1), pixels)
    assert image.equal(palette.step_ramp(pixels, table, -1), pixels)


def test_a_step_too_large_falls_back_to_one_that_fits():
    """Reduced until it stops costing shades, rather than refused outright --
    a clip asking for three steps on a shallow ramp should still move."""
    pixels = _ramped()
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    assert image.equal(palette.step_ramp(pixels, table, 3),
                       palette.step_ramp(pixels, table, 1, keep_shading=False))


def test_a_deep_ramp_steps_both_ways_by_the_same_amount():
    """Brightening and darkening are symmetric. They looked asymmetric while
    the cascade above was live, and that was the bug, not the art."""
    shades = [(20 + step * 24, 14 + step * 20, 12 + step * 18) for step in range(9)]
    pixels = image.blank(9, 4)
    for row, shade in enumerate(shades):
        pixels[row, :] = list(shade) + [255]
    table = palette.ramp_steps(palette.lock(pixels), pixels)
    up = palette._shade_count(palette.step_ramp(pixels, table, 1, keep_shading=False))
    down = palette._shade_count(palette.step_ramp(pixels, table, -1, keep_shading=False))
    assert up == down
