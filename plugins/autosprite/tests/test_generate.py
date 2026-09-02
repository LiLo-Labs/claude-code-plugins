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


# -- waiting for a slow job ------------------------------------------------

def test_a_finished_prediction_is_returned_as_is():
    answer = {"status": "succeeded", "output": ["x"]}
    assert generate.settled(answer, "tok") is answer


def test_a_starting_prediction_is_polled_until_it_finishes(monkeypatch):
    """`Prefer: wait` gives up after about a minute and returns whatever the job
    is doing. For a video that is `starting`, and reading it as a failure
    reports a running job dead -- which is exactly what happened."""
    seen = []

    def fake_get(url, api_token):
        seen.append(url)
        return ({"status": "processing"} if len(seen) < 3
                else {"status": "succeeded", "output": ["done"]})

    monkeypatch.setattr(generate, "_get", fake_get)
    monkeypatch.setattr(generate.time, "sleep", lambda _s: None)
    answer = generate.settled(
        {"status": "starting", "urls": {"get": "https://x/predictions/1"}}, "tok")
    assert answer["status"] == "succeeded"
    assert answer["output"] == ["done"]
    assert len(seen) == 3


def test_a_prediction_with_no_poll_url_is_handed_back_rather_than_hanging():
    answer = {"status": "starting"}
    assert generate.settled(answer, "tok") is answer


def test_a_job_that_never_finishes_is_unavailable(monkeypatch):
    monkeypatch.setattr(generate, "_get", lambda u, t: {"status": "processing"})
    monkeypatch.setattr(generate.time, "sleep", lambda _s: None)
    with pytest.raises(generate.Unavailable):
        generate.settled({"status": "starting", "urls": {"get": "https://x/1"}},
                         "tok", patience=0.01, every=0)


# -- video, and the window in which a character is still itself -------------

def test_frames_are_sampled_across_the_anchored_window_not_the_whole_video():
    video = [np.full((4, 4, 3), i, np.uint8) for i in range(100)]
    picked = generate.sampled(video, 4, until=18)
    assert len(picked) == 4
    assert [int(f[0, 0, 0]) for f in picked] == [0, 6, 12, 18]


def test_sampling_never_runs_past_a_short_video():
    video = [np.zeros((4, 4, 3), np.uint8) for _ in range(5)]
    assert len(generate.sampled(video, 8, until=18)) == 8


def test_a_single_frame_video_still_yields_a_frame():
    assert len(generate.sampled([np.zeros((4, 4, 3), np.uint8)], 4)) == 1


def test_drift_is_zero_against_the_source_itself():
    """The identity metric. Zero means the output IS the user's character, which
    is the one thing `footprint` cannot tell you about a generated frame."""
    art = source()
    assert generate.drift(art, art) == 0


def test_drift_counts_a_changed_silhouette():
    art = source()
    changed = art.copy()
    changed[10:12, 4:8] = 0            # four pixels removed from the silhouette
    assert generate.drift(changed, art) == 8


def test_a_video_frame_becomes_a_sprite_on_the_sources_palette():
    art = source()
    frame = np.full((64, 64, 3), 255, np.uint8)     # white field
    frame[8:56, 20:44] = (10, 200, 90)              # a colour the source lacks
    sprite = generate.to_sprite(frame, art)
    assert sprite is not None
    assert sprite.shape[:2] == art.shape[:2]
    assert conform.conforms(sprite, art)


def test_a_uniform_frame_is_kept_rather_than_silently_emptied():
    """Written the other way round first, and the code was right.

    `ingest.remove_background` refuses to treat a UNIFORM picture as background,
    because removing the dominant colour from an image that is only that colour
    deletes the whole frame. So a blank render comes back as a blank-coloured
    sprite rather than as None -- visible in a sheet, which is what you want,
    instead of a silent hole.
    """
    art = source()
    sprite = generate.to_sprite(np.full((32, 32, 3), 255, np.uint8), art)
    assert sprite is not None
    assert conform.conforms(sprite, art)


