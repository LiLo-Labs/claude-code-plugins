"""A walk cycle is a table of numbers, and these are the numbers."""

import json

import pytest

from spritepipe import motion, rig as R


@pytest.fixture
def humanoid_rig():
    return R.Rig((10, 20), [
        R.Part("torso", "torso", (2, 5, 8, 13), None, (5, 13), 1),
        R.Part("head", "head", (3, 0, 7, 6), "torso", (5, 5), 2),
        R.Part("arm_near", "arm_near", (7, 6, 9, 12), "torso", (8, 6), 3),
        R.Part("arm_far", "arm_far", (1, 6, 3, 12), "torso", (2, 6), 0),
        R.Part("leg_near", "leg_near", (5, 13, 7, 20), "torso", (6, 13), 2),
        R.Part("leg_far", "leg_far", (3, 13, 5, 20), "torso", (4, 13), 0),
    ])


def test_every_built_in_animation_validates():
    for name, animation in motion.LIBRARY.items():
        assert motion.validate_animation(animation.to_dict()) == [], name


def test_a_loop_samples_before_its_own_end_so_no_frame_repeats():
    """i/(frames-1) puts a duplicate frame in every cycle. That is the stutter."""
    walk = motion.get("walk")
    times = walk.times()
    assert times[0] == 0.0
    assert times[-1] < 1.0
    assert len(set(times)) == walk.frames


def test_a_one_shot_reaches_its_final_pose():
    jump = motion.get("jump")
    assert jump.times()[-1] == 1.0


def test_walk_legs_are_in_counter_phase():
    walk = motion.get("walk")
    near = [walk.tracks["leg_near"].sample(t, True).angle for t in walk.times()]
    far = [walk.tracks["leg_far"].sample(t, True).angle for t in walk.times()]
    for a, b in zip(near, far):
        assert abs(a + b) < 1e-6, "the legs must mirror, or the character skips"


def test_walk_arms_oppose_the_legs():
    walk = motion.get("walk")
    legs = walk.tracks["leg_near"].sample(0.0, True).angle
    arms = walk.tracks["arm_near"].sample(0.0, True).angle
    assert legs * arms < 0


def test_walk_bobs_twice_per_cycle():
    walk = motion.get("walk")
    bob = [walk.root.sample(t, True).dy for t in walk.times()]
    troughs = sum(1 for index in range(len(bob))
                  if bob[index] < bob[index - 1] and bob[index] <= bob[(index + 1) % len(bob)])
    assert troughs == 2


def test_a_looping_track_wraps_rather_than_holding():
    """Without the wrap the frame before the loop point freezes."""
    track = motion.Track([{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 10.0}])
    assert 0.0 < track.sample(0.75, loop=True).angle < 10.0


def test_a_one_shot_track_clamps_at_both_ends():
    track = motion.Track([{"t": 0.2, "angle": 5.0}, {"t": 0.8, "angle": 9.0}])
    assert track.sample(0.0, loop=False).angle == 5.0
    assert track.sample(1.0, loop=False).angle == 9.0


def test_hold_easing_steps_instead_of_sliding():
    track = motion.Track([{"t": 0.0, "angle": 0.0},
                          {"t": 1.0, "angle": 90.0, "easing": "hold"}])
    assert track.sample(0.99, loop=False).angle == 0.0


def test_scaling_moves_translations_and_leaves_angles_alone():
    """A bob of 1px on a 32px sprite is 3px on a 96px one; the angle is the same."""
    walk = motion.get("walk")
    big = walk.scaled(3.0)
    assert big.root.sample(0.25, True).dy == pytest.approx(
        walk.root.sample(0.25, True).dy * 3.0)
    assert big.tracks["leg_near"].sample(0.0, True).angle == pytest.approx(
        walk.tracks["leg_near"].sample(0.0, True).angle)


def test_scale_motion_uses_the_character_height():
    scaled = motion.scale_motion([motion.get("walk")], 64.0, authored_height=32.0)
    assert scaled[0].root.sample(0.25, True).dy == pytest.approx(-2.0)


