"""Damping exactly the part that came apart, and no more."""

import numpy as np
import pytest

import make_fixture
from spritepipe import (cutout, image, ingest, motion, quality, render, repair,
                        rig as R, vision)


def flailing():
    """A character, a rig, and a clip that measurably throws an arm off.

    Built by hand rather than taken from the silhouette rigger, because the
    rigger is meant to keep getting better at not doing this -- and every time
    it does, a test that leaned on one of its mistakes goes green for the wrong
    reason and then red for the wrong reason. The defect here is stated
    outright: `arm_near`'s pivot is at the character's opposite corner, so the arm
    is on a lever as long as the character is tall, and sixteen degrees of swing
    carries it clear of the body where eight does not.

    Returns (pixels, rig, cutout, animation).
    """
    art = np.zeros((16, 10, 4), dtype=np.uint8)
    art[0:12, 2:8] = (80, 110, 160, 255)        # body
    art[4:14, 8:10] = (200, 150, 110, 255)      # a long thin arm down one side
    parts = [R.Part("torso", "torso", (0, 0, 8, 16), None, (4, 12), z=1),
             R.Part("arm_near", "arm_near", (8, 4, 10, 14), "torso", (2, 15), z=2),
             R.Part("arm_far", "arm_far", (8, 4, 10, 14), "torso", (2, 15), z=0)]
    built = R.Rig((10, 16), parts, "humanoid", "right", anchor=(5, 16))
    swing = motion.Animation(
        "swing", frames=4,
        tracks={"arm_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 40.0},
                             {"t": 1.0, "angle": 0.0}],
                "leg_near": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 5.0},
                             {"t": 1.0, "angle": 0.0}]})
    return art, built, cutout.cut(built, art), swing


def whole_character():
    """One connected blob that holds together, for the cases about doing nothing."""
    return make_fixture.humanoid(arms_clear=False)


def rigged(pixels, **kwargs):
    reference = ingest.Reference(pixels, image.unique_colors(pixels), 1,
                                 (pixels.shape[1], pixels.shape[0]), {})
    built = vision.TemplateBackend().rig(reference, **kwargs)
    return built, cutout.cut(built, pixels)


def rendered(cut, built, animation):
    margin = render.suggest_margin(built)
    return render.render_sequence(cut, animation.poses(built), margin=margin), margin


# -- the parts ------------------------------------------------------------

def test_damp_scales_only_the_named_roles_rotation():
    walk = motion.get("walk")
    damped = repair.damp(walk, ["arm_near"], 0.5)
    assert damped.tracks["arm_near"].keys[1]["angle"] \
        == pytest.approx(walk.tracks["arm_near"].keys[1]["angle"] * 0.5)
    assert damped.tracks["leg_near"].to_list() == walk.tracks["leg_near"].to_list()


def test_damp_leaves_translation_and_squash_alone():
    """A translation moves a part without changing its shape and cannot shear it
    off; a squash is floored elsewhere. It is the swing that throws a limb clear."""
    run = motion.get("run")
    damped = repair.damp(run, ["leg_near"], 0.5)
    for before, after in zip(run.tracks["leg_near"].keys, damped.tracks["leg_near"].keys):
        assert after.get("sy") == before.get("sy")
        assert after.get("dy") == before.get("dy")


def test_damp_does_not_mutate_the_library():
    before = motion.get("walk").tracks["arm_near"].to_list()
    repair.damp(motion.get("walk"), ["arm_near"], 0.1)
    assert motion.get("walk").tracks["arm_near"].to_list() == before


def test_damp_ignores_a_role_the_clip_does_not_drive():
    walk = motion.get("walk")
    assert repair.damp(walk, ["wing_near"], 0.5).to_dict() == walk.to_dict()


def test_blame_names_the_part_whose_pixels_came_away():
    art, built, cut, swing = flailing()
    margin = render.suggest_margin(built)
    frames = render.render_sequence(cut, swing.poses(built), margin=margin)
    shed, index = quality.shed(frames, art)
    assert shed > repair.TOLERANCE, "the fixture is meant to come apart here"
    assert repair.blame(cut, built, swing.poses(built)[index], margin, render) \
        == ["arm_near"]


def test_blame_is_empty_when_the_character_is_whole():
    built, cut = rigged(whole_character())
    margin = render.suggest_margin(built)
    pose = motion.get("idle").poses(built)[0]
    assert repair.blame(cut, built, pose, margin, render) == []


# -- the repair itself ----------------------------------------------------

def test_a_whole_clip_is_handed_back_untouched():
    built, cut = rigged(whole_character())
    walk = motion.get("idle")
    frames, margin = rendered(cut, built, walk)
    again, back, note = repair.repair(cut, built, walk, frames,
                                      whole_character(), margin, render)
    assert note is None
    assert again is walk and back is frames


