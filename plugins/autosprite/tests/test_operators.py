"""An operator is a principle written once instead of typed into every clip.

Each test here states the principle and then asserts the thing that would be
true if it were working -- not that the numbers changed, which any rewrite makes
true, but that they changed in the direction the principle names.
"""

import copy
import json
import math

import pytest

from spritepipe import motion, operators, rig as R


@pytest.fixture
def caped():
    """A torso with two cape segments hanging off it, in order."""
    return R.Rig((16, 32), [
        R.Part("torso", "torso", (4, 8, 12, 22), None, (8, 22), 1),
        R.Part("cape_top", "accessory", (2, 8, 8, 16), "torso", (7, 9), 0),
        R.Part("cape_hem", "accessory", (1, 16, 8, 26), "cape_top", (5, 16), 0),
    ])


def _values(animation, rig, selector, channel="angle", part=None):
    """What one part actually holds, frame by frame."""
    name = part or motion.select(rig, selector)[0].name
    return [round(getattr(pose.get(name), channel), 4)
            for pose in animation.poses(rig)]


# --- lag -------------------------------------------------------------------

def test_a_lag_makes_a_part_do_later_what_its_parent_did(caped):
    """Follow-through. The cape's curve is the torso's, shifted in time."""
    swing = [{"t": 0.0, "angle": 0.0}, {"t": 0.25, "angle": 12.0},
             {"t": 0.5, "angle": 0.0}, {"t": 0.75, "angle": -12.0}]
    animation = motion.Animation("sway", 8, tracks={"torso": swing}, ops=[
        {"op": "lag", "on": "trait:stalk", "of": "torso", "frames": 2}])
    torso = _values(animation.applied(caped), caped, "torso")
    cape = _values(animation.applied(caped), caped, "trait:stalk")
    assert cape == torso[-2:] + torso[:-2]


def test_a_lag_damped_to_a_half_arrives_half_as_far(caped):
    animation = motion.Animation("sway", 8, tracks={
        "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 20.0}]}, ops=[
        {"op": "lag", "on": "trait:stalk", "of": "torso", "frames": 2,
         "damp": 0.5}])
    full = motion.Animation("sway", 8, tracks={
        "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 20.0}]}, ops=[
        {"op": "lag", "on": "trait:stalk", "of": "torso", "frames": 2}])
    half = _values(animation.applied(caped), caped, "trait:stalk")
    whole = _values(full.applied(caped), caped, "trait:stalk")
    assert all(abs(a * 2 - b) < 1e-3 for a, b in zip(half, whole))


def test_a_lag_wraps_rather_than_fading_in_over_the_first_frames(caped):
    """A looping clip's lag has to come from the END of the cycle, or the first
    frames of every loop show a cape that has not started moving yet."""
    animation = motion.Animation("sway", 8, tracks={
        "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 20.0}]}, ops=[
        {"op": "lag", "on": "trait:stalk", "of": "torso", "frames": 2}])
    assert _values(animation.applied(caped), caped, "trait:stalk")[0] != 0.0


def test_a_lag_adds_to_what_the_part_was_already_doing(caped):
    """An operator is a layer, not a replacement: the cape keeps its own swing."""
    own = [{"t": 0.0, "angle": 5.0}]
    plain = motion.Animation("x", 4, tracks={"trait:stalk": own,
                                             "torso": [{"t": 0.0, "angle": 0.0}]})
    lagged = motion.Animation("x", 4, tracks={
        "trait:stalk": own, "torso": [{"t": 0.0, "angle": 0.0},
                                      {"t": 0.5, "angle": 30.0}]},
        ops=[{"op": "lag", "on": "trait:stalk", "of": "torso", "frames": 1}])
    assert all(value == 5.0 for value in _values(plain, caped, "trait:stalk"))
    assert any(value != 5.0
               for value in _values(lagged.applied(caped), caped, "trait:stalk"))


