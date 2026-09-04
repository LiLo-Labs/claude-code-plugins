"""The partition must be exact, and a swinging limb must not tear the body."""

import numpy as np
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
        # Against the sprite's OWN origin, not the part's box. A sprite is cut
        # from a window grown to reach the pixels the part owns and then grown
        # again by the joint collar, so its origin is at or before the box's
        # corner and the two stopped being the same thing.
        assert sprite.pivot_local == (part.pivot[0] - sprite.origin[0],
                                      part.pivot[1] - sprite.origin[1])


# -- pixels no box reaches -------------------------------------------------

def rig_with_a_gap(size=(12, 16)):
    """Boxes that name the parts but do not tile the image.

    This is what every real rig looks like: a vision model draws a box around
    each part it can name, not a partition of the canvas, so a hem or a tuft of
    hair always falls outside all of them.
    """
    width, height = size
    return R.Rig(size, [
        R.Part("torso", "torso", (3, 5, 9, 11), None, (6, 11), z=1),
        R.Part("head", "head", (4, 1, 8, 5), "torso", (6, 5), z=2),
    ])


def full_block(size=(12, 16), colour=(40, 90, 200, 255)):
    art = image.blank(size[1], size[0])
    art[:, :] = colour
    return art


def test_a_pixel_no_box_covers_is_kept_not_silently_dropped():
    """Cutting the root from its declared box loses them, and loses them
    quietly: the sheet still builds and is missing part of the user's art."""
    art = full_block()
    built = rig_with_a_gap()
    pieces = cutout.cut(built, art)
    assert pieces.strays > 0, "the fixture must actually have uncovered pixels"
    assert image.equal(pieces.rest(), art)


def test_the_stray_count_is_reported():
    art = full_block()
    pieces = cutout.cut(rig_with_a_gap(), art)
    covered = (9 - 3) * (11 - 5) + (8 - 4) * (5 - 1)
    assert pieces.strays == 12 * 16 - covered


def test_the_root_window_grows_to_reach_its_strays():
    art = full_block()
    built = rig_with_a_gap()
    pieces = cutout.cut(built, art)
    torso = pieces.by_name("torso")
    assert torso.origin == (0, 0)
    assert torso.pixels.shape[:2] == (16, 12)


def test_a_rig_that_does_tile_the_image_reports_no_strays():
    art = full_block()
    built = R.Rig((12, 16), [R.Part("body", "body", (0, 0, 12, 16), None, (6, 16))])
    assert cutout.cut(built, art).strays == 0


# -- near beats far on a duplicated box ------------------------------------

def duplicated_arm_rig():
    """A profile rig: one visible arm, and a far box over the same pixels.

    The vision prompt asks for this on purpose -- a one-armed walk cycle reads
    as a bug -- and the far box lands a couple of pixels tighter about as often
    as not.
    """
    return R.Rig((20, 20), [
        R.Part("torso", "torso", (7, 2, 15, 16), None, (11, 16), z=1),
        R.Part("arm_far", "arm_far", (3, 4, 9, 13), "torso", (8, 4), z=-1),
        R.Part("arm_near", "arm_near", (2, 4, 9, 13), "torso", (8, 4), z=5),
    ])


def test_the_visible_arm_is_not_handed_to_the_limb_drawn_behind_the_body():
    """Otherwise the only arm you can see is drawn behind the torso, and the
    character appears to have no arms at all."""
    art = full_block((20, 20))
    built = duplicated_arm_rig()
    owner = cutout.ownership(built, image.alpha_mask(art))
    near = [i for i, p in enumerate(built.parts) if p.role == "arm_near"][0]
    far = [i for i, p in enumerate(built.parts) if p.role == "arm_far"][0]
    overlap = owner[4:13, 3:9]
    assert (overlap == near).all()
    assert (owner == far).sum() == 0


