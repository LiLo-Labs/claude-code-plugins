"""The partition must be exact, and a swinging limb must not tear the body."""

import pytest

import make_fixture
from spritepipe import cutout, image, ingest, rig as R, vision


def cut_of(art):
    reference = ingest.Reference(art, image.unique_colors(art), 1,
                                 (art.shape[1], art.shape[0]), {})
    built = vision.TemplateBackend().rig(reference)
    return built, cutout.cut(built, art)


ART = [("humanoid", make_fixture.humanoid()),
       ("robed", make_fixture.humanoid(legs_parted=False)),
       ("touching-arms", make_fixture.humanoid(arms_clear=False)),
       ("creature", make_fixture.creature()),
       ("prop", make_fixture.prop())]


@pytest.mark.parametrize("name,art", ART, ids=[name for name, _ in ART])
def test_the_rest_pose_reconstructs_the_source_exactly(name, art):
    """The strongest claim this plugin makes. If it fails, every frame is wrong."""
    trimmed = image.trim(art)[0]
    _, pieces = cut_of(trimmed)
    assert image.equal(pieces.rest(), trimmed)


@pytest.mark.parametrize("name,art", ART, ids=[name for name, _ in ART])
def test_every_opaque_pixel_is_owned_exactly_once(name, art):
    trimmed = image.trim(art)[0]
    built, _ = cut_of(trimmed)
    mask = image.alpha_mask(trimmed)
    owner = cutout.ownership(built, mask)
    assert (owner[mask] >= 0).all(), "some opaque pixel is owned by nothing"
    assert (owner[~mask] == -1).all(), "a transparent pixel was claimed"


def test_the_smallest_box_wins_so_a_nested_part_keeps_its_pixels():
    art = image.blank(10, 10)
    art[:, :] = [10, 20, 30, 255]
    big = R.Part("body", "body", (0, 0, 10, 10), None, (5, 10), z=0)
    small = R.Part("head", "head", (3, 3, 6, 6), "body", (4, 6), z=1)
    built = R.Rig((10, 10), [big, small])
    owner = cutout.ownership(built, image.alpha_mask(art))
    assert owner[4, 4] == 1
    assert owner[0, 0] == 0


def test_a_pixel_no_box_covers_falls_to_the_root_rather_than_vanishing():
    art = image.blank(10, 10)
    art[:, :] = [10, 20, 30, 255]
    built = R.Rig((10, 10), [R.Part("body", "body", (0, 0, 4, 4), None, (2, 4))])
    owner = cutout.ownership(built, image.alpha_mask(art))
    assert (owner[image.alpha_mask(art)] == 0).all()


def test_backfill_puts_colour_under_a_limb_without_changing_the_rest_pose():
    """The fill is invisible until the arm moves, and then it is the body."""
    trimmed = image.trim(make_fixture.humanoid())[0]
    built, filled = cut_of(trimmed)
    plain = cutout.cut(built, trimmed, backfill=False)

    torso_filled = filled.by_name("torso")
    torso_plain = plain.by_name("torso")
    assert (image.alpha_mask(torso_filled.pixels).sum()
            >= image.alpha_mask(torso_plain.pixels).sum())
    assert image.equal(filled.rest(), trimmed)
    assert image.equal(plain.rest(), trimmed)


def test_backfill_invents_no_colour():
    trimmed = image.trim(make_fixture.humanoid())[0]
    _, pieces = cut_of(trimmed)
    allowed = {tuple(c) for c in image.unique_colors(trimmed)}
    for sprite in pieces.sprites:
        for colour in image.unique_colors(sprite.pixels):
            assert tuple(colour) in allowed


def test_a_part_sprite_knows_where_its_pivot_sits_inside_itself():
    trimmed = image.trim(make_fixture.humanoid())[0]
    built, pieces = cut_of(trimmed)
    for sprite in pieces.sprites:
        part = built.by_name(sprite.name)
        assert sprite.pivot_local == (part.pivot[0] - part.box[0],
                                      part.pivot[1] - part.box[1])
