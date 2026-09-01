"""One box per clip, and an anchor that does not wander."""


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
