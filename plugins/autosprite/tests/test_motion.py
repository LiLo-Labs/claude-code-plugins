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


def test_run_bobs_twice_per_cycle():
    run = motion.get("run")
    bob = [run.root.sample(t, True).dy for t in run.times()]
    troughs = sum(1 for index in range(len(bob))
                  if bob[index] < bob[index - 1] and bob[index] <= bob[(index + 1) % len(bob)])
    assert troughs == 2


def test_the_walk_authors_no_bob_at_all():
    """It does not need one. With the feet planted the body's rise and fall
    comes out of the leg geometry, correctly phased and scaled to the character
    -- lowest where the legs are splayed at contact, highest where they pass
    vertically underneath."""
    assert motion.get("walk").root is None
    assert motion.get("walk").planted


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
    run = motion.get("run")
    big = run.scaled(3.0)
    assert big.root.sample(0.25, True).dy == pytest.approx(
        run.root.sample(0.25, True).dy * 3.0)
    assert big.tracks["leg_near"].sample(0.0, True).angle == pytest.approx(
        run.tracks["leg_near"].sample(0.0, True).angle)


def test_scale_motion_uses_the_character_height():
    scaled = motion.scale_motion([motion.get("run")], 64.0, authored_height=32.0)
    assert scaled[0].root.sample(0.25, True).dy == pytest.approx(-4.0)


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


def test_fronted_damps_the_torso_lean_too():
    """The lean is authored in the plane the character walks ALONG, which is the
    plane a head-on camera looks down. It foreshortens exactly as a limb's swing
    does -- and unlike a limb's, what it foreshortens into is a yaw, which a
    32px sprite cannot draw, so nothing comes back on another channel."""
    walk = motion.get("walk")
    front = walk.fronted()
    assert _peak(front.tracks["torso"], "angle") < _peak(walk.tracks["torso"],
                                                         "angle")
    assert _peak(front.tracks["torso"], "dx") == 0
    assert _peak(front.tracks["torso"], "dy") == 0


def test_fronted_is_not_planted():
    """`plant` corrects the daylight a RIGID leg's swing opens under a
    character. `fronted` removes most of that swing and replaces it with a
    deliberate lift -- so what plant finds to correct is the lift itself, and
    normalising every pose to a common floor cancels it into a body bob. The
    foot stays down and the head goes up, which is the animation backwards."""
    walk = motion.get("walk")
    assert walk.planted
    assert not walk.fronted().planted


def test_fronted_keeps_the_timing_and_the_authored_root():
    walk = motion.get("walk")
    front = walk.fronted()
    assert front.frames == walk.frames and front.fps == walk.fps
    # A run bobs whichever way you look at it; only the mechanical floor
    # correction goes, never a bob the clip asked for by name.
    run = motion.get("run")
    assert run.fronted().root.to_list() == run.root.to_list()


def test_fronted_does_not_mutate_the_library():
    walk = motion.get("walk")
    before = walk.tracks["leg_near"].to_list()
    walk.fronted()
    assert motion.get("walk").tracks["leg_near"].to_list() == before


# -- a translation that would round away ----------------------------------

def test_a_bob_scaled_below_a_pixel_is_floored_not_lost():
    """A 16px sprite scales the walk's 1px bob to half a pixel, which cannot be
    drawn, so the character slides instead of walking."""
    small = motion.get("idle").scaled(0.5)
    assert _peak(small.root, "dy") == pytest.approx(0.5)
    assert _peak(small.floored_travel(1.0).root, "dy") == pytest.approx(1.0)


def test_a_travel_that_already_reads_is_left_alone():
    big = motion.get("idle").scaled(3.0)
    before = big.root.to_list()
    assert big.floored_travel(1.0).root.to_list() == before


def test_a_channel_that_was_never_authored_is_not_invented():
    still = motion.Animation("still", frames=2, root=[{"t": 0.0}, {"t": 1.0}])
    assert _peak(still.floored_travel(1.0).root, "dy") == 0.0


def test_scale_motion_floors_the_travel_for_a_small_character():
    scaled = motion.scale_motion([motion.get("idle")], 16)[0]
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


def test_only_the_clips_that_keep_a_foot_down_are_planted():
    grounded = {name for name, animation in motion.LIBRARY.items() if animation.planted}
    assert grounded == {"walk", "attack", "hurt", "cast", "throw", "crouch", "block"}


