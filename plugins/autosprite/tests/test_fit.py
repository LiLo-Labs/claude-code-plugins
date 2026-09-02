"""Solving a rig pose from a target silhouette, and the motion that falls out.

The point of this module is that a generated animation contributes a table of
angles and nothing else -- no pixels. So the tests are about whether the solve
finds a pose it was given, whether it degrades honestly when it cannot, and
whether what comes back is a reusable clip.
"""

import numpy as np
import pytest

import make_fixture
from spritepipe import cutout, fit, image, ingest, motion, render, skeleton, vision


def rigged():
    art = image.trim(make_fixture.humanoid())[0]
    reference = ingest.Reference(art, image.unique_colors(art), 1,
                                 (art.shape[1], art.shape[0]), {})
    rig = vision.TemplateBackend().rig(reference)
    return rig, cutout.cut(rig, art)


def silhouette(cut, pose, margin):
    return image.alpha_mask(render.render_pose(cut, pose, margin=margin))


# -- the score -------------------------------------------------------------

def test_agreement_is_one_for_identical_silhouettes():
    mask = np.zeros((8, 8), dtype=bool)
    mask[2:6, 2:6] = True
    assert fit.agreement(mask, mask) == 1.0


def test_agreement_is_zero_for_disjoint_silhouettes():
    a = np.zeros((8, 8), dtype=bool); a[0:3, 0:3] = True
    b = np.zeros((8, 8), dtype=bool); b[5:8, 5:8] = True
    assert fit.agreement(a, b) == 0.0


def test_agreement_of_two_empties_is_one_rather_than_a_division_by_zero():
    empty = np.zeros((4, 4), dtype=bool)
    assert fit.agreement(empty, empty) == 1.0


def test_agreement_punishes_a_silhouette_that_is_merely_bigger():
    """Intersection over UNION, not intersection over the target. Otherwise a
    pose that covers everything scores perfectly by covering everything."""
    small = np.zeros((10, 10), dtype=bool); small[4:6, 4:6] = True
    big = np.ones((10, 10), dtype=bool)
    assert fit.agreement(big, small) < 0.1


# -- solving a pose --------------------------------------------------------

def test_the_rest_pose_is_recovered_from_the_rest_silhouette():
    rig, cut = rigged()
    margin = render.suggest_margin(rig)
    target = silhouette(cut, skeleton.Pose(), margin)
    pose, score = fit.fit_pose(cut, target, margin, passes=((5, 1.0),))
    assert score > 0.98
    assert silhouette(cut, pose, margin).sum() > 0


def test_a_posed_silhouette_is_recovered_better_than_rest_explains_it():
    """The solve has to actually move something. A rig that returns rest for
    every frame scores well on a nearly-still clip and animates nothing."""
    rig, cut = rigged()
    margin = render.suggest_margin(rig)
    wanted = skeleton.Pose()
    for part in rig.parts:
        if part.role.startswith("leg"):
            wanted.set(part.name, skeleton.PartPose(angle=22.0))
    target = silhouette(cut, wanted, margin)
    rest_score = fit.agreement(silhouette(cut, skeleton.Pose(), margin), target)
    _pose, score = fit.fit_pose(cut, target, margin, passes=((7, 1.0), (5, 0.3)))
    assert score > rest_score, "the solve did no better than not solving"
    assert score > 0.9


def test_the_search_leaves_the_renderer_as_it_found_it():
    """Skinning is switched off during the search for speed and must come back,
    or every frame drawn after a fit silently loses it."""
    rig, cut = rigged()
    margin = render.suggest_margin(rig)
    target = silhouette(cut, skeleton.Pose(), margin)
    before = render.SKIN
    fit.fit_pose(cut, target, margin, passes=((3, 1.0),))
    assert render.SKIN is before


# -- a clip ----------------------------------------------------------------

def test_a_clip_returns_one_pose_and_score_per_target():
    rig, cut = rigged()
    margin = render.suggest_margin(rig)
    targets = [silhouette(cut, skeleton.Pose(), margin) for _ in range(3)]
    fitted = fit.fit_clip(cut, targets, margin=margin, passes=((3, 1.0),))
    assert len(fitted) == 3
    assert all(0.0 <= score <= 1.0 for _pose, score in fitted)