def test_a_track_resolves_onto_every_part_with_that_role(humanoid_rig):
    pose = motion.get("walk").pose_at(humanoid_rig, 0.0)
    assert pose.get("leg_near").angle != 0.0
    assert pose.get("leg_far").angle != 0.0
    assert pose.get("leg_near").angle == -pose.get("leg_far").angle


def test_a_rig_without_a_role_simply_ignores_that_track():
    lone = R.Rig((10, 10), [R.Part("body", "body", (0, 0, 10, 10), None, (5, 10))])
    pose = motion.get("walk").pose_at(lone, 0.25)
    assert pose.parts == {} or all(p.angle == 0 for p in pose.parts.values())


def test_the_root_track_moves_the_root_part(humanoid_rig):
    """`die` is one line of keyframes because the root carries the whole body."""
    pose = motion.get("die").pose_at(humanoid_rig, 1.0)
    assert pose.get("torso").angle < -60


def test_presets_expand_and_deduplicate():
    names = [a.name for a in motion.resolve(["basic", "walk", "jump"])]
    assert names == ["idle", "walk", "jump"]


def test_an_unknown_animation_lists_what_exists():
    with pytest.raises(KeyError) as error:
        motion.get("moonwalk")
    assert "walk" in str(error.value)


# -- validating what a model or a user writes ------------------------------

def test_a_missing_frame_count_is_caught():
    assert any("frames must be" in p for p in
               motion.validate_animation({"name": "x", "tracks": {"torso": [{"t": 0}]}}))


def test_an_absurd_frame_count_is_caught():
    assert any("64 frames" in p for p in motion.validate_animation(
        {"name": "x", "frames": 500, "tracks": {"torso": [{"t": 0}]}}))


def test_an_animation_with_no_tracks_is_caught():
    assert any("identical" in p for p in
               motion.validate_animation({"name": "x", "frames": 4}))


def test_a_track_on_an_unknown_role_is_caught():
    assert any("not a rig role" in p for p in motion.validate_animation(
        {"name": "x", "frames": 4, "tracks": {"elbow": [{"t": 0, "angle": 5}]}}))


def test_a_keyframe_outside_zero_to_one_is_caught():
    assert any("outside 0..1" in p for p in motion.validate_animation(
        {"name": "x", "frames": 4, "tracks": {"torso": [{"t": 3, "angle": 5}]}}))


def test_an_unknown_channel_is_caught():
    assert any("unknown channels" in p for p in motion.validate_animation(
        {"name": "x", "frames": 4, "tracks": {"torso": [{"t": 0, "twist": 5}]}}))


def test_a_custom_animation_round_trips_through_disk(tmp_path):
    spec = {"name": "taunt", "frames": 5, "fps": 8, "loop": False,
            "tracks": {"arm_near": [{"t": 0, "angle": 0}, {"t": 1, "angle": -90}]}}
    path = str(tmp_path / "custom.json")
    open(path, "w").write(json.dumps(spec))
    loaded = motion.load_custom(path)
    assert len(loaded) == 1 and loaded[0].name == "taunt"


def test_a_bad_custom_animation_is_refused_by_filename(tmp_path):
    path = str(tmp_path / "bad.json")
    open(path, "w").write(json.dumps({"name": "x", "frames": 0}))
    with pytest.raises(ValueError) as error:
        motion.load_custom(path)
    assert "bad.json" in str(error.value)


def test_a_list_of_animations_loads(tmp_path):
    path = str(tmp_path / "many.json")
    open(path, "w").write(json.dumps([
        {"name": "a", "frames": 2, "tracks": {"head": [{"t": 0, "angle": 1}]}},
        {"name": "b", "frames": 2, "tracks": {"head": [{"t": 0, "angle": 2}]}}]))
    assert [a.name for a in motion.load_custom(path)] == ["a", "b"]
