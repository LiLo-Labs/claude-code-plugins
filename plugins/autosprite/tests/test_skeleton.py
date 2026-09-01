"""Forward kinematics, with no pixels involved."""

import numpy as np
import pytest

from spritepipe import rig as R, skeleton


@pytest.fixture
def chain():
    return R.Rig((20, 20), [
        R.Part("root", "torso", (5, 10, 15, 20), None, (10, 20)),
        R.Part("mid", "head", (7, 5, 13, 10), "root", (10, 10)),
        R.Part("tip", "accessory", (9, 0, 11, 5), "mid", (10, 5)),
    ])


def test_the_identity_pose_is_the_identity(chain):
    for matrix in skeleton.world_transforms(chain, skeleton.Pose()).values():
        assert np.allclose(matrix, np.eye(3))


def test_a_part_rotates_about_its_own_pivot(chain):
    pose = skeleton.Pose({"mid": skeleton.PartPose(angle=90)})
    matrix = skeleton.world_transforms(chain, pose)["mid"]
    assert skeleton.apply_point(matrix, (10, 10)) == pytest.approx((10, 10))


def test_a_child_inherits_its_parent_and_composes(chain):
    pose = skeleton.Pose({"root": skeleton.PartPose(angle=90),
                          "mid": skeleton.PartPose(angle=90)})
    transforms = skeleton.world_transforms(chain, pose)
    # The tip's pivot travels through both rotations, so it is 180 degrees about
    # the root's pivot from where a single rotation would leave it.
    straight = skeleton.apply_point(transforms["root"], (10, 5))
    both = skeleton.apply_point(transforms["tip"], (10, 5))
    assert straight != pytest.approx(both)


def test_the_root_shift_moves_everything(chain):
    transforms = skeleton.world_transforms(chain, skeleton.Pose(dx=4, dy=-2))
    for name in ("root", "mid", "tip"):
        assert skeleton.apply_point(transforms[name], (0, 0)) == pytest.approx((4, -2))


def test_a_clockwise_positive_angle_swings_a_hand_backwards():
    """Screen y points down, so this convention is not the maths one."""
    matrix = skeleton.local(skeleton.PartPose(angle=90), (0, 0))
    x, y = skeleton.apply_point(matrix, (0, 10))    # a limb hanging down
    assert x < -1 and abs(y) < 1e-6


def test_blend_interpolates_every_channel():
    left = skeleton.PartPose(angle=0, dx=0, sx=1.0)
    right = skeleton.PartPose(angle=10, dx=4, sx=2.0)
    middle = left.blend(right, 0.5)
    assert (middle.angle, middle.dx, middle.sx) == pytest.approx((5.0, 2.0, 1.5))


def test_poses_blend_across_the_union_of_their_parts():
    left = skeleton.Pose({"a": skeleton.PartPose(angle=0)})
    right = skeleton.Pose({"b": skeleton.PartPose(angle=20)})
    blended = left.blend(right, 0.5)
    assert set(blended.parts) == {"a", "b"}
    assert blended.get("b").angle == pytest.approx(10.0)


def test_scale_is_applied_about_the_pivot_too():
    matrix = skeleton.local(skeleton.PartPose(sy=0.5), (0, 0))
    assert skeleton.apply_point(matrix, (0, 10)) == pytest.approx((0, 5))


def test_an_unposed_part_reports_rest():
    assert skeleton.Pose().get("anything").angle == 0.0


def test_a_shadow_never_moves_however_far_the_character_does():
    """A baked ground shadow is the floor drawn into the sprite. Riding the root
    lifts it off the ground at the apex of a jump and bobs it with every step,
    so the ground line pumps along with the animation."""
    parts = [R.Part("torso", "torso", (0, 0, 10, 14), None, (5, 14)),
             R.Part("shadow", "shadow", (2, 15, 8, 16), "torso", (5, 16))]
    rig = R.Rig((10, 16), parts, "humanoid", "right", anchor=(5, 16))
    pose = skeleton.Pose(dx=3.0, dy=-9.0)
    pose.set("torso", skeleton.PartPose(angle=20.0))
    transforms = skeleton.world_transforms(rig, pose)
    assert np.allclose(transforms["shadow"], np.eye(3))
    assert not np.allclose(transforms["torso"], np.eye(3))