def test_a_hold_sinks_from_the_legs_rather_than_the_root():
    """`crouch` and `block` first put their sink in a root translation, which
    lifted their feet off the floor (45px and 48px across the corpus) and made
    them impossible to plant -- planting a root-driven sink just deletes it.
    Folding the legs instead produces the same drop with the feet planted."""
    for name in ("crouch", "block"):
        animation = motion.get(name)
        assert animation.root is None, name
        for role in ("leg_near", "leg_far"):
            heights = [key.get("sy", 1.0) for key in animation.tracks[role].keys]
            assert max(heights) - min(heights) > 0.2, name


def test_a_clip_that_leaves_the_ground_is_never_planted():
    for name in ("jump", "land", "run", "dash", "die", "sleep", "climb"):
        assert not motion.get(name).planted, name


# -- an intro followed by a hold ------------------------------------------

def test_block_is_raised_once_and_then_held():
    """A guard is raised once and held while the button is down. Playing the
    raise on every repeat is what a whole-clip loop flag gives you."""
    block = motion.get("block")
    assert block.loop and block.loop_start == 2


def test_a_clip_with_no_loop_points_says_so_rather_than_guessing():
    assert motion.get("walk").loop_start is None
    assert motion.get("walk").loop_end is None


def test_loop_points_move_with_the_frame_count():
    """They name frames, so a sixteen-frame version of a four-frame clip would
    otherwise loop the wrong quarter."""
    dense = motion.get("block").resampled(16)
    assert dense.loop_start == 8


def test_a_loop_point_outside_the_clip_is_caught():
    data = motion.get("walk").to_dict()
    data["loop_start"] = 99
    assert any("loop_start" in problem for problem in motion.validate_animation(data))


def test_a_loop_that_ends_before_it_starts_is_caught():
    data = motion.get("walk").to_dict()
    data["loop_start"], data["loop_end"] = 5, 2
    assert any("before" in problem for problem in motion.validate_animation(data))


def test_loop_points_survive_a_round_trip():
    block = motion.get("block")
    again = motion.Animation.from_dict(block.to_dict())
    assert (again.loop_start, again.loop_end) == (block.loop_start, block.loop_end)


# -- wings ----------------------------------------------------------------

def test_wings_beat_together_where_limbs_alternate(hero_rig):
    """A body has to stay under itself, so legs and arms alternate. Wings beat
    in phase, because that is what produces lift; a wing in counter-phase with
    its partner reads as a broken bird."""
    for name in ("idle", "walk", "run", "fly"):
        animation = motion.get(name)
        near = animation.tracks["wing_near"].to_list()
        far = animation.tracks["wing_far"].to_list()
        assert near == far, name


def test_every_role_in_the_vocabulary_is_driven_or_deliberately_not():
    """A role nothing ever drives is a part the rigger finds, the exporter
    labels, and no animation ever moves -- which is what `wing_near` and
    `wing_far` were until `fly` existed."""
    from spritepipe import rig as R
    driven = set()
    for animation in motion.LIBRARY.values():
        driven |= set(animation.tracks)
    undriven = set(R.ROLES) - driven
    # These four are right to be still: a shadow is the floor, and body, prop
    # and accessory ride whatever they are parented to.
    assert undriven == {"accessory", "body", "prop", "shadow"}


def test_fly_exists_and_is_not_planted():
    fly = motion.get("fly")
    assert not fly.planted and fly.loop
    assert "wing_near" in fly.tracks and "wing_far" in fly.tracks
    assert motion.validate_animation(fly.to_dict()) == []


# ---------------------------------------------------------------------------
# Lanes: one channel of one role, on its own timeline.
# ---------------------------------------------------------------------------

def test_a_pose_key_asserts_rest_for_every_channel_it_omits():
    """The limit lanes exist to lift, asserted on a real clip.

    `cast` keys leg_near at t=0.3 with a squash and never mentions `sy` again.
    The squash unwinds by t=0.55 -- not because anyone authored the unwind, but
    because the later keys omit the channel and omission means rest. Any change
    to sampling has to keep producing these three numbers or sixteen hand-tuned
    clips have silently moved.
    """
    track = motion.get("cast").tracks["leg_near"]
    assert track.sample(0.30, True).sy == pytest.approx(0.92)
    assert track.sample(0.40, True).sy == pytest.approx(0.948, abs=1e-3)
    assert track.sample(0.55, True).sy == pytest.approx(1.0)