def test_a_broken_clip_is_damped_until_it_holds_together():
    art, built, cut, swing = flailing()
    margin = render.suggest_margin(built)
    frames = render.render_sequence(cut, swing.poses(built), margin=margin)
    before, _ = quality.shed(frames, art)
    assert before > repair.TOLERANCE

    fixed, after_frames, note = repair.repair(cut, built, swing, frames, art,
                                              margin, render)
    after, _ = quality.shed(after_frames, art)
    assert after <= repair.TOLERANCE and after < before
    assert note and "reduced to" in note and "arm_near" in note
    assert len(after_frames) == len(frames)


def test_the_repair_only_damps_what_it_blamed():
    art, built, cut, swing = flailing()
    margin = render.suggest_margin(built)
    frames = render.render_sequence(cut, swing.poses(built), margin=margin)
    fixed, _, _ = repair.repair(cut, built, swing, frames, art, margin, render)
    assert fixed.tracks["leg_near"].to_list() == swing.tracks["leg_near"].to_list()
    assert fixed.tracks["arm_near"].keys[1]["angle"] < 40.0


def test_a_clip_that_damping_cannot_save_says_so_and_changes_nothing():
    """A rig this far out needs a better rig, not less motion, and shipping a
    quieter version of a broken clip would hide that."""
    art, built, cut, swing = flailing()
    margin = render.suggest_margin(built)
    frames = render.render_sequence(cut, swing.poses(built), margin=margin)
    again, back, note = repair.repair(cut, built, swing, frames, art, margin,
                                      render, steps=())
    assert note and "does not put it back together" in note
    assert again is swing and back is frames


def _flask():
    """A wide bowl joined to a wide cap by a neck one pixel across."""
    art = np.zeros((12, 9, 4), dtype=np.uint8)
    art[6:12, 1:8] = (200, 60, 60, 255)
    art[3:6, 4:5] = (180, 180, 190, 255)
    art[1:3, 2:7] = (180, 180, 190, 255)
    return art


def test_a_squashed_flask_no_longer_comes_apart_at_all():
    """It used to: the neck is the first thing to go, so the cap came away while
    nothing had rotated. `render._reconnect` repairs that where it happens, at
    the reduction, so there is nothing left here to repair."""
    flask = _flask()
    built, cut = rigged(flask, character_class="prop")
    margin = render.suggest_margin(built)
    spin = motion.Animation(
        "spin", frames=8,
        root=[{"t": 0.0, "sx": 1.0}, {"t": 0.25, "sx": 0.4},
              {"t": 0.5, "sx": 1.0}, {"t": 0.75, "sx": 0.4}, {"t": 1.0, "sx": 1.0}])
    frames = render.render_sequence(cut, spin.poses(built), margin=margin)
    assert quality.shed(frames, flask)[0] <= repair.TOLERANCE

    again, back, note = repair.repair(cut, built, spin, frames, flask, margin, render)
    assert note is None and again is spin and back is frames


def test_a_clip_pulled_apart_by_something_that_is_not_a_swing_says_so():
    """Two parts driven apart by a translation. Nothing swings them there, so
    saying "damping did not help" would point the reader at the wrong thing."""
    art = np.zeros((14, 10, 4), dtype=np.uint8)
    art[4:14, 2:8] = (80, 110, 160, 255)     # body
    art[0:4, 3:7] = (220, 200, 90, 255)      # a cap sitting on it
    parts = [R.Part("body", "body", (0, 4, 10, 14), None, (5, 14)),
             R.Part("cap", "accessory", (0, 0, 10, 4), "body", (5, 4))]
    built = R.Rig((10, 14), parts, "prop", "right", anchor=(5, 14))
    cut = cutout.cut(built, art)
    margin = render.suggest_margin(built)
    lift = motion.Animation("lift", frames=4, tracks={
        "accessory": [{"t": 0.0, "dy": 0.0}, {"t": 0.5, "dy": -6.0},
                      {"t": 1.0, "dy": 0.0}]})
    frames = render.render_sequence(cut, lift.poses(built), margin=margin)
    assert quality.shed(frames, art)[0] > repair.TOLERANCE

    _, back, note = repair.repair(cut, built, lift, frames, art, margin, render)
    assert note and "which damping cannot fix" in note
    assert "accessory" in note
    assert back is frames


def test_every_failure_message_names_the_parts_it_is_talking_about():
    """Both messages tell the user where to look, and it is a different list in
    each: the not-a-swing message names what came away, the damping one names
    what was swung."""
    art, built, cut, swing = flailing()
    margin = render.suggest_margin(built)
    frames = render.render_sequence(cut, swing.poses(built), margin=margin)
    _, _, gave_up = repair.repair(cut, built, swing, frames, art, margin, render,
                                  steps=())
    assert "arm_near" in gave_up