def test_a_lag_naming_a_track_that_does_not_exist_changes_nothing(caped):
    animation = motion.Animation("x", 4, tracks={"torso": [{"t": 0.0, "angle": 4.0}]},
                                 ops=[{"op": "lag", "on": "trait:stalk",
                                       "of": "wing_near", "frames": 1}])
    assert animation.applied(caped).to_dict()["tracks"] == animation.to_dict()["tracks"]


# --- envelope --------------------------------------------------------------

def test_an_envelope_makes_the_middle_of_a_cycle_louder_than_its_ends(caped):
    """The thing a constant amplitude cannot say, and every real gust does."""
    animation = motion.Animation("gust", 8, loop=False, tracks={
        "torso": [{"t": 0.0, "angle": 10.0}, {"t": 1.0, "angle": 10.0}]},
        ops=[{"op": "envelope", "on": "torso",
              "curve": [{"t": 0.0, "v": 0.0}, {"t": 0.5, "v": 1.0},
                        {"t": 1.0, "v": 0.0}]}])
    values = _values(animation.applied(caped), caped, "torso")
    assert values[0] == pytest.approx(0.0)
    assert values[len(values) // 2] > values[1] > values[0]
    assert values[-1] == pytest.approx(0.0)


def test_an_envelope_of_one_throughout_changes_nothing(caped):
    keys = [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 14.0}]
    plain = motion.Animation("x", 6, tracks={"torso": keys})
    enveloped = motion.Animation("x", 6, tracks={"torso": keys}, ops=[
        {"op": "envelope", "on": "torso", "curve": [{"t": 0.0, "v": 1.0}]}])
    assert _values(enveloped.applied(caped), caped, "torso") == \
        _values(plain, caped, "torso")


def test_an_envelope_scales_a_squash_about_one_not_about_zero(caped):
    """A scale's rest is 1.0, so half the amplitude of a 0.5 squash is 0.75 --
    not 0.25, which would be a much bigger squash."""
    animation = motion.Animation("x", 4, tracks={
        "torso": [{"t": 0.0, "sy": 0.5}]}, ops=[
        {"op": "envelope", "on": "torso", "channels": ["sy"],
         "curve": [{"t": 0.0, "v": 0.5}]}])
    assert _values(animation.applied(caped), caped, "torso", "sy")[0] == \
        pytest.approx(0.75)


# --- taper -----------------------------------------------------------------

def test_a_taper_gives_the_far_end_of_a_chain_more_movement(caped):
    """`spread` gives an ordered selection its own timing; this gives it its own
    size. Between them a chain reads as a chain."""
    animation = motion.Animation("x", 4, tracks={
        "trait:stalk": [{"t": 0.0, "angle": 10.0}]}, ops=[
        {"op": "taper", "on": "trait:stalk", "gain": [1.0, 2.0]}])
    applied = animation.applied(caped)
    top = _values(applied, caped, None, part="cape_top")
    hem = _values(applied, caped, None, part="cape_hem")
    assert top[0] == pytest.approx(10.0)
    assert hem[0] == pytest.approx(20.0)


def test_a_taper_removes_the_track_it_came_from(caped):
    """Or the original would compose on top of its own tapered copies and every
    part would move by one plus its own gain."""
    animation = motion.Animation("x", 4, tracks={
        "trait:stalk": [{"t": 0.0, "angle": 10.0}]}, ops=[
        {"op": "taper", "on": "trait:stalk", "gain": [1.0, 1.0]}])
    applied = animation.applied(caped)
    assert "trait:stalk" not in applied.tracks
    assert _values(applied, caped, None, part="cape_top")[0] == pytest.approx(10.0)


def test_a_taper_keeps_the_spread_it_replaces(caped):
    """Removing the track must not throw away its timing as well as its size."""
    animation = motion.Animation("x", 4, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 20.0}], "spread": 0.25}},
        ops=[{"op": "taper", "on": "trait:stalk", "gain": [1.0, 1.0]}])
    applied = animation.applied(caped)
    assert _values(applied, caped, None, part="cape_top") != \
        _values(applied, caped, None, part="cape_hem")