def test_no_clip_in_the_library_uses_a_lane_yet():
    """So the test above is a statement about every clip, not just `cast`."""
    tracks = [track for animation in motion.LIBRARY.values()
              for track in list(animation.tracks.values())
              + ([animation.root] if animation.root else [])]
    assert tracks and not any(track.lanes for track in tracks)


def test_a_lane_gives_one_channel_a_timeline_the_others_do_not_share():
    """The whole point: a squash that peaks where the rotation has no key.

    Written as the comparison, because the pose-key version is not merely
    clumsier -- it is a different animation. Adding a `sy` key at t=0.6 to a
    track whose angle is keyed at 0 and 0.5 pulls the ANGLE to rest at 0.6 as
    well, because that key omits it. The lane leaves the angle alone.
    """
    keys = [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 30.0}]
    squash = [{"t": 0.6, "v": 0.8}, {"t": 0.9, "v": 1.0}]

    laned = motion.Track(keys, lanes={"sy": squash})
    posed = motion.Track(keys + [{"t": 0.6, "sy": 0.8}, {"t": 0.9, "sy": 1.0}])

    assert laned.sample(0.6, True).sy == pytest.approx(0.8)
    assert posed.sample(0.6, True).sy == pytest.approx(0.8)

    # ... and the angle at that instant is the thing that differs.
    assert laned.sample(0.6, True).angle == pytest.approx(26.88, abs=0.05)
    assert posed.sample(0.6, True).angle == pytest.approx(0.0)


def test_a_lane_leaves_every_channel_it_does_not_name_alone():
    track = motion.Track([{"t": 0.0, "angle": 10.0, "dx": 3.0}],
                         lanes={"sy": [{"t": 0.0, "v": 0.5}]})
    pose = track.sample(0.4, True)
    assert (pose.angle, pose.dx, pose.sx, pose.sy) == (10.0, 3.0, 1.0, 0.5)


def test_a_track_may_be_nothing_but_lanes():
    track = motion.Track(lanes={"angle": [{"t": 0.0, "v": 0.0},
                                          {"t": 0.5, "v": 20.0}]})
    assert track.sample(0.5, True).angle == pytest.approx(20.0)
    assert track.sample(0.5, True).sx == 1.0     # every other channel at rest


def test_a_track_with_neither_keys_nor_lanes_is_refused():
    with pytest.raises(ValueError):
        motion.Track([])


def test_a_lane_on_a_channel_that_does_not_exist_is_refused():
    with pytest.raises(ValueError):
        motion.Track([{"t": 0.0}], lanes={"wobble": [{"t": 0.0, "v": 1.0}]})


def test_a_lane_keyframe_without_a_value_is_refused():
    with pytest.raises(ValueError):
        motion.Lane([{"t": 0.0}])


def test_a_lane_wraps_the_way_a_track_does():
    """A looping lane's last key leads back to its first a period later, so the
    frame before the wrap moves like every other one."""
    lane = motion.Lane([{"t": 0.0, "v": 0.0}, {"t": 0.5, "v": 10.0}])
    assert lane.sample(0.75, True) == pytest.approx(5.0)
    assert lane.sample(0.75, False) == pytest.approx(10.0)   # clamped instead


def test_a_lane_survives_being_written_out_and_read_back():
    track = motion.Track([{"t": 0.0, "angle": 0.0}],
                         lanes={"dy": [{"t": 0.2, "v": -2.0}, {"t": 0.8, "v": 0.0}]})
    restored = motion.Track.of(json.loads(json.dumps(track.to_dict())))
    for moment in (0.0, 0.3, 0.5, 0.9):
        assert restored.sample(moment, True).dy == pytest.approx(
            track.sample(moment, True).dy)


def test_a_track_without_lanes_still_serialises_as_a_plain_list():
    """Every animation written before lanes existed round-trips unchanged."""
    assert motion.get("walk").tracks["leg_near"].to_dict() == \
        motion.get("walk").tracks["leg_near"].to_list()


def test_scaling_for_a_bigger_character_scales_a_translation_lane():
    animation = motion.Animation("bobbing", 4, tracks={
        "torso": motion.Track([{"t": 0.0}], lanes={"dy": [{"t": 0.0, "v": -1.0},
                                                          {"t": 0.5, "v": 0.0}]})})
    assert animation.scaled(3.0).tracks["torso"].values("dy") == [-3.0, 0.0]


def test_a_squash_floor_reaches_into_a_lane():
    animation = motion.Animation("squashing", 4, tracks={
        "torso": motion.Track([{"t": 0.0}], lanes={"sy": [{"t": 0.0, "v": 0.1}]})})
    assert animation.floored(0.0, 0.4).tracks["torso"].values("sy") == [0.4]