def test_a_frame_whose_content_all_washes_out_yields_nothing(monkeypatch):
    """The guard for the other case: if a frame's content box comes back empty,
    cropping to it makes a fully transparent sprite that would enter a sheet as
    a missing frame."""
    art = source()
    monkeypatch.setattr(generate.img, "content_box", lambda _p: (5, 5, 5, 5))
    assert generate.to_sprite(np.full((32, 32, 3), 200, np.uint8), art) is None


# -- measuring a video the same way in every frame -------------------------

def test_calibration_reads_the_scale_off_the_first_frame():
    art = source()
    frame = np.full((64, 64, 3), 255, np.uint8)
    frame[16:48, 24:40] = (40, 90, 200)          # content 32 rows tall
    scale, floor = generate.calibrate(frame, art)
    inside = image.content_box(art)
    assert scale == pytest.approx((inside[3] - inside[1]) / 32.0)
    assert floor == inside[3]


def test_a_raised_arm_does_not_shrink_the_body():
    """The bug this fixes, stated as a test. Normalising each frame against its
    OWN height means a character raising a sword gets taller content, so the
    body is scaled down to compensate -- and the fitted attack came back
    squashed, with the rig contorting to explain a shortening nobody drew."""
    art = source()
    plain = np.full((64, 64, 3), 255, np.uint8)
    plain[16:48, 24:40] = (40, 90, 200)
    raised = plain.copy()
    raised[4:16, 30:34] = (40, 90, 200)          # a sword above the head

    scale, floor = generate.calibrate(plain, art)
    steady = [generate.to_sprite(f, art, scale=scale, floor=floor)
              for f in (plain, raised)]
    drifting = [generate.to_sprite(f, art) for f in (plain, raised)]

    def body_rows(sprite):
        mask = image.alpha_mask(sprite)
        rows = np.nonzero(mask.any(axis=1))[0]
        return int(rows.max() - rows.min()) if rows.size else 0

    # Calibrated: the raised arm makes the content TALLER, as it should.
    assert body_rows(steady[1]) > body_rows(steady[0])
    # Uncalibrated: both come back the same height, because the body was shrunk
    # by exactly as much as the arm added.
    assert body_rows(drifting[1]) == body_rows(drifting[0])


def test_frames_are_aligned_by_the_floor_not_by_the_box():
    """A character stands on the ground. Its feet must not wander when the top
    of the silhouette moves."""
    art = source()
    plain = np.full((64, 64, 3), 255, np.uint8)
    plain[16:48, 24:40] = (40, 90, 200)
    raised = plain.copy()
    raised[4:16, 30:34] = (40, 90, 200)
    scale, floor = generate.calibrate(plain, art)
    feet = []
    for frame in (plain, raised):
        mask = image.alpha_mask(generate.to_sprite(frame, art, scale=scale,
                                                   floor=floor))
        feet.append(int(np.nonzero(mask.any(axis=1))[0].max()))
    assert feet[0] == feet[1]


def test_a_frame_that_reduces_to_nothing_is_dropped():
    """The box guard is not enough on a real video.

    Once the background removal stops working -- which is the moment the model
    changes the backdrop, part-way through most clips -- the content box becomes
    the whole frame, so the crop is scaled from hundreds of pixels of background
    and the paste offset goes negative. The sprite comes back holding nothing.
    It is not `None`, so it passes every downstream check and becomes a fit
    target no pose can ever match, and `fit` then reports agreement 0.00 on it,
    which reads as a rig that cannot reach the pose.
    """
    art = source()
    # A frame the background removal only PARTLY cleared: the character down in
    # one corner and a single stray survivor far away, which balloons the content
    # box to most of the frame. Scaled by a factor calibrated on a frame that
    # cleared properly, the crop is then mostly transparent and the window that
    # lands on the sprite's own grid catches none of the character.
    frame = np.zeros((64, 64, 3), np.uint8)
    frame[40:52, 4:12] = (200, 30, 30)
    frame[1, 60] = (30, 200, 30)
    assert generate.to_sprite(frame, art, scale=6.0, floor=14) is None
    # The same frame measured against itself still comes back: the guard rejects
    # an empty result, not a difficult frame.
    assert generate.to_sprite(frame, art) is not None
