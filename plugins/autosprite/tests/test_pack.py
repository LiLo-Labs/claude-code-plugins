"""Laying frames out without letting them touch, and without moving the anchor."""

import numpy as np
import pytest

from spritepipe import image, pack


def frames(count, width, height, colour):
    out = []
    for index in range(count):
        frame = image.blank(height, width)
        frame[index % height:, :] = colour
        frame[0, 0] = colour
        out.append(frame)
    return out


@pytest.fixture
def clips():
    return [
        pack.Clip("idle", frames(4, 10, 14, [200, 40, 40, 255]), 6, True, anchor=(5, 14)),
        pack.Clip("walk", frames(8, 12, 14, [40, 90, 200, 255]), 10, True, anchor=(6, 14)),
        # A jump leaves the ground: its anchor is below its art.
        pack.Clip("jump", frames(6, 12, 18, [60, 180, 90, 255]), 12, False, anchor=(6, 22)),
    ]


def test_a_grid_gives_every_frame_the_same_cell(clips):
    sheet = pack.pack(clips, layout="grid")
    sizes = {(p.width, p.height) for p in sheet.placements}
    assert len(sizes) == 1
    assert sheet.cell == sizes.pop()


def test_a_grid_aligns_cells_by_anchor_so_a_jump_survives(clips):
    """Centring the apex frame in its cell would put the feet back on the floor."""
    sheet = pack.pack(clips, layout="grid", padding=0, extrude=0)
    anchors = {tuple(p.anchor) for p in sheet.placements}
    assert len(anchors) == 1, "every cell must place the anchor at the same pixel"

    jump = [p for p in sheet.placements if p.clip == "jump"][0]
    idle = [p for p in sheet.placements if p.clip == "idle"][0]
    jump_box = image.content_box(image.crop(sheet.pixels, (jump.x, jump.y,
                                                           jump.x + jump.width,
                                                           jump.y + jump.height)))
    idle_box = image.content_box(image.crop(sheet.pixels, (idle.x, idle.y,
                                                           idle.x + idle.width,
                                                           idle.y + idle.height)))
    assert jump_box[3] < idle_box[3], "the jumping character must sit higher in its cell"


def test_every_frame_lands_in_the_sheet(clips):
    for layout in ("grid", "packed"):
        sheet = pack.pack(clips, layout=layout)
        height, width = sheet.pixels.shape[:2]
        assert len(sheet.placements) == sum(len(c.frames) for c in clips)
        for placement in sheet.placements:
            assert 0 <= placement.x and placement.x + placement.width <= width
            assert 0 <= placement.y and placement.y + placement.height <= height


def test_packed_rects_never_overlap(clips):
    sheet = pack.pack(clips, layout="packed", padding=1, extrude=1)
    occupied = np.zeros(sheet.pixels.shape[:2], dtype=bool)
    for placement in sheet.placements:
        window = occupied[placement.y:placement.y + placement.height,
                          placement.x:placement.x + placement.width]
        assert not window.any(), "%s overlaps an earlier frame" % placement.name
        window[:] = True


def test_packed_is_smaller_than_grid_when_frames_differ(clips):
    grid = pack.pack(clips, layout="grid")
    packed = pack.pack(clips, layout="packed")
    assert packed.size[0] * packed.size[1] < grid.size[0] * grid.size[1]


def test_extrude_puts_the_frames_own_colour_in_the_gutter(clips):
    """Padding alone leaves a transparent halo under bilinear filtering."""
    sheet = pack.pack(clips, layout="grid", padding=0, extrude=2)
    placement = sheet.placements[0]
    inside = sheet.pixels[placement.y, placement.x]
    just_outside = sheet.pixels[placement.y - 1, placement.x]
    assert tuple(just_outside) == tuple(inside)


def test_no_extrude_leaves_the_gutter_empty(clips):
    sheet = pack.pack(clips, layout="grid", padding=2, extrude=0)
    placement = sheet.placements[0]
    assert sheet.pixels[placement.y - 1, placement.x][3] == 0


def test_power_of_two_grows_the_texture_without_moving_a_frame(clips):
    plain = pack.pack(clips, layout="packed", power_of_two=False)
    padded = pack.pack(clips, layout="packed", power_of_two=True)
    for value in padded.size:
        assert value & (value - 1) == 0
    assert [p.rect for p in plain.placements] == [p.rect for p in padded.placements]


def test_scaling_upscales_the_art_and_the_anchor_together(clips):
    sheet = pack.pack(clips, layout="grid", scale=3, padding=0, extrude=0)
    plain = pack.pack(clips, layout="grid", scale=1, padding=0, extrude=0)
    assert sheet.cell == (plain.cell[0] * 3, plain.cell[1] * 3)
    assert sheet.placements[0].anchor == (plain.placements[0].anchor[0] * 3,
                                          plain.placements[0].anchor[1] * 3)


def test_scaling_invents_no_colour(clips):
    plain = pack.pack(clips, layout="grid", scale=1)
    scaled = pack.pack(clips, layout="grid", scale=4)
    assert ({tuple(c) for c in image.unique_colors(scaled.pixels)}
            <= {tuple(c) for c in image.unique_colors(plain.pixels)})


def test_a_grid_too_wide_to_pack_says_what_to_do(clips):
    with pytest.raises(ValueError) as error:
        pack.pack(clips, layout="grid", max_width=40)
    assert "--layout packed" in str(error.value)


def test_packing_nothing_is_refused():
    with pytest.raises(ValueError):
        pack.pack([])


def test_a_clip_with_a_direction_carries_it_into_the_frame_names():
    clip = pack.Clip("walk", frames(2, 4, 4, [1, 2, 3, 255]), direction="SE")
    assert clip.key == "walk_SE"
    assert clip.frame_name(1) == "walk_SE_001"
