"""A generated frame made to obey the source's grid, palette and alpha.

The guarantee here is the plugin's usual one and it holds by CONSTRUCTION: every
output pixel is a colour that was in the source, because every output pixel is
assigned one. A model that invents a colour cannot get it past this.
"""

import numpy as np
import pytest

from spritepipe import conform, image, ingest


def _sprite(height=8, width=6):
    art = image.blank(height, width)
    art[1:height - 1, 1:width - 1] = [40, 90, 160, 255]
    art[2:4, 2:4] = [200, 210, 240, 255]
    art[height - 2, 1:width - 1] = [20, 30, 60, 255]
    return art


def _as_a_model_would_return_it(art, scale=16, field=(0, 128, 128), noise=10,
                                seed=3):
    """The same sprite as a smooth, upscaled, noisy, opaque picture."""
    from PIL import Image, ImageFilter
    height, width = art.shape[:2]
    canvas = np.zeros((height, width, 4), np.uint8)
    canvas[..., :3] = field
    canvas[..., 3] = 255
    solid = image.alpha_mask(art)
    canvas[solid] = art[solid]
    big = Image.fromarray(canvas, "RGBA").resize(
        (width * scale, height * scale), Image.LANCZOS)
    big = big.filter(ImageFilter.GaussianBlur(scale / 6.0))
    out = np.array(big).astype(np.int16)
    if noise:
        out[..., :3] += np.random.RandomState(seed).randint(
            -noise, noise + 1, out[..., :3].shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def test_no_colour_survives_that_the_source_did_not_have():
    """The whole point. The model invents hundreds of colours; none get out."""
    art = _sprite()
    generated = _as_a_model_would_return_it(art)
    assert len(image.unique_colors(generated)) > 50      # the model invented a lot
    out, report = conform.conform(generated, art)
    assert report["invented"] > 0
    assert report["escaped"] == []
    assert conform.conforms(out, art)


def test_the_grid_is_the_source_s_grid():
    art = _sprite()
    generated = _as_a_model_would_return_it(art, scale=20)
    out, _report = conform.conform(generated, art)
    assert out.shape == art.shape


def test_a_block_is_reduced_by_its_median_not_its_mode():
    """A model's block is not flat, so every colour in it appears once and the
    mode is whatever the tie-break reaches. One outlier must not become the
    pixel."""
    block = np.zeros((1, 4, 4), np.uint8)
    block[0, :3] = [[10, 10, 10, 255], [12, 12, 12, 255], [14, 14, 14, 255]]
    block[0, 3] = [250, 250, 250, 255]                   # one bright outlier
    reduced = conform.to_grid(block, (1, 1))
    assert 10 <= int(reduced[0, 0, 0]) <= 14             # not the outlier


def test_the_flat_field_becomes_transparency():
    art = _sprite()
    generated = _as_a_model_would_return_it(art)
    out, report = conform.conform(generated, art)
    assert "flood" in report["background"] or "alpha" in report["background"]
    assert not image.alpha_mask(out)[0, 0]


def test_every_pixel_is_fully_opaque_or_fully_absent():
    """A 40%-opaque pixel is a pixel that will flicker under alpha testing."""
    art = _sprite()
    out, _report = conform.conform(_as_a_model_would_return_it(art), art)
    alpha = out[:, :, 3]
    assert set(np.unique(alpha)) <= {0, 255}


def test_nearest_picks_a_palette_colour_and_only_a_palette_colour():
    palette = np.array([[0, 0, 0, 255], [255, 255, 255, 255]], np.uint8)
    pixels = image.blank(1, 3)
    pixels[0] = [[30, 30, 30, 255], [200, 200, 200, 255], [128, 128, 128, 255]]
    out = conform.nearest(pixels, palette)
    assert list(out[0, 0][:3]) == [0, 0, 0]
    assert list(out[0, 1][:3]) == [255, 255, 255]
    for pixel in out[0]:
        assert list(pixel[:3]) in ([0, 0, 0], [255, 255, 255])


def test_a_recognisable_sprite_comes_back():
    """Not just legal colours -- most of the actual picture."""
    art = _sprite(12, 10)
    out, _report = conform.conform(_as_a_model_would_return_it(art), art)
    same = int((out == art).all(axis=2).sum())
    assert same / float(art.shape[0] * art.shape[1]) > 0.7


def test_an_image_already_on_the_grid_is_left_on_it():
    art = _sprite()
    out, report = conform.conform(art, art)
    assert report["invented"] == 0
    assert conform.conforms(out, art)