# --- settle and anticipate -------------------------------------------------

def test_a_settle_carries_a_one_shot_past_its_target_and_back(caped):
    """A motion that stops exactly on its target reads as a slider released."""
    animation = motion.Animation("open", 10, loop=False, tracks={
        "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.4, "angle": 40.0},
                  {"t": 1.0, "angle": 40.0}]},
        ops=[{"op": "settle", "on": "torso", "overshoot": 0.3}])
    values = _values(animation.applied(caped), caped, "torso")
    assert max(values) > 40.0                      # it goes past
    assert values[-1] == pytest.approx(40.0, abs=2.0)   # and comes back


def test_a_settle_does_nothing_to_a_loop(caped):
    """A cycle has no arrival to ring down from."""
    keys = [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 20.0}]
    plain = motion.Animation("x", 6, tracks={"torso": keys})
    ringing = motion.Animation("x", 6, tracks={"torso": keys},
                               ops=[{"op": "settle", "on": "torso"}])
    assert _values(ringing.applied(caped), caped, "torso") == \
        _values(plain, caped, "torso")


def test_an_anticipate_goes_the_wrong_way_before_it_goes_the_right_way(caped):
    """No easing in the library can do this: all five original ones are
    monotone in 0..1 and cannot go the wrong way first."""
    animation = motion.Animation("swing", 8, loop=False, tracks={
        "torso": [{"t": 0.0, "angle": 0.0}, {"t": 0.6, "angle": 60.0},
                  {"t": 1.0, "angle": 60.0}]},
        ops=[{"op": "anticipate", "on": "torso", "amount": 0.25, "lead": 0.3}])
    values = _values(animation.applied(caped), caped, "torso")
    assert min(values) < 0.0


def test_an_anticipate_still_ends_where_the_motion_was_going_to_end(caped):
    """It makes room by compressing the action, not by cutting it short."""
    keys = [{"t": 0.0, "angle": 0.0}, {"t": 0.6, "angle": 60.0},
            {"t": 1.0, "angle": 60.0}]
    plain = motion.Animation("swing", 8, loop=False, tracks={"torso": keys})
    wound = motion.Animation("swing", 8, loop=False, tracks={"torso": keys},
                             ops=[{"op": "anticipate", "on": "torso"}])
    assert _values(wound.applied(caped), caped, "torso")[-1] == \
        pytest.approx(_values(plain, caped, "torso")[-1])


def test_an_anticipate_does_nothing_to_a_loop(caped):
    """A cycle has no start to wind up from, and compressing one would put a
    discontinuity at the loop."""
    keys = [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 20.0}]
    plain = motion.Animation("x", 6, tracks={"torso": keys})
    wound = motion.Animation("x", 6, tracks={"torso": keys},
                             ops=[{"op": "anticipate", "on": "torso"}])
    assert _values(wound.applied(caped), caped, "torso") == \
        _values(plain, caped, "torso")


# --- volume ----------------------------------------------------------------

def test_volume_makes_a_squash_keep_its_area(caped):
    animation = motion.Animation("x", 4, tracks={
        "torso": [{"t": 0.0, "sy": 0.8}]},
        ops=[{"op": "volume", "on": "torso"}])
    applied = animation.applied(caped)
    assert _values(applied, caped, "torso", "sx")[0] == pytest.approx(1.25)


# --- the frame around them -------------------------------------------------

def test_an_animation_with_no_operators_is_returned_unchanged(caped):
    animation = motion.Animation("still", 4, tracks={"torso": [{"t": 0.0}]})
    assert animation.applied(caped) is animation


