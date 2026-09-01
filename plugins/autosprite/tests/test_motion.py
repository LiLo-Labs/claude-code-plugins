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


# -- a clip seen from the front -------------------------------------------

def _peak(track, channel):
    values = [float(key.get(channel, 0.0)) for key in track.keys]
    return max(values) - min(values)


def test_fronted_damps_the_swing_and_pays_it_back_as_travel():
    walk = motion.get("walk")
    front = walk.fronted()
    for role in ("leg_near", "leg_far", "arm_near", "arm_far"):
        assert _peak(front.tracks[role], "angle") < _peak(walk.tracks[role], "angle")
    # legs lift, arms reach sideways
    assert _peak(front.tracks["leg_near"], "dy") > 0
    assert _peak(front.tracks["arm_near"], "dx") > 0
    assert _peak(front.tracks["leg_near"], "dx") == 0


def test_fronted_keeps_the_pair_in_counter_phase():
    """Which side of the body a limb is on is never known here, so the sign of
    the original swing has to carry the phase through."""
    front = motion.get("walk").fronted()
    near = front.tracks["leg_near"].sample(0.0, True)
    far = front.tracks["leg_far"].sample(0.0, True)
    assert near.dy * far.dy < 0


def test_fronted_leaves_the_body_alone():
    walk = motion.get("walk")
    front = walk.fronted()
    assert front.tracks["torso"].to_list() == walk.tracks["torso"].to_list()
    assert front.root.to_list() == walk.root.to_list()
    assert front.frames == walk.frames and front.fps == walk.fps


def test_fronted_does_not_mutate_the_library():
    walk = motion.get("walk")
    before = walk.tracks["leg_near"].to_list()
    walk.fronted()
    assert motion.get("walk").tracks["leg_near"].to_list() == before


# -- a translation that would round away ----------------------------------

def test_a_bob_scaled_below_a_pixel_is_floored_not_lost():
    """A 16px sprite scales the walk's 1px bob to half a pixel, which cannot be
    drawn, so the character slides instead of walking."""
    small = motion.get("walk").scaled(0.5)
    assert _peak(small.root, "dy") == pytest.approx(0.5)
    assert _peak(small.floored_travel(1.0).root, "dy") == pytest.approx(1.0)


def test_a_travel_that_already_reads_is_left_alone():
    big = motion.get("walk").scaled(3.0)
    before = big.root.to_list()
    assert big.floored_travel(1.0).root.to_list() == before


def test_a_channel_that_was_never_authored_is_not_invented():
    still = motion.Animation("still", frames=2, root=[{"t": 0.0}, {"t": 1.0}])
    assert _peak(still.floored_travel(1.0).root, "dy") == 0.0


def test_scale_motion_floors_the_travel_for_a_small_character():
    scaled = motion.scale_motion([motion.get("walk")], 16)[0]
    assert _peak(scaled.root, "dy") >= 1.0


# -- a different number of frames -----------------------------------------

def test_resampling_keeps_the_duration_and_changes_the_smoothness():
    walk = motion.get("walk")
    denser = walk.resampled(16)
    assert denser.frames == 16
    assert denser.fps == pytest.approx(walk.fps * 2)
    assert denser.frames / denser.fps == pytest.approx(walk.frames / walk.fps)


def test_resampling_samples_the_same_curve():
    """Not an interpolation of finished pictures: every track is a continuous
    curve, so more frames is a finer sampling of the identical movement."""
    walk = motion.get("walk")
    denser = walk.resampled(16)
    for t in (0.0, 0.125, 0.375, 0.5, 0.875):
        before = walk.tracks["leg_near"].sample(t, True)
        after = denser.tracks["leg_near"].sample(t, True)
        assert after.angle == pytest.approx(before.angle)


def test_resampling_to_the_same_count_is_free():
    walk = motion.get("walk")
    assert walk.resampled(walk.frames) is walk


def test_a_clip_cannot_be_resampled_below_two_frames():
    assert motion.get("walk").resampled(1).frames == 2


def test_resampling_does_not_mutate_the_library():
    before = motion.get("walk").frames
    motion.get("walk").resampled(30)
    assert motion.get("walk").frames == before


# -- a cycle, not a pendulum ----------------------------------------------