def test_damping_a_broken_clip_reaches_into_an_angle_lane():
    """`repair` damps the swing that threw a limb clear of the body. It has to
    find that swing whichever way the track stores it."""
    from spritepipe import repair

    animation = motion.Animation("swinging", 4, tracks={
        "arm_near": motion.Track([{"t": 0.0}],
                                 lanes={"angle": [{"t": 0.0, "v": 90.0}]})})
    assert repair.damp(animation, ["arm_near"], 0.5) \
        .tracks["arm_near"].values("angle") == [45.0]


def test_a_face_on_rewrite_turns_a_lane_swing_into_a_lift():
    """`fronted` reads an angle and re-emits it on another channel. With a lane
    the target channel has no key at the angle's instants, so the offset has to
    be derived at the angle's own times rather than merged into a shared key."""
    animation = motion.Animation("striding", 4, tracks={
        "leg_near": motion.Track([{"t": 0.0}],
                                 lanes={"angle": [{"t": 0.0, "v": 20.0},
                                                  {"t": 0.5, "v": -20.0}]})})
    track = animation.fronted(swing=0.3, lift=1.5).tracks["leg_near"]
    assert track.values("angle") == [pytest.approx(6.0), pytest.approx(-6.0)]
    # Peak forward swing lifts the foot; the far end of the stride puts it down.
    assert track.values("dy") == [pytest.approx(-1.5), pytest.approx(1.5)]


def test_a_custom_animation_may_be_written_with_lanes(tmp_path):
    """The user-facing path: a JSON file with a lane in it validates, loads and
    samples. This is what "make the squash land after the punch" has to be
    writable as."""
    document = {"name": "punch", "frames": 6, "fps": 12, "loop": False,
                "tracks": {"arm_near": {
                    "keys": [{"t": 0.0, "angle": -20.0}, {"t": 0.4, "angle": 70.0}],
                    "lanes": {"sx": [{"t": 0.55, "v": 1.15}, {"t": 1.0, "v": 1.0}]}}}}
    assert motion.validate_animation(document) == []
    path = tmp_path / "punch.json"
    path.write_text(json.dumps(document))
    animation, = motion.load_custom(str(path))
    track = animation.tracks["arm_near"]
    # The stretch peaks after the swing has already arrived -- follow-through.
    assert track.sample(0.4, False).angle == pytest.approx(70.0)
    assert track.sample(0.4, False).sx == pytest.approx(1.15)
    assert track.sample(0.55, False).sx == pytest.approx(1.15)
    assert track.sample(1.0, False).sx == pytest.approx(1.0)


def test_a_lane_with_a_bad_keyframe_is_reported_rather_than_rendered():
    bad = {"name": "x", "frames": 4, "tracks": {"head": {
        "keys": [{"t": 0.0}], "lanes": {"angle": [{"t": 0.0}]}}}}
    problems = motion.validate_animation(bad)
    assert any("lane keyframe that is not" in problem for problem in problems)


def test_a_lane_on_a_channel_that_is_not_a_channel_is_reported():
    bad = {"name": "x", "frames": 4, "tracks": {"head": {
        "keys": [{"t": 0.0}], "lanes": {"wobble": [{"t": 0.0, "v": 1.0}]}}}}
    assert any("not a channel" in problem
               for problem in motion.validate_animation(bad))


def test_a_broken_root_track_is_reported_rather_than_ignored():
    """The root track was validated by nothing at all until lanes arrived."""
    bad = {"name": "x", "frames": 4, "root": [{"dy": -2.0}]}
    assert any("no t" in problem for problem in motion.validate_animation(bad))


# ---------------------------------------------------------------------------
# Selectors: addressing parts by what they ARE, not by a humanoid role name.
# ---------------------------------------------------------------------------

@pytest.fixture
def windmill_rig():
    """A subject with no humanoid part in it at all.

    Four sails on a hub, listed clockwise, tagged `spinner` -- a trait no role
    in the thirteen-name enum carries, which is exactly why the enum could not
    animate this building except by bobbing the whole house.
    """
    return R.Rig((16, 16), [
        R.Part("tower", "body", (4, 4, 12, 16), None, (8, 15), 0),
        R.Part("sail_n", "accessory", (7, 1, 9, 6), "tower", (8, 6), 1, tags=("spinner",)),
        R.Part("sail_e", "accessory", (9, 5, 14, 7), "tower", (8, 6), 1, tags=("spinner",)),
        R.Part("sail_s", "accessory", (7, 6, 9, 11), "tower", (8, 6), 1, tags=("spinner",)),
        R.Part("sail_w", "accessory", (2, 5, 7, 7), "tower", (8, 6), 1, tags=("spinner",)),
    ])


