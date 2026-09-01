"""The GIF is the review artefact. A still sheet cannot show timing."""

import os

from PIL import Image as PILImage

from spritepipe import image, motion, pack, preview, render


def clip_of(hero_cutout, hero_rig, name="walk"):
    animation = motion.get(name)
    frames = [render.render_pose(hero_cutout, pose, margin=10)
              for pose in animation.poses(hero_rig)]
    return pack.Clip(name, frames, animation.fps, animation.loop, anchor=(10, 10))


def test_a_gif_has_one_frame_per_clip_frame(hero_cutout, hero_rig, tmp_path):
    clip = clip_of(hero_cutout, hero_rig)
    path = str(tmp_path / "walk.gif")
    preview.write_gif(clip.frames, path, clip.fps, clip.loop)
    with PILImage.open(path) as handle:
        assert handle.n_frames == len(clip.frames)
        assert handle.is_animated


def test_a_gif_carries_the_clips_own_frame_rate(hero_cutout, hero_rig, tmp_path):
    clip = clip_of(hero_cutout, hero_rig, "run")
    path = str(tmp_path / "run.gif")
    preview.write_gif(clip.frames, path, clip.fps, clip.loop)
    with PILImage.open(path) as handle:
        assert abs(handle.info["duration"] - 1000.0 / clip.fps) <= 20


def test_a_gif_keeps_the_sprite_transparent(hero_cutout, hero_rig, tmp_path):
    """GIF has one transparent index, not an alpha channel. Index 255 is reserved."""
    clip = clip_of(hero_cutout, hero_rig)
    path = str(tmp_path / "walk.gif")
    preview.write_gif(clip.frames, path, clip.fps, clip.loop)
    with PILImage.open(path) as handle:
        assert handle.info.get("transparency") == 255


def test_a_gif_can_be_upscaled_for_looking_at(hero_cutout, hero_rig, tmp_path):
    clip = clip_of(hero_cutout, hero_rig)
    small = str(tmp_path / "a.gif")
    big = str(tmp_path / "b.gif")
    preview.write_gif(clip.frames, small, clip.fps, clip.loop, scale=1)
    preview.write_gif(clip.frames, big, clip.fps, clip.loop, scale=5)
    with PILImage.open(small) as a, PILImage.open(big) as b:
        assert b.size[0] == a.size[0] * 5


def test_a_contact_sheet_holds_a_row_per_clip(hero_cutout, hero_rig, tmp_path):
    clips = [clip_of(hero_cutout, hero_rig, name) for name in ("idle", "walk", "run")]
    path = preview.contact_sheet(clips, str(tmp_path / "contact.png"), scale=2)
    sheet = image.load(path)
    assert sheet.shape[0] > sheet.shape[1] / 4
    assert os.path.getsize(path) > 0


def test_the_contact_sheet_numbers_its_frames(hero_cutout, hero_rig, tmp_path):
    """So a reviewer can say "frame 5 is wrong" instead of "the third one"."""
    clips = [clip_of(hero_cutout, hero_rig)]
    path = preview.contact_sheet(clips, str(tmp_path / "contact.png"))
    sheet = image.load(path)
    tick = (sheet == [150, 150, 160, 255]).all(axis=2)
    assert tick.any()


def test_write_all_produces_a_gif_per_clip(hero_cutout, hero_rig, tmp_path):
    clips = [clip_of(hero_cutout, hero_rig, name) for name in ("idle", "walk")]
    written = preview.write_all(clips, str(tmp_path / "preview"))
    assert set(written["gifs"]) == {"idle", "walk"}
    assert os.path.exists(written["contact_sheet"])


def test_an_empty_clip_writes_nothing_rather_than_crashing(tmp_path):
    assert preview.write_gif([], str(tmp_path / "empty.gif"), 10, True) is None
