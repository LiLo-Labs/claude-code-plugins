"""Rasterising a posed rig. Nearest-neighbour, alpha-tested, colour-exact."""

import numpy as np
import pytest

from spritepipe import image, motion, render, skeleton


def test_the_identity_pose_reproduces_the_reference_exactly(hero, hero_cutout):
    assert image.equal(render.render_pose(hero_cutout, skeleton.Pose()), hero.pixels)


def test_a_margin_only_pads_and_does_not_move_the_art(hero, hero_cutout):
    framed = render.render_pose(hero_cutout, skeleton.Pose(), margin=7)
    assert framed.shape[:2] == (hero.pixels.shape[0] + 14, hero.pixels.shape[1] + 14)
    assert image.equal(image.crop(framed, (7, 7, 7 + hero.size[0], 7 + hero.size[1])),
                       hero.pixels)


@pytest.mark.parametrize("angle", [-90, -45, -7, 13, 62, 155])
def test_no_pose_invents_a_colour(hero, hero_cutout, angle):
    """The whole palette guarantee rests on this."""
    allowed = {tuple(c) for c in image.unique_colors(hero.pixels)}
    pose = skeleton.Pose({"arm_near": skeleton.PartPose(angle=angle),
                          "leg_far": skeleton.PartPose(angle=-angle, sy=0.8),
                          "head": skeleton.PartPose(angle=angle / 3.0)})
    frame = render.render_pose(hero_cutout, pose, margin=20)
    assert {tuple(c) for c in image.unique_colors(frame)} <= allowed


def test_a_posed_frame_is_not_the_rest_frame(hero_cutout):
    """A renderer that silently ignores the pose passes every other test here."""
    rest = render.render_pose(hero_cutout, skeleton.Pose(), margin=20)
    posed = render.render_pose(
        hero_cutout, skeleton.Pose({"arm_near": skeleton.PartPose(angle=-70)}), margin=20)
    assert not image.equal(rest, posed)


def test_a_child_follows_its_parent(hero_cutout):
    """Rotating the torso must carry the head; that is what FK is for."""
    head = hero_cutout.by_name("head")
    before = render.render_pose(hero_cutout, skeleton.Pose(), margin=20)
    after = render.render_pose(
        hero_cutout, skeleton.Pose({"torso": skeleton.PartPose(angle=35)}), margin=20)
    top_before = image.content_box(before)[1]
    top_after = image.content_box(after)[1]
    assert head is not None
    assert top_before != top_after


def test_flip_is_an_exact_horizontal_mirror(hero_cutout):
    plain = render.render_pose(hero_cutout, skeleton.Pose(), margin=4)
    flipped = render.render_pose(hero_cutout, skeleton.Pose(flip=True), margin=4)
    assert image.equal(flipped[:, ::-1], plain)


def test_a_whole_character_translation_moves_every_part_together(hero_cutout):
    moved = render.render_pose(hero_cutout, skeleton.Pose(dx=5, dy=-3), margin=20)
    plain = render.render_pose(hero_cutout, skeleton.Pose(), margin=20)
    box_moved, box_plain = image.content_box(moved), image.content_box(plain)
    assert box_moved[0] - box_plain[0] == 5
    assert box_moved[1] - box_plain[1] == -3


def test_alpha_is_hard_so_frames_compare_exactly(hero_cutout):
    frame = render.render_pose(
        hero_cutout, skeleton.Pose({"arm_near": skeleton.PartPose(angle=41)}), margin=20)
    assert set(np.unique(frame[:, :, 3]).tolist()) <= {0, 255}