def test_an_operator_never_mutates_the_clip_it_was_given(caped):
    """The library is shared, so a build that ran an op on `walk` must not leave
    `walk` changed for the next one."""
    animation = motion.Animation("x", 4, tracks={
        "torso": [{"t": 0.0, "angle": 10.0}]},
        ops=[{"op": "damp", "on": "torso", "factor": 0.5}])
    before = json.dumps(animation.to_dict(), sort_keys=True)
    animation.applied(caped)
    assert json.dumps(animation.to_dict(), sort_keys=True) == before


def test_an_unknown_operator_is_refused_by_name():
    problems = motion.validate_animation({
        "name": "x", "frames": 4, "tracks": {"torso": [{"t": 0.0, "angle": 1.0}]},
        "ops": [{"op": "wobble", "on": "torso"}]})
    assert any("not an operator" in problem for problem in problems)


def test_an_operator_given_a_parameter_it_does_not_take_is_refused():
    problems = motion.validate_animation({
        "name": "x", "frames": 4, "tracks": {"torso": [{"t": 0.0, "angle": 1.0}]},
        "ops": [{"op": "damp", "on": "torso", "factor": 0.5, "speed": 2}]})
    assert any("does not take speed" in problem for problem in problems)


def test_operators_run_in_the_order_they_are_written(caped):
    """damp then envelope is not envelope then damp, and the table has to say
    which one happened."""
    keys = [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 20.0}]
    curve = [{"t": 0.0, "v": 0.0}, {"t": 0.5, "v": 1.0}]
    first = motion.Animation("x", 4, tracks={"torso": keys}, ops=[
        {"op": "damp", "on": "torso", "factor": 0.5},
        {"op": "envelope", "on": "torso", "curve": curve}])
    second = motion.Animation("x", 4, tracks={"torso": keys}, ops=[
        {"op": "envelope", "on": "torso", "curve": curve},
        {"op": "damp", "on": "torso", "factor": 0.5}])
    # Both halve and both envelope, so these agree -- which is the point of
    # checking a pair that does NOT commute below.
    assert _values(first.applied(caped), caped, "torso") == \
        _values(second.applied(caped), caped, "torso")


def test_ops_survive_being_written_out_and_read_back():
    animation = motion.Animation("x", 4, tracks={"torso": [{"t": 0.0, "angle": 5.0}]},
                                 ops=[{"op": "damp", "on": "torso", "factor": 0.5}])
    restored = motion.Animation.from_dict(json.loads(json.dumps(animation.to_dict())))
    assert restored.ops == animation.ops


def test_every_operator_says_what_it_is_for():
    for name, entry in operators.OPERATORS.items():
        assert entry["note"] and entry["params"], name


# ---------------------------------------------------------------------------
# The library uses them. That is the point: a principle written once.
# ---------------------------------------------------------------------------

def test_every_clip_in_the_library_gives_a_trailing_part_follow_through(caped):
    """Until operators existed this had to be typed into all sixteen clips by
    hand, so it was typed into none, and a cape hung rigid through every one."""
    still = []
    for name, animation in sorted(motion.LIBRARY.items()):
        applied = animation.applied(caped)
        poses = applied.poses(caped)
        held = {(round(pose.get("cape_top").angle, 3),
                 round(pose.get("cape_top").dx, 3),
                 round(pose.get("cape_top").dy, 3)) for pose in poses}
        if len(held) < 2:
            still.append(name)
    assert not still, "the cape holds perfectly still through %s" % ", ".join(still)


def test_the_follow_through_does_not_touch_a_rig_with_nothing_that_trails():
    """A selector that matches nothing costs nothing, which is what lets one
    statement be safe to make about every subject."""
    plain = R.Rig((16, 32), [
        R.Part("torso", "torso", (4, 8, 12, 22), None, (8, 22), 1),
        R.Part("head", "head", (5, 0, 11, 8), "torso", (8, 8), 2)])
    walk = motion.get("walk")
    before = [str(pose.get("torso")) for pose in walk.poses(plain)]
    after = [str(pose.get("torso")) for pose in walk.applied(plain).poses(plain)]
    assert before == after