def test_a_solved_clip_becomes_an_animation_the_library_would_accept():
    """The artefact worth keeping: a solved walk is a table of angles like any
    hand-authored clip, and has to validate like one."""
    rig, cut = rigged()
    margin = render.suggest_margin(rig)
    poses = []
    for angle in (0.0, 14.0, 0.0, -14.0):
        pose = skeleton.Pose()
        for part in rig.parts:
            if part.role.startswith("leg"):
                pose.set(part.name, skeleton.PartPose(angle=angle))
        poses.append((pose, 1.0))
    clip = fit.to_animation(poses, "solved-walk", fps=12)
    assert clip.name == "solved-walk"
    assert clip.frames == 4 and clip.fps == 12
    assert motion.validate_animation(clip.to_dict()) == []


def test_a_channel_that_never_leaves_rest_is_not_written_out():
    """A solved clip should read as what it is, not as a wall of zeroes."""
    rig, cut = rigged()
    poses = []
    for angle in (0.0, 10.0):
        pose = skeleton.Pose()
        pose.set(rig.parts[0].name, skeleton.PartPose(angle=angle))
        poses.append((pose, 1.0))
    clip = fit.to_animation(poses, "x")
    for track in clip.tracks.values():
        for key in track.to_list():
            assert "sx" not in key and "sy" not in key


def test_a_clip_solved_with_a_rig_is_keyed_by_role_so_it_transfers():
    """The reason to keep a solved clip: keyed by role it drives every other
    character, keyed by part name it only ever drives the one it came from."""
    rig, cut = rigged()
    leg = next(p for p in rig.parts if p.role.startswith("leg"))
    poses = []
    for angle in (0.0, 12.0):
        pose = skeleton.Pose()
        pose.set(leg.name, skeleton.PartPose(angle=angle))
        poses.append((pose, 1.0))
    named = fit.to_animation(poses, "x")
    roled = fit.to_animation(poses, "x", rig=rig)
    assert leg.name in named.tracks
    assert leg.role in roled.tracks


def test_no_fitted_poses_is_an_error_rather_than_an_empty_animation():
    with pytest.raises(ValueError):
        fit.to_animation([], "nothing")


# -- the rig learning where it needs a joint -------------------------------

def test_only_the_frames_the_rig_could_not_reach_are_reported():
    fitted = [(None, 1.0), (None, 0.95), (None, 0.51), (None, 0.39)]
    assert fit.unreached(fitted, floor=0.7) == [3, 2]


def test_a_clip_the_rig_can_express_reports_nothing_to_fix():
    assert fit.unreached([(None, 0.99), (None, 0.95)], floor=0.7) == []


def test_splitting_a_limb_makes_two_segments_end_to_end():
    rig, _cut = rigged()
    leg = next(p for p in rig.parts if p.role.startswith("leg"))
    grown = fit.split_part(rig, leg.name, 0.5)
    upper = grown.by_name(leg.name)
    lower = grown.by_name(leg.name + "_lower")
    assert upper is not None and lower is not None
    assert upper.parent == leg.parent
    assert lower.parent == leg.name, "the lower segment hangs off the upper"
    # end to end down the limb's own long axis, covering the original
    assert upper.box[1] == leg.box[1] and lower.box[3] == leg.box[3]
    assert upper.box[3] == lower.box[1]


def test_a_split_limb_keeps_the_rig_valid_and_still_cuts():
    from spritepipe import rig as R
    rig, _cut = rigged()
    arm = next(p for p in rig.parts if p.role.startswith("arm"))
    grown = fit.split_part(rig, arm.name, 0.5)
    assert R.validate(grown) == [], R.validate(grown)
    art = image.trim(make_fixture.humanoid())[0]
    pieces = cutout.cut(grown, art)
    assert image.equal(pieces.rest(), art), "REST must survive a new joint"


def test_a_part_too_short_to_bend_is_refused():
    """A two-pixel mitten has nowhere to put a joint, and a one-pixel bone fits
    noise rather than anatomy."""
    from spritepipe import rig as R
    tiny = R.Rig((10, 10), [
        R.Part("body", "torso", (0, 0, 10, 10), None, (5, 10)),
        R.Part("nub", "arm_near", (8, 4, 10, 6), "body", (8, 4)),
    ])
    assert fit.split_part(tiny, "nub", 0.5) is None