def test_a_trait_track_drives_every_part_that_has_the_trait(windmill_rig):
    turn = motion.Animation("turn", 4, tracks={
        "trait:spinner": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 180.0}]})
    pose = turn.pose_at(windmill_rig, 0.5)
    assert [round(pose.get(name).angle) for name in
            ("sail_n", "sail_e", "sail_s", "sail_w")] == [180, 180, 180, 180]
    assert pose.get("tower").angle == 0.0      # the tower is not a spinner


def test_a_name_selector_drives_exactly_one_part(windmill_rig):
    animation = motion.Animation("one", 4, tracks={
        "name:sail_e": [{"t": 0.0, "angle": 40.0}]})
    pose = animation.pose_at(windmill_rig, 0.0)
    assert pose.get("sail_e").angle == 40.0
    assert pose.get("sail_n").angle == 0.0


def test_a_spread_makes_one_track_a_travelling_wave(windmill_rig):
    """The mechanism behind wheat bending in sequence and a chain following
    the link before it: each matched part plays the same curve a bit later."""
    wave = motion.Animation("wave", 4, tracks={
        "trait:spinner": {"keys": [{"t": 0.0, "angle": 0.0},
                                   {"t": 0.5, "angle": 20.0}],
                          "spread": 0.25}})
    pose = wave.pose_at(windmill_rig, 0.5)
    angles = [pose.get(name).angle for name in
              ("sail_n", "sail_e", "sail_s", "sail_w")]
    assert angles[0] == pytest.approx(20.0)           # at its peak
    assert angles[2] == pytest.approx(0.0)            # half a cycle behind
    assert len(set(round(a, 3) for a in angles)) > 1  # not lockstep


def test_a_role_track_is_the_base_and_a_trait_track_composes_onto_it(humanoid_rig):
    """The ordering that makes a broad statement safe to write. A lag applied
    to every limb must leave each limb's own authored swing alone."""
    animation = motion.Animation("both", 4, tracks={
        "arm_near": [{"t": 0.0, "angle": 30.0}],
        "trait:limb": [{"t": 0.0, "angle": 5.0}]})
    pose = animation.pose_at(humanoid_rig, 0.0)
    assert pose.get("arm_near").angle == pytest.approx(35.0)
    assert pose.get("leg_near").angle == pytest.approx(5.0)


def test_a_name_selector_outranks_a_role_track(windmill_rig):
    animation = motion.Animation("both", 4, tracks={
        "name:sail_n": [{"t": 0.0, "angle": 90.0, "sx": 2.0}],
        "accessory": [{"t": 0.0, "angle": 10.0, "sx": 3.0}]})
    pose = animation.pose_at(windmill_rig, 0.0)
    # Rotations add and squashes multiply whichever way round they compose, so
    # what specificity decides is only which one is the base -- and the answer
    # has to be the same every run, whatever order the dict happens to iterate.
    assert pose.get("sail_n").angle == pytest.approx(100.0)
    assert pose.get("sail_n").sx == pytest.approx(6.0)


def test_composing_layers_does_not_depend_on_dictionary_order(windmill_rig):
    """Two trait tracks match the same part; the result must be stable."""
    first = motion.Animation("a", 4, tracks={
        "trait:spinner": [{"t": 0.0, "angle": 7.0}],
        "trait:socket": [{"t": 0.0, "angle": 3.0}]})
    second = motion.Animation("a", 4, tracks={
        "trait:socket": [{"t": 0.0, "angle": 3.0}],
        "trait:spinner": [{"t": 0.0, "angle": 7.0}]})
    assert first.pose_at(windmill_rig, 0.0).get("sail_n").angle == \
        second.pose_at(windmill_rig, 0.0).get("sail_n").angle


def test_a_trait_is_a_property_of_the_role_and_of_the_tags():
    part = R.Part("cape", "accessory", (0, 0, 4, 8), tags=("cloth",))
    assert part.has_trait("stalk")     # every accessory rides with a lag
    assert part.has_trait("socket")
    assert part.has_trait("cloth")     # ... and this rig said so explicitly
    assert not part.has_trait("limb")


