"""One box per clip, and an anchor that does not wander."""

import pytest

from spritepipe import image, stabilize


def moving(count=4, size=20, colour=(200, 40, 40, 255)):
    frames = []
    for index in range(count):
        frame = image.blank(size, size)
        frame[5 + index:12 + index, 4 + index:9 + index] = colour
        frames.append(frame)
    return frames


def test_the_union_box_holds_every_frames_content():
    frames = moving()
    box = stabilize.union_box(frames)
    for frame in frames:
        content = image.content_box(frame)
        assert box[0] <= content[0] and box[1] <= content[1]
        assert box[2] >= content[2] and box[3] >= content[3]


def test_every_frame_comes_out_the_same_size():
    cropped, box, anchor, report = stabilize.stabilise(moving(), (10, 12))
    assert len({frame.shape for frame in cropped}) == 1
    assert report["size"] == [box[2] - box[0], box[3] - box[1]]


def test_the_anchor_moves_with_the_crop_so_it_still_points_at_the_same_pixel():
    frames = moving()
    cropped, box, anchor, _ = stabilize.stabilise(frames, (10, 12))
    assert anchor == (10 - box[0], 12 - box[1])


def test_padding_widens_the_box_without_losing_content():
    plain, _, _, _ = stabilize.stabilise(moving(), (10, 12))
    padded, _, _, _ = stabilize.stabilise(moving(), (10, 12), padding=2)
    assert padded[0].shape[0] > plain[0].shape[0]


def test_a_hold_is_reported_not_removed():
    """`attack` holds its contact frame on purpose. Reporting is the right move."""
    frame = image.blank(8, 8)
    frame[2:6, 2:6] = [1, 2, 3, 255]
    runs = stabilize.duplicate_runs([frame, frame.copy(), frame.copy()])
    assert runs == [[0, 3]]


def test_distinct_frames_report_no_holds():
    assert stabilize.duplicate_runs(moving()) == []


def test_an_all_empty_clip_is_reported_rather_than_crashing():
    frames = [image.blank(8, 8) for _ in range(3)]
    cropped, box, anchor, report = stabilize.stabilise(frames, (4, 8))
    assert box is None
    assert report["empty"] == [0, 1, 2]


def test_anchor_drift_is_measured_not_corrected():
    """A jump SHOULD drift; correcting it would delete the jump."""
    drift = stabilize.anchor_drift(moving(), (10, 12))
    assert len(drift) == 4
    assert drift[0] != drift[-1]


# -- a fixed frame size ---------------------------------------------------

def test_every_frame_lands_in_the_cell_with_the_anchor_in_one_place():
    frames = [image.blank(6, 4), image.blank(5, 7)]
    frames[0][:, :] = (10, 20, 30, 255)
    frames[1][:, :] = (40, 50, 60, 255)
    out, anchor = stabilize.fit_to_cell(frames, (2, 6), 16)
    assert anchor == (8, 16)
    assert all(frame.shape[:2] == (16, 16) for frame in out)
    # the first frame's bottom-left corner sits where the anchor put it
    assert tuple(out[0][15, 6][:3]) == (10, 20, 30)


def test_the_character_still_stands_on_the_cell_floor():
    frame = image.blank(4, 4)
    frame[:, :] = (200, 100, 50, 255)
    out, _ = stabilize.fit_to_cell([frame], (2, 4), 12)
    rows = image.alpha_mask(out[0]).nonzero()[0]
    assert int(rows.max()) == 11


def test_art_too_big_for_the_cell_is_refused_not_cropped():
    frame = image.blank(20, 20)
    frame[:, :] = (1, 2, 3, 255)
    with pytest.raises(ValueError) as caught:
        stabilize.fit_to_cell([frame], (10, 20), 16)
    assert "--frame-size" in str(caught.value)


def test_nothing_is_lost_when_it_does_fit():
    frame = image.blank(5, 5)
    frame[2, 2] = (9, 9, 9, 255)
    out, _ = stabilize.fit_to_cell([frame], (2, 5), 20)
    assert int(image.alpha_mask(out[0]).sum()) == 1


# -- repeats that are not adjacent ----------------------------------------

def _solid(colour):
    frame = image.blank(4, 4)
    frame[:, :] = colour
    return frame


def test_distinct_frames_finds_a_repeat_that_is_not_adjacent():
    """The repeat that matters most is not adjacent: a swing symmetric in time
    makes frame k and frame N-k the same picture, and `duplicate_runs` walks
    straight past it."""
    frames = [_solid((1, 1, 1, 255)), _solid((2, 2, 2, 255)),
              _solid((3, 3, 3, 255)), _solid((2, 2, 2, 255))]
    assert stabilize.duplicate_runs(frames) == []
    assert stabilize.distinct_frames(frames) == 3


def test_a_one_shot_that_ends_where_it_started_is_not_repeating_itself():
    frames = [_solid((1, 1, 1, 255)), _solid((2, 2, 2, 255)), _solid((1, 1, 1, 255))]
    assert stabilize.distinct_frames(frames, loop=False) == 2
    assert stabilize.distinct_frames(frames, loop=True) == 2


def test_every_frame_different_counts_them_all():
    frames = [_solid((index, index, index, 255)) for index in range(1, 6)]
    assert stabilize.distinct_frames(frames) == 5