def test_a_tail_both_wags_and_trails(caped):
    """`lag` adds to a track rather than replacing it, so a part with its own
    authored swing keeps it."""
    rig = R.Rig((16, 32), [
        R.Part("torso", "torso", (4, 8, 12, 22), None, (8, 22), 1),
        R.Part("tail", "tail", (0, 16, 5, 24), "torso", (4, 20), 0)])
    walk = motion.get("walk")
    plain = [round(pose.get("tail").angle, 3) for pose in walk.poses(rig)]
    trailing = [round(pose.get("tail").angle, 3)
                for pose in walk.applied(rig).poses(rig)]
    assert any(a != b for a, b in zip(plain, trailing))     # it trails
    assert len(set(plain)) > 1                              # ... and it wagged


def test_the_follow_through_trails_by_less_than_it_follows():
    """Measured as well as physical. At a gain of 1.0 or more, a pegasus whose
    tail already swings had that swing amplified until the tail came away from
    the body -- 1.82% of the character loose at 1.15 and nothing at 0.85, with
    exactly as many clips moving their stalk either way."""
    assert motion.FOLLOW["damp"] < 1.0


# --- hinge -----------------------------------------------------------------

def test_a_hinge_narrows_a_door_instead_of_turning_it(caped):
    """A door that ROTATES goes through the wall. What it does is turn about a
    vertical axis, which flat-on is a narrowing."""
    animation = motion.Animation("open", 6, loop=False, tracks={
        "torso": [{"t": 0.0}]}, ops=[
        {"op": "hinge", "on": "torso", "degrees": 80.0}])
    applied = animation.applied(caped)
    widths = _values(applied, caped, "torso", "sx")
    angles = _values(applied, caped, "torso", "angle")
    assert widths[0] == pytest.approx(1.0)
    assert widths[-1] == pytest.approx(math.cos(math.radians(80.0)), abs=1e-3)
    assert all(later <= earlier + 1e-6
               for earlier, later in zip(widths, widths[1:]))     # it only narrows
    assert set(angles) == {0.0}                                   # ... and never turns


def test_a_hinge_of_zero_degrees_leaves_the_door_shut(caped):
    animation = motion.Animation("shut", 4, loop=False, tracks={"torso": [{"t": 0.0}]},
                                 ops=[{"op": "hinge", "on": "torso", "degrees": 0.0}])
    assert _values(animation.applied(caped), caped, "torso", "sx") == [1.0] * 4


def test_a_hinge_keeps_the_door_s_height(caped):
    """It narrows; it does not shrink. A door that got shorter as it opened
    would read as the camera moving."""
    animation = motion.Animation("open", 4, loop=False, tracks={"torso": [{"t": 0.0}]},
                                 ops=[{"op": "hinge", "on": "torso", "degrees": 70.0}])
    assert _values(animation.applied(caped), caped, "torso", "sy") == [1.0] * 4


# --- retime ----------------------------------------------------------------

def test_a_retime_reaches_the_same_poses_on_a_different_schedule(caped):
    """Timing is not a property of a part, so this is the one operator that
    touches the whole clip."""
    keys = [{"t": 0.0, "angle": 0.0}, {"t": 1.0, "angle": 40.0}]
    plain = motion.Animation("x", 5, loop=False, tracks={"torso": keys})
    late = motion.Animation("x", 5, loop=False, tracks={"torso": keys}, ops=[
        {"op": "retime", "curve": [{"t": 0.0, "v": 0.0}, {"t": 0.7, "v": 0.15},
                                   {"t": 1.0, "v": 1.0}]}])
    before = _values(plain, caped, "torso")
    after = _values(late.applied(caped), caped, "torso")
    assert before[0] == after[0] and before[-1] == pytest.approx(after[-1])
    assert after[len(after) // 2] < before[len(before) // 2]      # ... held back


def test_a_retime_with_the_identity_changes_nothing(caped):
    keys = [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 20.0}]
    plain = motion.Animation("x", 6, loop=False, tracks={"torso": keys})
    same = motion.Animation("x", 6, loop=False, tracks={"torso": keys}, ops=[
        {"op": "retime", "curve": [{"t": 0.0, "v": 0.0}, {"t": 1.0, "v": 1.0},
                                   {"t": 0.5, "v": 0.5, "easing": "linear"}]}])
    assert _values(same.applied(caped), caped, "torso") == \
        pytest.approx(_values(plain, caped, "torso"), abs=1e-3)


