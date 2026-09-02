"""The generative backend, tested without a network or a key.

Everything here is the part of `generate` that runs on this side of the API: how
a returned sheet is cut into frames, how a token is found, and -- the one that
matters -- that a model's output is forced onto the source's palette before
anyone downstream sees it. The HTTP call itself is one function and is stubbed.
"""

import base64
import io
import os

import numpy as np
import pytest

from spritepipe import conform, generate, image, ingest


def source():
    """A tiny sprite with a deliberately small palette to conform against."""
    art = image.blank(16, 12)
    art[2:14, 3:9] = (40, 90, 200, 255)
    art[4:6, 4:8] = (240, 220, 60, 255)
    return art


# -- cutting a returned sheet ---------------------------------------------

def test_a_horizontal_strip_is_cut_along_its_length():
    sheet = image.blank(16, 64)
    for i in range(4):
        sheet[:, i * 16:(i + 1) * 16] = (i * 10, 0, 0, 255)
    frames = generate.split_sheet(sheet, 4)
    assert len(frames) == 4
    assert [f.shape[:2] for f in frames] == [(16, 16)] * 4
    assert [int(f[0, 0, 0]) for f in frames] == [0, 10, 20, 30]


def test_a_vertical_strip_is_cut_along_its_length():
    """Not every service returns a row, and guessing wrong quarters the
    character instead of splitting the animation."""
    sheet = image.blank(64, 16)
    for i in range(4):
        sheet[i * 16:(i + 1) * 16, :] = (i * 10, 0, 0, 255)
    frames = generate.split_sheet(sheet, 4)
    assert [f.shape[:2] for f in frames] == [(16, 16)] * 4
    assert [int(f[0, 0, 0]) for f in frames] == [0, 10, 20, 30]


def test_one_frame_is_the_sheet_itself():
    sheet = image.blank(8, 8)
    assert len(generate.split_sheet(sheet, 1)) == 1


def test_a_sheet_that_divides_neither_way_still_returns_that_many_frames():
    """A ragged sheet is better cut approximately than not at all -- the caller
    has already been told how many frames it asked for."""
    sheet = image.blank(10, 33)
    assert len(generate.split_sheet(sheet, 4)) == 4


# -- the palette guarantee, over a model's output --------------------------

def test_a_models_invented_colours_never_reach_the_caller():
    """The whole reason this module is more than an API wrapper. A model
    returns whatever it likes; what comes back here is made of the source's
    own colours, because `conform` assigns every pixel one."""
    art = source()
    invented = image.blank(16, 12)
    invented[:, :] = (17, 200, 130, 255)          # a colour the source lacks
    invented[6:10, 4:8] = (255, 0, 255, 255)      # and another

    class Stub:
        def animate(self, reference, prompt, **kwargs):
            sheet = image.blank(16, 24)
            image.paste(sheet, invented, 0, 0)
            image.paste(sheet, invented, 12, 0)
            return sheet, {"model": "stub"}

    frames, report = generate.frames(Stub(), art, "walking", 2)
    assert len(frames) == 2
    allowed = {tuple(int(v) for v in c) for c in image.unique_colors(art)}
    for frame in frames:
        for colour in image.unique_colors(frame):
            assert tuple(int(v) for v in colour) in allowed
        assert conform.conforms(frame, art)
    assert report["frames"] == 2
    assert len(report["conform"]) == 2


# -- credentials -----------------------------------------------------------

def test_a_token_is_read_from_the_environment_first(monkeypatch):
    monkeypatch.setenv("SPRITE_TEST_TOKEN", "  from-env  ")
    assert generate.token("SPRITE_TEST_TOKEN", "/nonexistent") == "from-env"


def test_a_token_falls_back_to_a_file_outside_the_repository(tmp_path, monkeypatch):
    monkeypatch.delenv("SPRITE_TEST_TOKEN", raising=False)
    path = tmp_path / "keys.env"
    path.write_text("OTHER=x\nSPRITE_TEST_TOKEN=from-file\n")
    assert generate.token("SPRITE_TEST_TOKEN", str(path)) == "from-file"


def test_a_missing_token_is_unavailable_rather_than_a_crash(monkeypatch):
    """No key must never break a build. The cutout path does not need one."""
    monkeypatch.delenv("SPRITE_TEST_TOKEN", raising=False)
    with pytest.raises(generate.Unavailable):
        generate.token("SPRITE_TEST_TOKEN", "/nonexistent")


def test_a_data_uri_round_trips_the_pixels_exactly():
    """Lossy encoding here would hand the model a different sprite than the one
    the user uploaded, and every difference downstream would be unexplainable."""
    from PIL import Image as PILImage
    art = source()
    uri = generate.data_uri(art)
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    back = np.array(PILImage.open(io.BytesIO(raw)).convert("RGBA"))
    assert image.equal(back, art)
