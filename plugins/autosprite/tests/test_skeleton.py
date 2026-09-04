"""Forward kinematics, with no pixels involved."""

import math

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


# -- a foot on the floor --------------------------------------------------

def _leg_points(rig, length=10):
    """One column of pixels down each leg, in reference coordinates."""
    points = {}
    for part in rig.parts:
        x0, y0, x1, y1 = part.box
        rows = np.arange(y0, y1)
        columns = np.full(rows.shape, (x0 + x1) // 2)
        points[part.name] = np.stack([columns, rows, np.ones(rows.shape)], axis=0)
    return points


@pytest.fixture
def stander():
    return R.Rig((12, 20), [
        R.Part("torso", "torso", (2, 0, 10, 12), None, (6, 12)),
        R.Part("leg_near", "leg_near", (6, 12, 9, 20), "torso", (7, 12)),
        R.Part("leg_far", "leg_far", (3, 12, 6, 20), "torso", (4, 12)),
    ], "humanoid", "right", anchor=(6, 20))


def test_swinging_a_rigid_leg_lifts_its_own_foot(stander):
    """The whole reason planting exists: a leg here is one rigid piece rotating
    about the hip, so a swing of t degrees lifts its foot by L(1 - cos t)."""
    points = _leg_points(stander)
    rest = skeleton.lowest_point(stander, skeleton.Pose(), points)
    swung = skeleton.Pose()
    swung.set("leg_near", skeleton.PartPose(angle=30.0))
    swung.set("leg_far", skeleton.PartPose(angle=-30.0))
    assert skeleton.lowest_point(stander, swung, points) < rest - 0.5


def test_planting_puts_every_pose_on_one_floor(stander):
    points = _leg_points(stander)
    poses = []
    for angle in (0.0, 12.0, 26.0, 12.0):
        pose = skeleton.Pose()
        pose.set("leg_near", skeleton.PartPose(angle=angle))
        pose.set("leg_far", skeleton.PartPose(angle=-angle))
        poses.append(pose)
    skeleton.plant(stander, poses, points)
    floors = [round(skeleton.lowest_point(stander, pose, points), 6) for pose in poses]
    assert len(set(floors)) == 1


def test_planting_gives_back_a_body_bob_lowest_at_contact(stander):
    """With the feet held down the body is lowest where the legs are splayed and
    highest where they pass vertically underneath -- which is the bob a walk is
    supposed to have, arrived at rather than authored."""
    points = _leg_points(stander)
    poses = []
    for angle in (26.0, 0.0):          # contact, then passing
        pose = skeleton.Pose()
        pose.set("leg_near", skeleton.PartPose(angle=angle))
        pose.set("leg_far", skeleton.PartPose(angle=-angle))
        poses.append(pose)
    skeleton.plant(stander, poses, points)
    head = lambda pose: skeleton.apply_point(
        skeleton.world_transforms(stander, pose)["torso"], (6, 0))[1]
    assert head(poses[1]) < head(poses[0])


def test_posed_leaves_an_unplanted_clip_alone(stander):
    from spritepipe import motion
    points = _leg_points(stander)
    run = motion.get("run")
    assert not run.planted
    assert [pose.dy for pose in skeleton.posed(stander, run, points)] \
        == [pose.dy for pose in run.poses(stander)]


# ---------------------------------------------------------------------------
# shear: a surface leans, it does not hinge.
# ---------------------------------------------------------------------------

def test_a_shear_moves_the_top_and_leaves_the_base_alone():
    """The difference from a rotation. A hinge turns a limb about a joint; a
    surface has no joint, and cloth pinned at its base slides above it."""
    matrix = skeleton.local(skeleton.PartPose(shear=30.0), (0, 10))
    top = matrix @ np.array([0.0, 0.0, 1.0])      # ten pixels above the pivot
    base = matrix @ np.array([0.0, 10.0, 1.0])    # at the pivot
    assert top[0] == pytest.approx(10.0 * math.tan(math.radians(30.0)))
    assert base[0] == pytest.approx(0.0)


def test_a_shear_shares_a_rotation_s_sign():
    """An author who writes 20 into either channel must get the top going the
    same way, or every clip that uses both reads as a mistake."""
    above = np.array([0.0, 0.0, 1.0])
    turned = skeleton.local(skeleton.PartPose(angle=20.0), (0, 10)) @ above
    leaned = skeleton.local(skeleton.PartPose(shear=20.0), (0, 10)) @ above
    assert turned[0] > 0 and leaned[0] > 0


def test_a_shear_of_zero_is_the_identity():
    assert np.allclose(skeleton.skew(0.0), np.eye(3))


def test_a_shear_keeps_a_part_s_height():
    """It slides rows sideways; it does not squash them. A surface that got
    shorter as it leaned would read as the camera moving."""
    matrix = skeleton.local(skeleton.PartPose(shear=25.0), (0, 10))
    top = matrix @ np.array([0.0, 0.0, 1.0])
    base = matrix @ np.array([0.0, 10.0, 1.0])
    assert (base[1] - top[1]) == pytest.approx(10.0)


def test_a_shear_blends_and_composes_like_every_other_channel():
    half = skeleton.PartPose().blend(skeleton.PartPose(shear=10.0), 0.5)
    assert half.shear == pytest.approx(5.0)
    both = skeleton.PartPose(shear=4.0).compose(skeleton.PartPose(shear=3.0))
    assert both.shear == pytest.approx(7.0)
