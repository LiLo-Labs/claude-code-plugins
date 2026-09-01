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