def _mirrors_itself(animation, rig):
    """Does pose(t) equal pose(1-t)? That is what makes a swing a pendulum."""
    for t in (0.125, 0.25, 0.375):
        here, there = animation.pose_at(rig, t), animation.pose_at(rig, 1.0 - t)
        for name in set(here.parts) | set(there.parts):
            a, b = here.get(name), there.get(name)
            if (round(a.angle, 3), round(a.sy, 3)) != (round(b.angle, 3), round(b.sy, 3)):
                return False
    return True


def test_the_walk_does_not_retrace_itself(hero_rig):
    """A swing with one key at each end and one in the middle is symmetric in
    time, so frame k and frame N-k are the same picture -- eight frames, five
    images, a character rocking instead of walking. The knee is what breaks it:
    at each passing pose one leg is planted and straight and the other lifted
    and bent, and which is which swaps between the halves."""
    assert not _mirrors_itself(motion.get("walk"), hero_rig)


def test_the_two_passing_poses_differ_in_which_knee_is_bent(hero_rig):
    quarter = motion.get("walk").pose_at(hero_rig, 0.25)
    three_quarter = motion.get("walk").pose_at(hero_rig, 0.75)
    assert quarter.get("leg_far").sy < quarter.get("leg_near").sy
    assert three_quarter.get("leg_near").sy < three_quarter.get("leg_far").sy


def test_no_locomotion_cycle_retraces_itself(hero_rig):
    """Only locomotion. A breathing idle SHOULD retrace itself -- in and out is
    what breathing is -- and its 1px motion is covered by the build's own
    "only N different pictures" warning instead."""
    for name in ("walk", "run"):
        assert not _mirrors_itself(motion.get(name), hero_rig), name


# -- the wider library ----------------------------------------------------

NEW = ("crouch", "land", "dash", "climb", "block", "cast", "throw", "sleep")


def test_every_new_clip_is_in_the_library_and_says_what_it_is():
    for name in NEW:
        animation = motion.get(name)
        assert animation.note, name
        assert 2 <= animation.frames <= 64, name


def test_the_everything_preset_covers_the_whole_library():
    assert set(motion.PRESET_SETS["everything"]) == set(motion.LIBRARY)


def test_the_new_clips_all_validate():
    for name in NEW:
        assert motion.validate_animation(motion.get(name).to_dict()) == [], name


def test_land_squashes_hardest_on_the_impact_frame(hero_rig):
    """The impact frame is the whole animation. If the deepest squash is not
    there, what the clip reads as is a character sinking rather than landing."""
    land = motion.get("land")
    depths = [min(land.pose_at(hero_rig, t).get("leg_near").sy,
                  land.pose_at(hero_rig, t).get("leg_far").sy)
              for t in land.times()]
    assert depths.index(min(depths)) == 1
    assert min(depths) < 0.7


def test_sleep_puts_the_character_down_rather_than_slouching(hero_rig):
    """A slumped upright figure reads as standing still. Only the root taking
    the whole character over reads as lying down."""
    root = motion.get("sleep").pose_at(hero_rig, 0.0).get(hero_rig.root.name)
    assert abs(root.angle) > 60


def test_dash_leans_further_than_run(hero_rig):
    lean = lambda name, t: motion.get(name).pose_at(hero_rig, t).get("torso").angle
    assert lean("dash", 0.0) > lean("run", 0.0)


def test_the_new_looping_cycles_do_not_retrace_themselves(hero_rig):
    """Locomotion only -- a breathing hold like `crouch` or `sleep` should
    retrace itself, which is what breathing is."""
    for name in ("dash", "climb"):
        assert not _mirrors_itself(motion.get(name), hero_rig), name


def test_a_breathing_hold_peaks_off_centre(hero_rig):
    """Quick in, slow out -- and a peak exactly halfway makes the two off-beats
    the same picture, which on a four-frame loop is half the cycle wasted."""
    for name in ("idle", "crouch", "sleep"):
        animation = motion.get(name)
        quarter = animation.pose_at(hero_rig, 0.25)
        three = animation.pose_at(hero_rig, 0.75)
        assert (quarter.dy, quarter.get(hero_rig.root.name).angle) \
            != (three.dy, three.get(hero_rig.root.name).angle), name
