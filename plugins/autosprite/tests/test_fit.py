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
