"""Measuring whether a frame still looks like the character.

Every other check proves something about bookkeeping. These prove something
about the picture, and they exist because the bookkeeping checks all passed on
frames that were visibly wrong: mass is conserved when parts are merely
scrambled, and a detached three-pixel hand is below any blob-significance floor
worth setting.
"""

import numpy as np
import pytest

import make_fixture
from spritepipe import image, quality


def blob(size=6, at=(1, 1), colour=(200, 40, 40, 255), canvas=(20, 20)):
    art = image.blank(canvas[0], canvas[1])
    art[at[0]:at[0] + size, at[1]:at[1] + size] = colour
    return art


def test_one_solid_shape_has_no_debris():
    assert quality.debris(blob()) == 0.0


def test_a_detached_piece_is_debris():
    art = blob(size=6, at=(1, 1))
    art[15:17, 15:17] = [200, 40, 40, 255]      # 4 px adrift of a 36 px body
    assert quality.debris(art) == pytest.approx(4 / 40.0)


def test_a_diagonally_touching_piece_is_not_debris():
    """Eight-connected: a corner touch is still one character."""
    art = image.blank(20, 20)
    art[2:6, 2:6] = [1, 2, 3, 255]
    art[6:8, 6:8] = [1, 2, 3, 255]
    assert quality.debris(art) == 0.0


def test_an_empty_frame_is_not_a_division_by_zero():
    assert quality.debris(image.blank(8, 8)) == 0.0


def test_blob_sizes_are_largest_first():
    art = blob(size=2, at=(1, 1))
    art[10:16, 10:16] = [1, 2, 3, 255]
    assert quality.blob_sizes(image.alpha_mask(art)) == [36, 4]


def test_shed_ignores_debris_the_source_already_had():
    """A sprite drawn with a detached shadow starts non-zero, and that is not
    this plugin's doing. Only the excess is."""
    source = blob(size=6, at=(1, 1))
    source[15:17, 15:17] = [200, 40, 40, 255]
    worst, index = quality.shed([source.copy(), source.copy()], source)
    assert worst == 0.0 and index is None


def test_shed_finds_the_worst_frame_and_names_it():
    source = blob(size=6, at=(1, 1))
    clean = source.copy()
    broken = source.copy()
    broken[15:18, 15:18] = [200, 40, 40, 255]
    worst, index = quality.shed([clean, broken, clean], source)
    assert index == 1 and worst > 0.1


def test_shed_is_zero_when_every_frame_matches_the_source():
    art = image.trim(make_fixture.humanoid())[0]
    worst, index = quality.shed([art.copy() for _ in range(4)], art)
    assert worst == 0.0