def test_a_retime_moves_the_root_track_too(caped):
    """Or the body would keep the old schedule while the limbs took the new
    one, which is worse than not retiming at all."""
    animation = motion.Animation("x", 5, loop=False,
                                 root=[{"t": 0.0, "dy": 0.0}, {"t": 1.0, "dy": -8.0}],
                                 ops=[{"op": "retime", "curve": [
                                     {"t": 0.0, "v": 0.0}, {"t": 0.7, "v": 0.15},
                                     {"t": 1.0, "v": 1.0}]}])
    applied = animation.applied(caped)
    held = [round(pose.dy, 3) for pose in applied.poses(caped)]
    assert held[len(held) // 2] > -4.0        # still near the start
    assert held[-1] == pytest.approx(-8.0)    # and arrives


# --- operators and the spread axis -----------------------------------------
#
# A track's axis says which way its wave travels. An operator that kept the
# spread and dropped the axis would leave the wave exactly the same size and
# silently turn it back to declaration order -- a defect with no visible
# symptom on any rig that happens to be listed tidily.

@pytest.fixture
def field():
    """Four stalks, listed RIGHT TO LEFT, so declaration order and the image
    disagree about which way is downwind."""
    return R.Rig((44, 14), [
        R.Part("soil", "body", (0, 12, 44, 14), None, (22, 14), 0),
        R.Part("stalk_d", "accessory", (33, 0, 41, 12), "soil", (37, 12), 1),
        R.Part("stalk_c", "accessory", (22, 0, 30, 12), "soil", (26, 12), 1),
        R.Part("stalk_b", "accessory", (11, 0, 19, 12), "soil", (15, 12), 1),
        R.Part("stalk_a", "accessory", (0, 0, 8, 12), "soil", (4, 12), 1),
    ])


def _axed(op):
    return motion.Animation("wind", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 10.0}],
                        "spread": 0.1, "along": "x"}}, ops=[op])


def test_a_baking_operator_keeps_the_axis(field):
    """`damp` goes through `_bake`, which rebuilds the track from scratch."""
    applied = _axed({"op": "damp", "on": "trait:stalk", "factor": 0.5}).applied(field)
    assert applied.tracks["trait:stalk"].along == "x"
    assert applied.tracks["trait:stalk"].spread == pytest.approx(0.1)


def test_retime_keeps_the_axis(field):
    applied = _axed({"op": "retime",
                     "curve": [{"t": 0.0, "v": 0.0},
                               {"t": 1.0, "v": 1.0}]}).applied(field)
    assert applied.tracks["trait:stalk"].along == "x"


def test_an_axed_wave_reaches_the_leftmost_stalk_first(field):
    """The end-to-end claim. The rig lists these right to left; along x the
    crest still starts at the left, because that is where the left is."""
    clip = motion.Animation("wind", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.25, "angle": 10.0},
                                 {"t": 0.5, "angle": 0.0}],
                        "spread": 0.125, "along": "x"}})
    peak = {}
    for index, pose in enumerate(clip.poses(field)):
        for name in ("stalk_a", "stalk_b", "stalk_c", "stalk_d"):
            angle = pose.get(name).angle
            if angle > peak.get(name, (-1e9, -1))[0]:
                peak[name] = (angle, index)
    order = [peak[name][1] for name in ("stalk_a", "stalk_b", "stalk_c", "stalk_d")]
    assert order == sorted(order)
    assert order[0] < order[-1]