def test_whatever_hung_off_a_limb_moves_to_its_free_end():
    """A sword rides the hand. Left on the upper segment it stays pinned to the
    shoulder while the arm bends away from it."""
    from spritepipe import rig as R
    built = R.Rig((20, 20), [
        R.Part("torso", "torso", (5, 2, 15, 12), None, (10, 12)),
        R.Part("arm_near", "arm_near", (14, 3, 18, 13), "torso", (15, 4)),
        # Both halves: paired limbs animate in counter-phase, and a rig with one
        # of a pair is refused before it ever reaches the splitter.
        R.Part("arm_far", "arm_far", (2, 3, 6, 13), "torso", (5, 4)),
        R.Part("sword", "prop", (17, 6, 20, 10), "arm_near", (18, 8)),
    ])
    grown = fit.split_part(built, "arm_near", 0.5)
    assert grown.by_name("sword").parent == "arm_near_lower"
    assert R.validate(grown) == []


# -- what a part is allowed to do ------------------------------------------

def test_a_head_may_not_turn_as_far_as_an_arm():
    from spritepipe import rig as R
    head = R.Part("head", "head", (0, 0, 4, 4), "torso", (2, 4))
    arm = R.Part("arm_near", "arm_near", (0, 0, 4, 4), "torso", (2, 0))
    assert fit.limit_for(head) < fit.limit_for(arm)


def test_an_unknown_role_still_gets_a_limit():
    from spritepipe import rig as R
    odd = R.Part("thing", "gizmo", (0, 0, 4, 4), "torso", (2, 2))
    assert fit.limit_for(odd) == fit.DEFAULT_LIMIT


def test_effort_is_zero_at_rest_and_rises_with_departure():
    rig, _cut = rigged()
    at_rest = skeleton.Pose()
    assert fit.effort(rig, at_rest) == 0.0
    moved = skeleton.Pose()
    part = next(p for p in rig.parts if p.role.startswith("leg"))
    moved.set(part.name, skeleton.PartPose(angle=30.0))
    assert fit.effort(rig, moved) > 0.0


def test_effort_is_scaled_by_each_parts_own_limit():
    """A leg swinging most of its allowance is not more extravagant than a head
    turning most of its much smaller one."""
    rig, _cut = rigged()
    head = next(p for p in rig.parts if p.role == "head")
    leg = next(p for p in rig.parts if p.role.startswith("leg"))
    a, b = skeleton.Pose(), skeleton.Pose()
    a.set(head.name, skeleton.PartPose(angle=fit.limit_for(head)))
    b.set(leg.name, skeleton.PartPose(angle=fit.limit_for(leg)))
    assert fit.effort(rig, a) == pytest.approx(fit.effort(rig, b), abs=1e-9)


def test_the_solve_never_turns_a_part_past_its_limit():
    """Unpenalised, the solve rotates whatever part buys the most overlap -- the
    biggest one. Fitting an exaggerated walk it turned the corpus knight's HEAD
    forty degrees and smeared it across the chest, which fits at 0.78 and is not
    a walk."""
    rig, cut = rigged()
    margin = render.suggest_margin(rig)
    wanted = skeleton.Pose()
    for part in rig.parts:
        if part.role.startswith("leg"):
            wanted.set(part.name, skeleton.PartPose(angle=40.0))
    target = silhouette(cut, wanted, margin)
    pose, _score = fit.fit_pose(cut, target, margin, passes=((7, 1.0),))
    for part in rig.parts:
        own = pose.parts.get(part.name)
        if own is not None:
            assert abs(own.angle) <= fit.limit_for(part) + 1e-6, part.name


def test_the_reported_score_is_the_raw_agreement_not_the_penalised_one():
    """Tidiness steers the search. A caller reading the fit as a rig diagnostic
    needs the silhouette number, not the number minus a housekeeping charge."""
    rig, cut = rigged()
    margin = render.suggest_margin(rig)
    target = silhouette(cut, skeleton.Pose(), margin)
    pose, score = fit.fit_pose(cut, target, margin, passes=((3, 1.0),))
    assert score == pytest.approx(
        fit.agreement(silhouette(cut, pose, margin), target), abs=1e-9)