def test_a_real_frame_that_comes_apart_is_caught():
    """The failure this module exists for: a limb sheared into loose pixels."""
    art = image.trim(make_fixture.humanoid())[0]
    torn = art.copy()
    mask = image.alpha_mask(torn)
    rows = np.flatnonzero(mask.any(axis=1))
    torn[rows[len(rows) // 2]] = 0            # cut the character in half
    worst, _ = quality.shed([torn], art)
    assert worst > 0.1


# ---------------------------------------------------------------------------
# Footprint: the first measurement here that asks whether the RIGHT pixels moved.
# ---------------------------------------------------------------------------

def _plain(colour, size=8):
    pixels = image.blank(size, size)
    pixels[:, :] = list(colour) + [255]
    return pixels


def test_a_clip_that_moves_nothing_has_no_footprint():
    rest = _plain((80, 80, 90))
    assert quality.footprint([rest, rest], rest, [rest, rest]) == (0.0, 0, 0)


def test_moving_exactly_what_the_artist_moved_scores_zero():
    rest = _plain((80, 80, 90))
    moved = rest.copy()
    moved[2:4, 2:4] = [200, 30, 30, 255]
    share, wrong, total = quality.footprint([rest, moved], rest, [rest, moved])
    assert (share, wrong, total) == (0.0, 0, 4)


def test_moving_pixels_the_artist_never_touches_is_caught():
    """The defect this exists for. Both clips below are perfectly intact and
    perfectly distinct; only this says which one is right."""
    rest = _plain((80, 80, 90))
    theirs = rest.copy()
    theirs[2:4, 2:4] = [200, 30, 30, 255]
    ours = rest.copy()
    ours[6:8, 6:8] = [200, 30, 30, 255]
    share, wrong, total = quality.footprint([rest, ours], rest, [rest, theirs])
    assert (wrong, total) == (4, 4) and share == 1.0


def test_shed_passes_the_very_clip_footprint_fails():
    """Stated outright, because it is why the measurement was added: a clip can
    be one connected blob in every frame and move entirely the wrong thing."""
    rest = _plain((80, 80, 90))
    theirs = rest.copy()
    theirs[0:2, 0:2] = [200, 30, 30, 255]
    ours = rest.copy()
    ours[6:8, 6:8] = [200, 30, 30, 255]
    assert quality.shed([rest, ours], rest)[0] == 0.0
    assert quality.footprint([rest, ours], rest, [rest, theirs])[0] == 1.0


def test_a_frame_of_a_different_size_is_compared_on_the_overlap():
    """Frames come back cropped to their common content box, so they are
    routinely a different shape from the source they are judged against."""
    rest = _plain((80, 80, 90))
    bigger = image.blank(12, 12)
    bigger[:8, :8] = rest
    bigger[1, 1] = [200, 30, 30, 255]
    theirs = rest.copy()
    theirs[1, 1] = [200, 30, 30, 255]
    share, _wrong, total = quality.footprint([bigger], rest, [rest, theirs])
    assert total > 0 and 0.0 <= share <= 1.0


def test_a_reference_cycle_of_a_different_size_does_not_raise():
    """Our rest pose goes through `ingest` and the artist's frames usually do
    not, so the two are routinely a row or two apart. Comparing them at their
    own sizes is a shape error waiting to happen -- and worse, a silent
    misalignment when it happens not to raise."""
    rest = _plain((80, 80, 90), size=8)
    ours = rest.copy()
    ours[2, 2] = [200, 30, 30, 255]
    bigger = _plain((80, 80, 90), size=10)
    theirs = bigger.copy()
    theirs[2, 2] = [200, 30, 30, 255]
    share, wrong, total = quality.footprint([ours], rest, [bigger, theirs])
    assert (share, wrong, total) == (0.0, 0, 1)


def test_the_two_footprints_are_aligned_at_the_top_left():
    """Which is right because everything here is cropped to its own content
    box, and is worth asserting because getting it wrong reads as a real
    difference rather than as a bug."""
    rest = _plain((80, 80, 90), size=8)
    ours = rest.copy()
    ours[1, 1] = [200, 30, 30, 255]
    bigger = _plain((80, 80, 90), size=12)
    theirs = bigger.copy()
    theirs[5, 5] = [200, 30, 30, 255]      # somewhere we do not touch
    share, wrong, total = quality.footprint([ours], rest, [bigger, theirs])
    assert (wrong, total) == (1, 1) and share == 1.0


def test_a_render_margin_must_be_declared_or_the_answer_is_nonsense():
    """The failure this parameter exists for. Rendered frames sit `margin`
    pixels in from the corner and the art they are judged against is trimmed
    flush, so measuring them as given compares a picture with a shifted copy of
    another one -- and reports a plausible-looking number for it."""
    rest = _plain((80, 80, 90), size=8)
    ours = rest.copy()
    ours[2, 2] = [200, 30, 30, 255]
    theirs = rest.copy()
    theirs[2, 2] = [200, 30, 30, 255]

    padded = image.blank(12, 12)
    padded[2:10, 2:10] = ours

    told = quality.footprint([padded], rest, [rest, theirs], offset=(2, 2))
    assert told == (0.0, 0, 1)                    # exactly right
    untold = quality.footprint([padded], rest, [rest, theirs])
    assert untold[0] > 0.0                        # ... and wrong when not told


# ---------------------------------------------------------------------------
# `footprint` is one-sided by design, so it is gameable by doing less. Both of
# these were found by pointing it at a real character for the first time.
# ---------------------------------------------------------------------------

def _strip(shape, boxes):
    """Frames in which a given box is filled, over a common background."""
    base = image.blank(*shape)
    base[2:shape[0] - 2, 2:shape[1] - 2] = [90, 90, 120, 255]
    frames = []
    for box in boxes:
        frame = base.copy()
        if box is not None:
            x0, y0, x1, y1 = box
            frame[y0:y1, x0:x1] = [220, 80, 60, 255]
        frames.append(frame)
    return base, frames


def test_coverage_is_the_half_footprint_does_not_measure():
    """A clip that moves ten pixels, all of them right, scores 0% error and is
    not an animation."""
    rest, artist = _strip((20, 20), [None, (4, 4, 14, 14), (5, 5, 15, 15)])
    _rest, timid = _strip((20, 20), [(4, 4, 6, 6)])
    share, wrong, total = quality.footprint(timid, rest, artist)
    assert share == 0.0                      # every pixel it moves is right
    assert quality.coverage(timid, rest, artist) < 0.2   # and it moves almost none


def test_coverage_is_one_when_both_disturb_the_same_amount():
    rest, artist = _strip((20, 20), [None, (4, 4, 14, 14)])
    _rest, ours = _strip((20, 20), [(4, 4, 14, 14)])
    assert quality.coverage(ours, rest, artist) == pytest.approx(1.0)


def test_measuring_from_two_different_rests_is_not_a_comparison():
    """Every clip here starts from the source image and an artist's strip
    usually does not. Passing such a strip straight in measures their motion
    from their guard and ours from standing."""
    rest, artist = _strip((20, 20), [(2, 2, 8, 8), (4, 4, 14, 14)])
    _rest, ours = _strip((20, 20), [(4, 4, 14, 14)])
    from_their_guard = quality.footprint(ours, rest, artist)[0]
    from_the_same_rest = quality.footprint(ours, rest, [rest] + artist)[0]
    assert from_their_guard > from_the_same_rest
    assert from_the_same_rest == pytest.approx(0.0, abs=0.01)
