"""Normalising whatever the user actually has."""

import numpy as np
import pytest

import make_fixture
from spritepipe import image, ingest


def test_flood_removes_a_white_background(tmp_path):
    art = make_fixture.humanoid()
    path = str(tmp_path / "on-white.png")
    make_fixture.write(path, make_fixture.on_background(art, (255, 255, 255, 255)))
    reference = ingest.ingest(path)
    assert "flood" in reference.report["background"]
    assert image.equal(reference.pixels, image.trim(art)[0])


def test_existing_alpha_is_believed_over_a_flood(tmp_path):
    """An artist who exported with alpha has already answered this question."""
    art = make_fixture.humanoid()
    padded = image.blank(art.shape[0] + 6, art.shape[1] + 6)
    image.paste(padded, art, 3, 3)
    path = str(tmp_path / "alpha.png")
    make_fixture.write(path, padded)
    reference = ingest.ingest(path)
    assert "source alpha" in reference.report["background"]


@pytest.mark.parametrize("factor", [2, 4, 6])
def test_an_upscaled_source_is_worked_at_native_size(tmp_path, factor):
    art = make_fixture.humanoid()
    path = str(tmp_path / "big.png")
    make_fixture.write(path, make_fixture.on_background(art, upscale=factor))
    reference = ingest.ingest(path)
    assert reference.scale == factor
    assert image.equal(reference.pixels, image.trim(art)[0])
    assert "pixel_scale_note" in reference.report


def test_native_can_be_switched_off(tmp_path):
    art = make_fixture.humanoid()
    path = str(tmp_path / "big.png")
    make_fixture.write(path, make_fixture.on_background(art, upscale=3))
    reference = ingest.ingest(path, native=False)
    trimmed = image.trim(art)[0]
    assert reference.scale == 1
    assert reference.size == (trimmed.shape[1] * 3, trimmed.shape[0] * 3)


def test_detect_pixel_scale_ignores_a_non_multiple():
    art = image.blank(7, 5)
    art[:, :] = [1, 2, 3, 255]
    assert ingest.detect_pixel_scale(art) == 1


def test_palette_art_is_classified_as_indexed(hero):
    assert hero.report["art_kind"] == "indexed"
    assert len(hero.palette) <= 64


def test_noisy_art_is_flagged_as_continuous(tmp_path):
    """The palette guarantee still holds, but it stops meaning much."""
    rng = np.random.default_rng(7)
    noisy = image.blank(40, 40)
    noisy[:, :, :3] = rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)
    noisy[:, :, 3] = 255
    padded = image.blank(48, 48)
    padded[:, :] = [255, 255, 255, 255]
    image.paste(padded, noisy, 4, 4)
    path = str(tmp_path / "noise.png")
    make_fixture.write(path, padded)
    reference = ingest.ingest(path)
    assert reference.report["art_kind"] == "continuous"
    assert "nearest-neighbour" in reference.report["art_note"]


def test_an_all_background_image_is_refused_with_the_path(tmp_path):
    blank = image.blank(12, 12)
    blank[:, :] = [255, 255, 255, 255]
    path = str(tmp_path / "blank.png")
    make_fixture.write(path, blank)
    with pytest.raises(ValueError) as error:
        ingest.ingest(path)
    assert "blank.png" in str(error.value)


def test_a_gradient_background_does_not_eat_the_character(tmp_path):
    """The flood compares against its seed, not a running average."""
    art = make_fixture.humanoid()
    canvas = image.blank(art.shape[0] + 8, art.shape[1] + 8)
    for y in range(canvas.shape[0]):
        canvas[y, :] = [200 + y % 40, 210, 220, 255]
    image.paste(canvas, art, 4, 4)
    path = str(tmp_path / "gradient.png")
    make_fixture.write(path, canvas)
    reference = ingest.ingest(path)
    kept = int(image.alpha_mask(reference.pixels).sum())
    assert kept >= int(image.alpha_mask(art).sum()) * 0.95