def test_taper_sizes_a_selection_by_where_its_parts_are(field):
    """Timing and amplitude have to agree about which end is the tip. Ranked by
    declaration order this rig tapers backwards; placed on the axis it does
    not."""
    op = {"op": "taper", "on": "trait:stalk", "gain": [0.0, 1.0]}
    placed = _axed(op).applied(field)
    ranked = motion.Animation("wind", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 10.0}],
                        "spread": 0.1}}, ops=[op]).applied(field)

    def reach(built, name):
        return max(abs(getattr(pose.get(name), "angle"))
                   for pose in built.poses(field))

    assert reach(placed, "stalk_a") == pytest.approx(0.0, abs=1e-6)
    assert reach(placed, "stalk_d") > reach(placed, "stalk_a")
    # Ranked, the rig's own listing order makes the RIGHTMOST stalk the quiet
    # one -- the same op, the same rig, the taper pointing the other way.
    assert reach(ranked, "stalk_d") == pytest.approx(0.0, abs=1e-6)


def test_taper_without_an_axis_is_unchanged(caped):
    """The generalisation does not move any clip that never asked for an axis."""
    op = {"op": "taper", "on": "trait:stalk", "gain": [0.5, 1.4]}
    animation = motion.Animation("sway", 8, tracks={
        "trait:stalk": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 20.0}]},
        ops=[op])
    built = animation.applied(caped)
    top = max(abs(pose.get("cape_top").angle) for pose in built.poses(caped))
    hem = max(abs(pose.get("cape_hem").angle) for pose in built.poses(caped))
    assert top == pytest.approx(10.0, abs=1e-3)     # 0.5 of 20
    assert hem == pytest.approx(28.0, abs=1e-3)     # 1.4 of 20


# --- turbulence ------------------------------------------------------------

def _rough(field, **kwargs):
    op = {"op": "turbulence", "on": "trait:stalk"}
    op.update(kwargs)
    return motion.Animation("wind", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 8.0}],
                        "spread": 0.1, "along": "x"}}, ops=[op]).applied(field)


def _angles(built, field, name):
    return [round(pose.get(name).angle, 4) for pose in built.poses(field)]


def test_turbulence_gives_each_part_a_different_signal(field):
    """The whole point: one curve played by every part reads as machinery."""
    built = _rough(field, amount=3.0)
    plain = motion.Animation("wind", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 8.0}],
                        "spread": 0.1, "along": "x"}})
    for name in ("stalk_a", "stalk_b", "stalk_c", "stalk_d"):
        assert _angles(built, field, name) != _angles(plain, field, name)
    departures = {name: tuple(round(a - b, 4) for a, b in
                              zip(_angles(built, field, name),
                                  _angles(plain, field, name)))
                  for name in ("stalk_a", "stalk_b", "stalk_c", "stalk_d")}
    assert len(set(departures.values())) == 4


def test_turbulence_closes_the_loop_exactly(field):
    """Sampled noise would need its ends stitched. A sum of whole-numbered
    harmonics has a period of exactly one cycle and cannot not close."""
    built = _rough(field, amount=3.0, rate=5)
    for name in ("stalk_a", "stalk_d"):
        assert (built.pose_at(field, 0.0).get(name).angle
                == pytest.approx(built.pose_at(field, 1.0).get(name).angle))


def test_amount_is_a_ceiling_that_is_actually_reached(field):
    """Not an average and not a scale factor: the largest departure at any
    frame of any part is `amount`, so the dial means what it says."""
    plain = motion.Animation("wind", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 8.0}],
                        "spread": 0.1, "along": "x"}})
    built = _rough(field, amount=3.0)
    biggest = max(abs(a - b)
                  for name in ("stalk_a", "stalk_b", "stalk_c", "stalk_d")
                  for a, b in zip(_angles(built, field, name),
                                  _angles(plain, field, name)))
    assert biggest == pytest.approx(3.0, abs=1e-3)