def test_a_sequence_renders_one_frame_per_pose(hero_cutout, hero_rig):
    walk = motion.get("walk")
    frames = render.render_sequence(hero_cutout, walk.poses(hero_rig), margin=12)
    assert len(frames) == walk.frames
    assert not image.equal(frames[0], frames[len(frames) // 2])


def test_the_suggested_margin_holds_a_limb_swung_to_horizontal(hero_rig, hero_cutout):
    margin = render.suggest_margin(hero_rig)
    pose = skeleton.Pose({"arm_near": skeleton.PartPose(angle=-90),
                          "arm_far": skeleton.PartPose(angle=90)})
    frame = render.render_pose(hero_cutout, pose, margin=margin)
    box = image.content_box(frame)
    assert box[0] > 0 and box[1] > 0
    assert box[2] < frame.shape[1] and box[3] < frame.shape[0]


def test_the_inverse_affine_is_the_one_pil_wants():
    """Getting this backwards renders a plausible frame that is wrong."""
    matrix = skeleton.translate(3, 5) @ skeleton.rotate(90)
    coefficients = render._affine_coefficients(matrix)
    inverse = np.array([[coefficients[0], coefficients[1], coefficients[2]],
                        [coefficients[3], coefficients[4], coefficients[5]],
                        [0, 0, 1]])
    assert np.allclose(inverse @ matrix, np.eye(3))


# -- supersampled rotation -------------------------------------------------

def test_mode_downscale_only_ever_picks_a_colour_the_block_already_had():
    """This is the half of supersampling that keeps the palette guarantee."""
    rng = np.random.default_rng(3)
    block = image.blank(9, 9)
    block[:, :, :3] = rng.integers(0, 255, (9, 9, 3), dtype=np.uint8)
    block[:, :, 3] = 255
    present = {tuple(c) for c in image.unique_colors(block)}
    small = render._mode_downscale(block, 3)
    assert {tuple(c) for c in image.unique_colors(small)} <= present


def test_mode_downscale_takes_the_majority_not_an_average():
    block = image.blank(3, 3)
    block[:, :] = [10, 20, 30, 255]
    block[0, 0] = [200, 0, 0, 255]
    out = render._mode_downscale(block, 3)
    assert tuple(out[0, 0]) == (10, 20, 30, 255)


def test_mode_downscale_survives_a_pure_white_sprite():
    """White is 0xFFFFFFFF; using that as the empty marker erases white art."""
    block = image.blank(3, 3)
    block[:, :] = [255, 255, 255, 255]
    assert tuple(render._mode_downscale(block, 3)[0, 0]) == (255, 255, 255, 255)


def test_mode_downscale_drops_a_block_that_is_mostly_hole():
    block = image.blank(3, 3)
    block[0, 0] = [1, 2, 3, 255]
    assert render._mode_downscale(block, 3)[0, 0][3] == 0


def test_mode_downscale_keeps_a_block_the_art_mostly_covers():
    block = image.blank(3, 3)
    block[:, :2] = [1, 2, 3, 255]      # six of nine samples
    assert tuple(render._mode_downscale(block, 3)[0, 0]) == (1, 2, 3, 255)


def test_mode_downscale_uses_a_majority_and_not_a_generous_threshold():
    """A lower threshold looks better and is dilation: limbs simply get fatter."""
    block = image.blank(3, 3)
    block[:, :1] = [1, 2, 3, 255]      # three of nine samples
    assert render._mode_downscale(block, 3)[0, 0][3] == 0


def test_rotation_preserves_the_characters_mass(hero, hero_cutout, hero_rig):
    """Nearest-neighbour rotation at 1:1 erodes a sprite by about 4% every time
    a limb turns. That is what the supersampling is for, and this is the claim."""
    rest = int(image.alpha_mask(hero.pixels).sum())
    margin = render.suggest_margin(hero_rig)
    areas = []
    for name in ("walk", "run", "jump", "attack"):
        animation = motion.scale_motion([motion.get(name)], hero_rig.size[1])[0]
        for pose in animation.poses(hero_rig):
            frame = render.render_pose(hero_cutout, pose, margin=margin)
            areas.append(int(image.alpha_mask(frame).sum()) / rest)
    mean = sum(areas) / len(areas)
    assert 0.95 <= mean <= 1.05, "the character gains or loses mass as it moves"
    assert max(abs(area - 1.0) for area in areas) < 0.15


def test_supersampling_beats_no_supersampling_at_preserving_mass(
        hero, hero_cutout, hero_rig):
    rest = int(image.alpha_mask(hero.pixels).sum())
    margin = render.suggest_margin(hero_rig)
    animation = motion.scale_motion([motion.get("run")], hero_rig.size[1])[0]

    def error(supersample):
        total = 0.0
        for pose in animation.poses(hero_rig):
            frame = _render_at(hero_cutout, pose, margin, supersample)
            total += abs(int(image.alpha_mask(frame).sum()) / rest - 1.0)
        return total / animation.frames

    assert error(render.SUPERSAMPLE) < error(1)


def _render_at(cut, pose, margin, supersample):
    from spritepipe import skeleton as sk
    width, height = render.canvas_size(cut.rig, margin)
    transforms = sk.world_transforms(cut.rig, pose)
    shift = sk.translate(margin, margin)
    frame = image.blank(height, width)
    for sprite in cut.sprites:
        layer = image.blank(height, width)
        image.paste(layer, sprite.pixels,
                    sprite.origin[0] + margin, sprite.origin[1] + margin)
        matrix = shift @ transforms[sprite.name] @ np.linalg.inv(shift)
        image.paste(frame, render._transform_layer(layer, matrix, (width, height),
                                                   supersample=supersample), 0, 0)
    return image.harden_alpha(frame)


def test_supersampling_does_not_move_the_part(hero_cutout):
    """Cleaner sampling must not shift the art, or every anchor drifts."""
    pose = skeleton.Pose({"arm_near": skeleton.PartPose(angle=-90)})
    frame = render.render_pose(hero_cutout, pose, margin=20)
    plain = render.render_pose(hero_cutout, skeleton.Pose(), margin=20)
    assert abs(image.content_box(frame)[3] - image.content_box(plain)[3]) <= 2


def test_an_unrotated_part_never_goes_through_the_resampler(hero, hero_cutout):
    """Most parts in most frames take this path, and it stays pixel-exact."""
    assert image.equal(render.render_pose(hero_cutout, skeleton.Pose()), hero.pixels)
