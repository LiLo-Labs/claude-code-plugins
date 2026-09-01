"""Damping exactly the part that came apart, and no more."""

import numpy as np
import pytest

import make_fixture
from spritepipe import (cutout, image, ingest, motion, quality, render, repair,
                        vision)


def whole_character():
    """One connected blob, so a loose pixel in a frame is this code's doing.

    The default fixture draws its arms clear of the body, which is a perfectly
    good sprite and a useless subject here: its source art is already three
    blobs, so `shed` starts forgiving and nothing can be attributed."""
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
    """This fixture's arms are carved out of a solid body rather than drawn
    clear of it, so an ordinary walk swings one of them off. That is the case
    this exists for, and it is worth having as a fixture: it is exactly what
    the silhouette rigger does to a character whose arms never separate."""
    built, cut = rigged(whole_character())
    walk = motion.get("walk")
    frames, margin = rendered(cut, built, walk)
    shed, index = quality.shed(frames, whole_character())
    assert shed > repair.TOLERANCE
    blamed = repair.blame(cut, built, walk.poses(built)[index], margin, render)
    assert blamed and any(role.startswith("arm_") for role in blamed)


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
    built, cut = rigged(whole_character())
    source = whole_character()
    thrown = repair.damp(motion.get("attack"), ["arm_near", "arm_far"], 6.0)
    frames, margin = rendered(cut, built, thrown)
    before, _ = quality.shed(frames, source)
    assert before > repair.TOLERANCE, "the fixture is meant to be broken here"

    fixed, after_frames, note = repair.repair(cut, built, thrown, frames, source,
                                              margin, render)
    after, _ = quality.shed(after_frames, source)
    assert after <= repair.TOLERANCE and after < before
    assert note and "reduced to" in note
    assert len(after_frames) == len(frames)


def test_the_repair_only_damps_what_it_blamed():
    built, cut = rigged(whole_character())
    source = whole_character()
    thrown = repair.damp(motion.get("attack"), ["arm_near", "arm_far"], 6.0)
    frames, margin = rendered(cut, built, thrown)
    fixed, _, _ = repair.repair(cut, built, thrown, frames, source, margin, render)
    assert fixed.tracks["leg_near"].to_list() == thrown.tracks["leg_near"].to_list()


def test_a_clip_that_damping_cannot_save_says_so_and_changes_nothing():
    """A rig this far out needs a better rig, not less motion, and shipping a
    quieter version of a broken clip would hide that."""
    built, cut = rigged(whole_character())
    source = whole_character()
    walk = motion.get("walk")
    frames, margin = rendered(cut, built, walk)
    again, back, note = repair.repair(cut, built, walk, frames, source, margin,
                                      render, steps=())
    assert note and "does not put it back together" in note
    assert again is walk and back is frames


def test_a_clip_pulled_apart_by_a_squash_says_that_instead():
    """The potion's spin lives entirely on the root track's sx, and a squash is
    not what this repairs -- flooring one was measured twice and reverted twice.
    Saying "damping did not help" would point the reader at the wrong thing.

    A flask is the shape that shows it: a wide bowl joined to a wide cap by a
    neck one pixel across. Squash it and the neck is the first thing to go, so
    the cap comes away while nothing has rotated at all."""
    flask = np.zeros((12, 9, 4), dtype=np.uint8)
    flask[6:12, 1:8] = (200, 60, 60, 255)      # bowl
    flask[3:6, 4:5] = (180, 180, 190, 255)     # a one-pixel neck
    flask[1:3, 2:7] = (180, 180, 190, 255)     # cap
    built, cut = rigged(flask, character_class="prop")
    margin = render.suggest_margin(built)
    spin = motion.Animation(
        "spin", frames=8,
        root=[{"t": 0.0, "sx": 1.0}, {"t": 0.25, "sx": 0.4},
              {"t": 0.5, "sx": 1.0}, {"t": 0.75, "sx": 0.4}, {"t": 1.0, "sx": 1.0}])
    frames = render.render_sequence(cut, spin.poses(built), margin=margin)
    assert quality.shed(frames, flask)[0] > repair.TOLERANCE, \
        "the flask is meant to come apart here"

    again, back, note = repair.repair(cut, built, spin, frames, flask, margin, render)
    assert note and "which damping cannot fix" in note
    assert again is spin and back is frames
