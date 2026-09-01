"""The raster primitives everything else assumes are exact."""

import pytest

from spritepipe import image


def block(height=6, width=6, colour=(200, 40, 40, 255)):
    canvas = image.blank(height, width)
    canvas[1:height - 1, 1:width - 1] = colour
    return canvas


def test_content_box_is_half_open_and_tight():
    canvas = image.blank(10, 10)
    canvas[3:7, 2:5] = [1, 2, 3, 255]
    assert image.content_box(canvas) == (2, 3, 5, 7)


def test_content_box_of_empty_is_none():
    assert image.content_box(image.blank(4, 4)) is None


def test_trim_round_trips_through_crop():
    canvas = block(8, 8)
    trimmed, box = image.trim(canvas)
    assert box == (1, 1, 7, 7)
    assert image.equal(trimmed, image.crop(canvas, box))


def test_paste_is_an_alpha_test_not_a_blend():
    """Two overlapping parts must never average into a third colour."""
    target = image.blank(4, 4)
    target[:, :] = [255, 0, 0, 255]
    source = image.blank(4, 4)
    source[0:2, 0:2] = [0, 0, 255, 128]     # half-transparent, above the floor
    image.paste(target, source, 0, 0)
    assert tuple(target[0, 0]) == (0, 0, 255, 128)
    assert tuple(target[3, 3]) == (255, 0, 0, 255)
    assert len(image.unique_colors(target)) == 2


def test_paste_clips_at_every_edge():
    target = image.blank(4, 4)
    source = image.blank(4, 4)
    source[:, :] = [9, 9, 9, 255]
    for x, y in ((-2, -2), (2, 2), (-9, 0), (0, 9)):
        image.paste(target, source, x, y)
    assert target.shape == (4, 4, 4)


def test_harden_alpha_zeroes_the_colour_of_absent_pixels():
    """Absent pixels must compare equal, or frame comparison is meaningless."""
    canvas = image.blank(2, 2)
    canvas[0, 0] = [200, 40, 40, 3]     # below ALPHA_FLOOR
    canvas[0, 1] = [200, 40, 40, 200]
    hardened = image.harden_alpha(canvas)
    assert tuple(hardened[0, 0]) == (0, 0, 0, 0)
    assert tuple(hardened[0, 1]) == (200, 40, 40, 255)


@pytest.mark.parametrize("factor", [2, 3, 5, 8])
def test_upscale_then_downscale_is_the_identity(factor):
    original = block(7, 5)
    assert image.equal(image.downscale_blocks(
        image.scale_nearest(original, factor), factor), original)


def test_scale_nearest_invents_no_colour():
    original = block(5, 5)
    before = {tuple(c) for c in image.unique_colors(original)}
    after = {tuple(c) for c in image.unique_colors(image.scale_nearest(original, 3))}
    assert after == before


def test_equal_is_shape_sensitive():
    assert not image.equal(image.blank(2, 2), image.blank(2, 3))


def test_save_load_round_trip_is_lossless(tmp_path):
    original = block(9, 11)
    path = str(tmp_path / "x.png")
    image.save(original, path)
    assert image.equal(image.load(path), original)


def test_unique_colors_ignores_transparent_by_default():
    canvas = image.blank(3, 3)
    canvas[0, 0] = [1, 2, 3, 255]
    assert len(image.unique_colors(canvas)) == 1
    assert len(image.unique_colors(canvas, include_transparent=True)) == 2


# ---------------------------------------------------------------------------
# wave_columns: the one deformation here that is not a rigid transform.
# ---------------------------------------------------------------------------

def _striped(height=12, width=16):
    art = image.blank(height, width)
    for row in range(height):
        art[row, :] = [10 + row * 15, 40, 200 - row * 10, 255]
    return art


def test_a_wave_invents_no_colour_because_it_is_a_permutation():
    """The strongest palette claim in the vocabulary: every output pixel is an
    input pixel moved by a whole number of rows. Nothing is sampled, averaged
    or interpolated, so there is nothing for `enforce` to catch."""
    art = _striped()
    before = {tuple(int(v) for v in colour) for colour in image.unique_colors(art)}
    waved = image.wave_columns(art, 4.0, 0.25)
    after = {tuple(int(v) for v in colour) for colour in image.unique_colors(waved)}
    assert after <= before


def test_a_wave_moves_whole_pixels_only():
    """A half-pixel slide would need a colour between two rows, which is the
    one thing this pipeline may not make."""
    art = _striped()
    waved = image.wave_columns(art, 3.0, 0.0)
    for column in range(art.shape[1]):
        theirs = [tuple(int(v) for v in pixel) for pixel in waved[:, column]
                  if pixel[3]]
        ours = [tuple(int(v) for v in pixel) for pixel in art[:, column] if pixel[3]]
        assert set(theirs) <= set(ours)


def test_a_wave_too_small_to_reach_a_pixel_does_nothing_at_all():
    art = _striped()
    assert image.equal(image.wave_columns(art, 0.3, 0.0), art)
    assert image.equal(image.wave_columns(art, 0.0, 0.5), art)


def test_a_wave_displaces_different_columns_differently():
    """Otherwise it is a translation, which the pipeline already had."""
    art = _striped()
    waved = image.wave_columns(art, 4.0, 0.0)
    columns = {waved[:, x].tobytes() for x in range(art.shape[1])}
    assert len(columns) > 1


def test_advancing_the_phase_moves_the_crest_along():
    """What makes the wave travel rather than stand still."""
    art = _striped()
    first = image.wave_columns(art, 4.0, 0.0)
    later = image.wave_columns(art, 4.0, 0.25)
    assert not image.equal(first, later)


def test_a_whole_cycle_of_phase_returns_the_same_picture():
    art = _striped()
    assert image.equal(image.wave_columns(art, 4.0, 0.0),
                       image.wave_columns(art, 4.0, 1.0))


def test_what_slides_off_the_end_leaves_transparency_not_a_wrap():
    """A column that wrapped would put the top of the flag at its bottom."""
    art = _striped(height=6, width=4)
    waved = image.wave_columns(art, 20.0, 0.0)
    assert not image.alpha_mask(waved).all()