def test_tags_survive_a_rig_being_written_out_and_read_back():
    part = R.Part("sails", "accessory", (0, 0, 8, 8), tags=("spinner",))
    assert R.Part.from_dict(json.loads(json.dumps(part.to_dict()))).tags == ("spinner",)


def test_a_rig_without_tags_does_not_grow_a_tags_field():
    """A rig file that gained an empty key on every part would be a diff on
    every rig anyone has already saved."""
    assert "tags" not in R.Part("head", "head", (0, 0, 4, 4)).to_dict()


def test_a_trait_that_is_not_a_trait_is_reported():
    bad = {"name": "x", "frames": 4,
           "tracks": {"trait:wobbly": [{"t": 0.0, "angle": 1.0}]}}
    assert any("is not a trait" in problem
               for problem in motion.validate_animation(bad))


def test_a_selector_track_validates_and_round_trips():
    document = {"name": "turn", "frames": 8, "tracks": {
        "trait:spinner": {"keys": [{"t": 0.0, "angle": 0.0},
                                   {"t": 0.5, "angle": 180.0}], "spread": 0.1}}}
    assert motion.validate_animation(document) == []
    restored = motion.Animation.from_dict(document)
    assert restored.tracks["trait:spinner"].spread == pytest.approx(0.1)
    assert restored.to_dict()["tracks"]["trait:spinner"]["spread"] == pytest.approx(0.1)


def test_a_spread_of_a_whole_cycle_is_refused():
    """A spread of 1 is a spread of 0 with extra steps, and a spread above it
    reads as frames rather than as a fraction -- the mistake worth catching."""
    bad = {"name": "x", "frames": 4, "tracks": {
        "trait:limb": {"keys": [{"t": 0.0, "angle": 1.0}], "spread": 2}}}
    assert any("fraction of the cycle" in problem
               for problem in motion.validate_animation(bad))


# ---------------------------------------------------------------------------
# Which way the wave travels. Without an axis a spread plays parts in the order
# the rig listed them, which makes the DIRECTION of a wind a property of how
# carefully somebody typed out a rig file.
# ---------------------------------------------------------------------------

@pytest.fixture
def wheat_rig():
    """The rig the vision backend actually returned for a CC0 wheat field.

    Four stalks left to right and THEN a full-width sheet lying over all of
    them -- so declaration order and left-to-right order already disagree in
    the first real multi-part subject the spread was ever pointed at. The
    stalks are also unevenly wide, which is the second disagreement: a crest
    crossing them does not arrive at even intervals.
    """
    return R.Rig((14, 13), [
        R.Part("field_base", "body", (0, 9, 14, 13), None, (7, 13), 0,
               tags=("ground",)),
        R.Part("stalk_left", "accessory", (0, 3, 4, 10), "field_base", (2, 10), 1),
        R.Part("stalk_left_mid", "accessory", (4, 1, 7, 10), "field_base", (5, 10), 1),
        R.Part("stalk_right_mid", "accessory", (7, 1, 10, 10), "field_base", (8, 10), 1),
        R.Part("stalk_right", "accessory", (10, 3, 14, 10), "field_base", (12, 10), 1),
        R.Part("canopy_sheet", "accessory", (0, 1, 14, 10), "field_base", (7, 10), 2),
    ])


def test_without_an_axis_a_spread_is_declaration_order(wheat_rig):
    parts = motion.select(wheat_rig, "trait:stalk")
    assert motion.phases(wheat_rig, parts) == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_a_part_spanning_the_whole_selection_lands_in_its_middle(wheat_rig):
    """The defect this was built for. `canopy_sheet` covers the entire field,
    and declaration order plays it LAST -- as though it stood to the right of
    every stalk it lies over. By position it plays at the centre, where it is."""
    parts = motion.select(wheat_rig, "trait:stalk")
    names = [part.name for part in parts]
    by_order = dict(zip(names, motion.phases(wheat_rig, parts)))
    by_place = dict(zip(names, motion.phases(wheat_rig, parts, "x")))
    assert by_order["canopy_sheet"] == 4.0
    assert by_place["canopy_sheet"] == pytest.approx(2.0)
    assert by_place["canopy_sheet"] == pytest.approx(max(by_place.values()) / 2.0)