def test_a_far_limb_keeps_the_pixels_its_partner_does_not_reach():
    art = full_block((20, 20))
    built = R.Rig((20, 20), [
        R.Part("torso", "torso", (7, 2, 15, 16), None, (11, 16), z=1),
        R.Part("arm_far", "arm_far", (0, 4, 6, 13), "torso", (5, 4), z=-1),
        R.Part("arm_near", "arm_near", (15, 4, 20, 13), "torso", (16, 4), z=5),
    ])
    owner = cutout.ownership(built, image.alpha_mask(art))
    far = [i for i, p in enumerate(built.parts) if p.role == "arm_far"][0]
    assert (owner == far).sum() > 0


def test_the_partition_stays_exact_with_a_duplicated_arm():
    art = full_block((20, 20))
    pieces = cutout.cut(duplicated_arm_rig(), art)
    assert image.equal(pieces.rest(), art)


# ---------------------------------------------------------------------------
# A part that turns claims a disc, not a rectangle.
# ---------------------------------------------------------------------------

def _windmill():
    """A tower with sails crossing it. No rectangle separates the two."""
    pixels = image.blank(16, 16)
    pixels[4:16, 6:10] = [110, 100, 96, 255]        # the tower
    for offset in range(-5, 6):                      # an X through the hub (7, 5)
        for x, y in ((7 + offset, 5 + offset), (7 + offset, 5 - offset)):
            if 0 <= x < 16 and 0 <= y < 16:
                pixels[y, x] = [230, 200, 90, 255]
    return pixels


def _rig(tags):
    return R.Rig((16, 16), [
        R.Part("tower", "body", (0, 0, 16, 16), None, (8, 15), 0),
        R.Part("sails", "accessory", (0, 0, 16, 11), "tower", (7, 5), 3, 1.0, tags),
    ])


def test_a_spinner_claims_only_the_disc_it_can_turn_within():
    """Sails drawn as a cross through a tower cannot be separated from the
    tower by a rectangle. They can by a disc about the hub."""
    pixels = _windmill()
    plain = cutout.cut(_rig(()), pixels).by_name("sails")
    spun = cutout.cut(_rig(("spinner",)), pixels).by_name("sails")
    assert image.alpha_mask(spun.pixels).sum() < image.alpha_mask(plain.pixels).sum()


def test_a_pixel_a_spinner_gives_up_is_not_lost():
    """The property that makes this safe at all: ownership stays a total
    function, so the cut still reassembles into the source exactly."""
    pixels = _windmill()
    assert image.equal(cutout.cut(_rig(("spinner",)), pixels).rest(), pixels)


def test_a_spinner_keeps_everything_within_the_disc():
    pixels = _windmill()
    sails = cutout.cut(_rig(("spinner",)), pixels).by_name("sails")
    rows, columns = np.nonzero(image.alpha_mask(sails.pixels))
    radius = min(7 - 0, 16 - 7, 5 - 0, 11 - 5)
    for row, column in zip(rows, columns):
        x = column + sails.origin[0]
        y = row + sails.origin[1]
        assert (x - 7) ** 2 + (y - 5) ** 2 <= radius ** 2


def test_a_hub_outside_its_own_box_clips_nothing_rather_than_everything():
    """A radius of zero would silently empty the part, which is worse than the
    loose box it was meant to tighten."""
    pixels = _windmill()
    rig = R.Rig((16, 16), [
        R.Part("tower", "body", (0, 0, 16, 16), None, (8, 15), 0),
        R.Part("sails", "accessory", (2, 2, 12, 8), "tower", (0, 0), 3, 1.0,
               ("spinner",)),
    ])
    assert image.alpha_mask(cutout.cut(rig, pixels).by_name("sails").pixels).any()


def test_a_limb_is_not_disc_clipped():
    """An arm rotates about its pivot too, and it is long. Only a part that
    turns a FULL revolution sweeps its whole extent through a circle."""
    pixels = _windmill()
    arm = R.Rig((16, 16), [
        R.Part("tower", "body", (0, 0, 16, 16), None, (8, 15), 0),
        R.Part("sails", "arm_near", (0, 0, 16, 11), "tower", (7, 5), 3),
    ])
    plain = cutout.cut(_rig(()), pixels).by_name("sails")
    limb = cutout.cut(arm, pixels).by_name("sails")
    assert image.alpha_mask(limb.pixels).sum() == image.alpha_mask(plain.pixels).sum()