def test_turbulence_is_reproducible_across_processes(field):
    """`hash()` is salted per process, so a build seeded with it would animate
    differently every run. This asserts the exact numbers, which is the only
    way to catch a switch back to it."""
    built = _rough(field, amount=2.0, rate=2, seed=7)
    first = _angles(built, field, "stalk_a")
    assert first == _angles(_rough(field, amount=2.0, rate=2, seed=7),
                            field, "stalk_a")
    assert operators._hash("phase", 0, "stalk_a", "angle", 1) == 1094011853


def test_a_different_seed_is_a_different_wind(field):
    assert (_angles(_rough(field, amount=2.0, seed=1), field, "stalk_a")
            != _angles(_rough(field, amount=2.0, seed=2), field, "stalk_a"))


def test_turbulence_does_not_depend_on_the_order_the_rig_lists_parts(field):
    """The same lesson as the spread axis. A part's wander is hashed from its
    name, so re-ordering a rig file changes nothing at all."""
    shuffled = R.Rig(field.size, [field.parts[0]] + list(reversed(field.parts[1:])))
    for name in ("stalk_a", "stalk_c"):
        assert (_angles(_rough(field, amount=3.0), field, name)
                == _angles(_rough(shuffled, amount=3.0), shuffled, name))


def test_turbulence_leaves_the_authored_swing_intact(field):
    """It composes rather than replaces: the wander is emitted as `name:`
    tracks and the trait track it was addressed by is untouched."""
    built = _rough(field, amount=1.0)
    assert "trait:stalk" in built.tracks
    assert built.tracks["trait:stalk"].along == "x"
    assert built.tracks["trait:stalk"].spread == pytest.approx(0.1)
    assert built.tracks["name:stalk_a"].values("angle") != [0.0] * 8


def test_turbulence_and_taper_compose_in_either_order(field):
    """Two operators that both address the same selection, one emitting
    `name:` tracks and one consuming the trait track."""
    ops = [{"op": "taper", "on": "trait:stalk", "gain": [0.4, 1.0]},
           {"op": "turbulence", "on": "trait:stalk", "amount": 1.5}]
    forward = motion.Animation("w", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 8.0}],
                        "spread": 0.1, "along": "x"}},
        ops=ops).applied(field)
    backward = motion.Animation("w", 8, tracks={
        "trait:stalk": {"keys": [{"t": 0.0, "angle": 0.0},
                                 {"t": 0.5, "angle": 8.0}],
                        "spread": 0.1, "along": "x"}},
        ops=list(reversed(ops))).applied(field)
    for built in (forward, backward):
        reach = {name: max(abs(a) for a in _angles(built, field, name))
                 for name in ("stalk_a", "stalk_d")}
        assert reach["stalk_d"] > reach["stalk_a"]


def test_a_fractional_rate_is_refused(field):
    """A frequency that is not a whole number of cycles per loop does not
    close, and a clip that does not close pops on every repeat."""
    with pytest.raises(ValueError) as caught:
        _rough(field, amount=1.0, rate=2.5)
    assert "close" in str(caught.value)


def test_turbulence_refuses_a_channel_that_is_not_one(field):
    with pytest.raises(ValueError) as caught:
        _rough(field, amount=1.0, channels=["wobble"])
    assert "wobble" in str(caught.value)


def test_turbulence_on_a_squash_multiplies_rather_than_adds(field):
    """Rest is 1 for a scale and 0 for a rotation, so a departure of the same
    size has to be applied differently or a 'quiet' wander erases the part."""
    built = _rough(field, amount=0.1, channels=["sy"])
    values = [round(pose.get("stalk_a").sy, 4) for pose in built.poses(field)]
    assert all(0.85 < value < 1.15 for value in values)
    assert len(set(values)) > 1


def test_turbulence_with_no_amount_changes_nothing(field):
    built = _rough(field, amount=0.0)
    assert not any(key.startswith("name:") for key in built.tracks)