def test_the_crest_crosses_uneven_gaps_in_uneven_time(wheat_rig):
    """Four stalks of different widths are not four even steps. Ranking them
    says the wave hops between parts; placing them says it travels."""
    parts = [part for part in motion.select(wheat_rig, "trait:stalk")
             if part.name != "canopy_sheet"]
    places = motion.phases(wheat_rig, parts, "x")
    gaps = [round(b - a, 3) for a, b in zip(places, places[1:])]
    assert places[0] == 0.0 and places[-1] == pytest.approx(3.0)
    assert len(set(gaps)) > 1                       # not evenly spaced
    assert gaps == sorted(gaps, reverse=True) or gaps[0] > gaps[1]


def test_an_axis_reverses_the_wind(wheat_rig):
    parts = motion.select(wheat_rig, "trait:stalk")
    forward = motion.phases(wheat_rig, parts, "x")
    backward = motion.phases(wheat_rig, parts, "-x")
    top = max(forward)
    assert backward == pytest.approx([top - value for value in forward])


def test_evenly_spaced_parts_listed_in_order_place_exactly_as_they_rank():
    """The property that makes this a generalisation rather than a change: when
    the geometry agrees with the declaration order and the spacing is even,
    placing by position returns the ranks it replaces, exactly."""
    rig = R.Rig((40, 10), [R.Part("base", "body", (0, 8, 40, 10), None, (20, 10), 0)] +
                [R.Part("s%d" % i, "accessory", (i * 10, 0, i * 10 + 4, 8),
                        "base", (i * 10 + 2, 8), 1) for i in range(4)])
    parts = motion.select(rig, "trait:stalk")
    assert motion.phases(rig, parts, "x") == pytest.approx([0.0, 1.0, 2.0, 3.0])
    assert motion.phases(rig, parts, "x") == motion.phases(rig, parts)


def test_parts_stacked_at_one_point_have_no_wave_to_travel(windmill_rig):
    """Four sails share a hub, so along a radius they are all at the same place.
    That collapses to no spread rather than to an arbitrary order."""
    parts = motion.select(windmill_rig, "trait:spinner")
    same = R.Rig((16, 16), [windmill_rig.parts[0]] + [
        R.Part(part.name, part.role, (7, 5, 9, 7), "tower", (8, 6), 1,
               tags=("spinner",)) for part in parts])
    stacked = motion.select(same, "trait:spinner")
    assert motion.phases(same, stacked, "x") == [0.0, 0.0, 0.0, 0.0]


def test_a_chain_is_measured_along_the_skeleton_not_the_image():
    """A tail curled back on itself doubles back in x, so every spatial axis
    reads its tip as being beside its root. Depth in the rig does not."""
    rig = R.Rig((20, 20), [
        R.Part("body", "body", (0, 8, 10, 16), None, (5, 12), 0),
        R.Part("tail_a", "tail", (10, 8, 16, 12), "body", (10, 10), 1),
        R.Part("tail_b", "tail", (12, 4, 18, 8), "tail_a", (16, 8), 1),
        R.Part("tail_c", "tail", (6, 2, 12, 6), "tail_b", (12, 5), 1),
    ])
    parts = motion.select(rig, "trait:stalk")
    assert [part.name for part in parts] == ["tail_a", "tail_b", "tail_c"]
    assert motion.phases(rig, parts, "chain") == pytest.approx([0.0, 1.0, 2.0])
    # In x the tip has come back past the middle segment, so a spatial axis
    # would play it out of order along its own chain.
    in_x = motion.phases(rig, parts, "x")
    assert in_x[2] < in_x[1]


def test_the_axis_changes_which_part_is_at_its_peak(wheat_rig):
    """Not just a table of numbers: the rendered pose differs."""
    clip = motion.Animation("wind", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 12.0}],
                        "spread": 0.12}})
    placed = motion.Animation("wind", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 12.0}],
                        "spread": 0.12, "along": "x"}})
    ranked_pose = clip.pose_at(wheat_rig, 0.5)
    placed_pose = placed.pose_at(wheat_rig, 0.5)
    assert (ranked_pose.get("canopy_sheet").angle
            != pytest.approx(placed_pose.get("canopy_sheet").angle))


def test_an_unknown_axis_is_refused_at_construction():
    with pytest.raises(ValueError) as caught:
        motion.Track([{"t": 0.0, "angle": 1.0}], spread=0.1, along="sideways")
    assert "sideways" in str(caught.value)


def test_an_unknown_axis_is_reported_by_the_validator():
    problems = motion.validate_animation({
        "name": "bad", "frames": 4,
        "tracks": {"trait:stalk": {"keys": [{"t": 0.0, "angle": 1.0}],
                                   "spread": 0.1, "along": "widdershins"}}})
    assert any("widdershins" in problem for problem in problems)


def test_an_axis_without_a_spread_is_cautioned_but_still_builds():
    """An axis with nothing to distribute along it says which way the wind
    blows and then blows on everything at once. That is a mistake, not a broken
    clip, so it is a caution and the build goes ahead."""
    document = {"name": "still", "frames": 4,
                "tracks": {"trait:stalk": {"keys": [{"t": 0.0, "angle": 1.0}],
                                           "along": "x"}}}
    assert motion.validate_animation(document) == []
    assert any("does nothing" in note for note in motion.cautions(document))


def test_an_axis_survives_a_round_trip():
    animation = motion.Animation.from_dict({
        "name": "w", "frames": 4,
        "tracks": {"trait:stalk": {"keys": [{"t": 0.0, "angle": 1.0}],
                                   "spread": 0.1, "along": "-x"}}})
    assert animation.tracks["trait:stalk"].along == "-x"
    assert animation.to_dict()["tracks"]["trait:stalk"]["along"] == "-x"


def test_a_track_with_no_axis_still_serialises_as_a_bare_list():
    """Every clip written before axes existed round-trips unchanged."""
    animation = motion.Animation("plain", 4, tracks={
        "trait:stalk": [{"t": 0.0, "angle": 1.0}]})
    assert isinstance(animation.to_dict()["tracks"]["trait:stalk"], list)


# ---------------------------------------------------------------------------
# Cautions: clips that build perfectly and are still not what anyone meant.
# All three of these were found in this plugin's OWN library.
# ---------------------------------------------------------------------------

def test_a_spread_of_a_whole_frame_makes_every_part_a_copy():
    """`ripple` spread by 0.125 on an eight-frame clip -- exactly one frame --
    so two banners rendered as the SAME EIGHT PICTURES, byte for byte, one
    frame apart. A spread is meant to make a selection look like several
    things."""
    document = {"name": "r", "frames": 8,
                "tracks": {"trait:surface": {"keys": [{"t": 0.0, "wave": 0.0},
                                                      {"t": 0.5, "wave": 4.0}],
                                             "spread": 0.125}}}
    assert motion.validate_animation(document) == []
    assert any("byte-identical" in note for note in motion.cautions(document))


def test_a_spread_off_a_whole_frame_is_not_cautioned():
    document = {"name": "r", "frames": 8,
                "tracks": {"trait:surface": {"keys": [{"t": 0.0, "wave": 0.0},
                                                      {"t": 0.5, "wave": 4.0}],
                                             "spread": 0.15}}}
    assert motion.cautions(document) == []


def test_a_spread_on_a_stepped_channel_is_cautioned_at_any_size():
    """The renderer rounds `cycle` to whole shades, so a spread there hands the
    next part the same table read from a different place. Measured on two gem
    faces: 0.25 and 0.30 of a cycle give byte-identical frames."""
    for spread in (0.25, 0.3, 0.11):
        document = {"name": "s", "frames": 8,
                    "tracks": {"trait:glow": {"keys": [{"t": 0.0, "cycle": 0.0},
                                                       {"t": 0.5, "cycle": 2.0}],
                                              "spread": spread}}}
        notes = motion.cautions(document)
        assert any("rounds to whole steps" in note for note in notes), spread


def test_turbulence_on_the_same_channel_answers_the_stepped_caution():
    """The caution is about a spread being ALONE on a stepped channel, not
    about a spread. `flicker` and `shimmer` both carry one and neither is
    cautioned, because both were given a wander that does vary them."""
    document = {"name": "s", "frames": 8,
                "tracks": {"trait:glow": {"keys": [{"t": 0.0, "cycle": 0.0},
                                                   {"t": 0.5, "cycle": 2.0}],
                                          "spread": 0.25}},
                "ops": [{"op": "turbulence", "on": "trait:glow",
                         "amount": 0.6, "channels": ["cycle"], "rate": 3}]}
    assert motion.cautions(document) == []


def test_the_shipped_libraries_raise_no_cautions():
    """The check that keeps this honest: it found three clips here when it was
    written, and it must find none now."""
    from spritepipe import props as props_module
    everything = list(motion.LIBRARY.values()) + list(props_module.LIBRARY.values())
    found = [(clip.name, note) for clip in everything
             for note in motion.cautions(clip.to_dict())]
    assert found == []
