"""One item, drawn once, on any character that has the part to hang it from.

The property worth protecting is that outfitting changes nothing else. An item
is composited into the source art before anything else runs, so REST still
proves the parts reassemble exactly and PALETTE still proves every output colour
came from the input -- no check had to be relaxed to let a sword in.
"""

import json
import os

import numpy as np
import pytest

from spritepipe import cutout, image, ingest, motion, outfit, pipeline, rig as R, vision


@pytest.fixture
def sword(tmp_path):
    """A two-colour blade with a hilt, held at its bottom centre."""
    pixels = image.blank(12, 4)
    pixels[0:9, 1:3] = [200, 200, 210, 255]      # blade
    pixels[9:10, 0:4] = [90, 60, 30, 255]        # crossguard
    pixels[10:12, 1:3] = [120, 80, 40, 255]      # grip
    path = str(tmp_path / "sword.png")
    image.save(pixels, path)
    return path


@pytest.fixture
def rigged(hero_path):
    reference = ingest.ingest(hero_path)
    return reference, vision.TemplateBackend().rig(reference)


def test_the_sockets_a_rig_offers_come_from_the_parts_it_has(rigged):
    _reference, rig = rigged
    offered = outfit.sockets(rig)
    assert "hand" in offered and "head" in offered
    assert offered["hand"][0] == rig.first_role("arm_near").name


def test_a_rig_with_no_arms_offers_no_hand():
    """Derived, not declared: a socket that has nothing to hang from is not
    offered, rather than being offered somewhere in the middle of the torso."""
    rig = R.Rig((8, 12), [R.Part("body", "body", (0, 0, 8, 12), None, (4, 12), 0)])
    assert outfit.sockets(rig) == {}


def test_the_hand_is_the_end_of_the_arm_away_from_the_shoulder():
    """Measured rather than assumed, because which end is the hand depends on
    which way the limb was drawn."""
    down = R.Part("arm", "arm_near", (4, 6, 7, 16), "torso", (5, 6))
    up = R.Part("arm", "arm_near", (4, 6, 7, 16), "torso", (5, 16))
    # 15, not 16: a box's bottom is EXCLUSIVE, so the arm's last row is 15 and
    # 16 is a pixel past the end of it. This test asserted 16 until a corpus
    # sweep showed the socket landing on a transparent pixel in four rigs out
    # of five, with the item floating clear of the hand.
    assert outfit._free_end(down)[1] == 15
    assert outfit._free_end(up)[1] == 6


def test_the_default_grip_is_the_bottom_of_what_is_drawn(sword):
    """Right for a sword, a staff, a hat and a lantern -- which is enough items
    that most need no metadata at all."""
    pixels = ingest.ingest(sword).pixels
    box = image.content_box(pixels)
    assert outfit.grip_of(pixels)[1] == box[3]


def test_an_attached_item_becomes_a_part_that_rides_its_socket(rigged, sword):
    reference, rig = rigged
    item = {"socket": "hand", "pixels": ingest.ingest(sword).pixels, "name": "sword"}
    _pixels, outfitted = outfit.attach(reference.pixels, rig, [item])
    added = outfitted.by_name("sword")
    assert added is not None
    assert added.parent == outfit.sockets(rig)["hand"][0]
    assert added.z > outfitted.by_name(added.parent).z    # in front of the arm


def test_the_composed_art_still_cuts_back_into_itself_exactly(rigged, sword):
    """The REST property, which is the one outfitting could most easily break."""
    reference, rig = rigged
    item = {"socket": "hand", "pixels": ingest.ingest(sword).pixels, "name": "sword"}
    pixels, outfitted = outfit.attach(reference.pixels, rig, [item])
    assert image.equal(cutout.cut(outfitted, pixels).rest(), pixels)


def test_the_composed_art_contains_both_palettes_and_nothing_else(rigged, sword):
    reference, rig = rigged
    item_pixels = ingest.ingest(sword).pixels
    pixels, _rig = outfit.attach(reference.pixels, rig,
                                 [{"socket": "hand", "pixels": item_pixels,
                                   "name": "sword"}])
    allowed = {tuple(int(v) for v in colour)
               for source in (reference.pixels, item_pixels)
               for colour in image.unique_colors(source)}
    assert all(tuple(int(v) for v in colour) in allowed
               for colour in image.unique_colors(pixels))


def test_an_item_hanging_past_the_edge_grows_the_canvas_and_moves_the_rig(rigged):
    """A rig is coordinates in one picture. If the picture grows, every box,
    pivot and anchor has to move with it or the rig is silently wrong."""
    reference, rig = rigged
    tall = image.blank(40, 3)
    tall[:, :] = [10, 200, 10, 255]
    before = dict((part.name, part.box) for part in rig.parts)
    pixels, outfitted = outfit.attach(reference.pixels, rig,
                                      [{"socket": "head", "pixels": tall,
                                        "name": "plume"}])
    assert pixels.shape[0] > reference.pixels.shape[0]
    shift = outfitted.by_name(rig.parts[0].name).box[1] - before[rig.parts[0].name][1]
    assert shift > 0
    for part in rig.parts:
        assert outfitted.by_name(part.name).box[1] == before[part.name][1] + shift
    assert image.equal(cutout.cut(outfitted, pixels).rest(), pixels)


def test_a_socket_the_rig_does_not_have_is_refused_by_name(rigged, sword):
    _reference, rig = rigged
    with pytest.raises(ValueError) as caught:
        outfit.attach(_reference.pixels, rig,
                      [{"socket": "tail_tip", "pixels": np.zeros((2, 2, 4), np.uint8),
                        "name": "x"}])
    assert "tail_tip" in str(caught.value) and "hand" in str(caught.value)


def test_two_parts_with_one_name_are_refused(rigged, sword):
    reference, rig = rigged
    name = rig.parts[0].name
    with pytest.raises(ValueError) as caught:
        outfit.attach(reference.pixels, rig,
                      [{"socket": "hand", "pixels": ingest.ingest(sword).pixels,
                        "name": name}])
    assert name in str(caught.value)


def test_an_item_can_be_tagged_so_a_trait_clip_drives_it(rigged, sword):
    """A lantern hung on a belt should creak. That is one tag, and then a clip
    written for shutters drives it."""
    reference, rig = rigged
    _pixels, outfitted = outfit.attach(
        reference.pixels, rig,
        [{"socket": "waist", "pixels": ingest.ingest(sword).pixels,
          "name": "lantern", "tags": ("stalk",)}])
    assert outfitted.by_name("lantern").has_trait("stalk")
    assert motion.select(outfitted, "trait:stalk")


def test_a_whole_build_with_an_item_passes_every_check(hero_path, sword, tmp_path):
    """End to end, which is the only way to know the item survived packing,
    the atlas, the engine files and the verifier."""
    out = str(tmp_path / "out")
    result = pipeline.build_sheet(
        hero_path, out, animations=["idle", "walk"], engines=("all",),
        attach=[{"socket": "hand", "path": sword}])
    assert result.verification.ok, result.verification.report()
    assert os.path.exists(result.written["source"])
    assert any(part.name.startswith("hand_") for part in result.rigs["side"].parts)


def test_the_item_actually_moves_with_the_arm(hero_path, sword, tmp_path):
    """The point of the whole feature: not that the sword is in the picture,
    but that it swings. A sword that rode the ROOT would also build and verify
    and would be motionless in the character's hand."""
    out = str(tmp_path / "out")
    result = pipeline.build_sheet(
        hero_path, out, animations=["walk"], engines=(),
        attach=[{"socket": "hand", "path": sword}])
    from spritepipe import skeleton

    rig = result.rigs["side"]
    item = next(part for part in rig.parts if part.name.startswith("hand_"))
    walk = motion.get("walk")
    # The item has no track of its own -- it rides the arm -- so its LOCAL pose
    # is rest in every frame and says nothing. What moves is its world
    # transform, which is the whole mechanism being tested.
    places = {np.round(skeleton.world_transforms(rig, pose)[item.name], 4).tobytes()
              for pose in walk.poses(rig)}
    assert len(places) > 1, "the item holds still through the whole walk"


# ---------------------------------------------------------------------------
# One item, EVERY character. Two defects stopped that being true: the item was
# pasted at whatever size it happened to be drawn, and the socket it hung on
# was a corner of a bounding box rather than a pixel of the character.
# ---------------------------------------------------------------------------

def _figure(height, arm_length):
    """A stick character whose arm is a given length, and its picture."""
    width = 12
    pixels = image.blank(height, width)
    pixels[2:height - 2, 4:8] = [80, 90, 140, 255]                  # torso
    pixels[0:3, 4:8] = [220, 180, 140, 255]                         # head
    top = 4
    pixels[top:top + arm_length, 8:10] = [220, 180, 140, 255]       # near arm
    rig = R.Rig((width, height), [
        R.Part("torso", "torso", (4, 2, 8, height - 2), None, (6, height - 2), 1),
        R.Part("head", "head", (4, 0, 8, 3), "torso", (6, 3), 2),
        R.Part("arm_near", "arm_near", (8, top, 10, top + arm_length),
               "torso", (8, top), 2),
    ])
    return pixels, rig


def _blade(length):
    pixels = image.blank(length, 3)
    pixels[0:length - 2, 1:2] = [200, 200, 210, 255]
    pixels[length - 2:length, 0:3] = [120, 80, 40, 255]
    return pixels


def test_one_item_comes_out_proportionate_on_characters_of_any_size():
    """The measurement that made this necessary: a 30px CC0 sword across
    seventeen corpus characters landed anywhere from 1.4x to 30x the length of
    the arm holding it."""
    blade = _blade(24)
    ratios = []
    for height, arm in ((10, 3), (18, 6), (40, 14), (64, 22)):
        pixels, rig = _figure(height, arm)
        factor, _why = outfit.fit(blade, rig, "hand")
        ratios.append(24 * factor / float(arm))
    assert all(1.4 < ratio < 2.7 for ratio in ratios), ratios


def test_an_explicit_scale_is_taken_as_given():
    """A dagger is a short sword, not a small character."""
    pixels, rig = _figure(40, 14)
    factor, why = outfit.fit(_blade(24), rig, "hand", scale=0.25)
    assert factor == 0.25 and why == "as asked"


def test_the_scale_snaps_to_a_ratio_pixel_art_can_survive():
    """A sprite reduced by 0.37 gets a blade two pixels wide in one place and
    one in another. Every ratio offered is a simple one."""
    for wanted, expected in ((0.34, 1 / 3.0), (0.49, 0.5), (0.9, 1.0),
                             (1.9, 2.0), (100.0, 4.0), (0.0001, 1 / 6.0)):
        assert outfit.snap_ratio(wanted) == pytest.approx(expected)
    # Symmetric in log space: halving and doubling are equally far from 1.
    assert outfit.snap_ratio(2.0) == 2.0 and outfit.snap_ratio(0.5) == 0.5


def test_an_item_scaled_away_to_nothing_is_refused_by_name():
    pixels, rig = _figure(10, 1)
    with pytest.raises(ValueError) as caught:
        outfit.attach(pixels, rig, [{"socket": "hand", "pixels": _blade(60),
                                     "name": "pike", "scale": 0.01}])
    assert "pike" in str(caught.value) and "nothing was left" in str(caught.value)


def test_scaling_an_item_invents_no_colour():
    """Nearest-neighbour in both directions, which is what lets PALETTE go on
    meaning what it meant: the composed picture IS the source."""
    pixels, rig = _figure(40, 14)
    blade = _blade(24)
    composed, _built = outfit.attach(pixels, rig, [
        {"socket": "hand", "pixels": blade, "name": "sword"}])
    allowed = {tuple(colour) for colour in image.unique_colors(pixels)}
    allowed |= {tuple(colour) for colour in image.unique_colors(blade)}
    out = {tuple(colour) for colour in image.unique_colors(composed)}
    assert out <= allowed


def test_a_socket_lands_on_a_pixel_of_the_character_not_a_box_corner():
    """A box is a rectangle around a limb and a limb is not a rectangle. Given
    the picture, the point is measured on what is drawn."""
    pixels, rig = _figure(40, 14)
    x, y = outfit.sockets(rig, pixels)["hand"][1]
    assert pixels[y, x, 3] > 0


def test_the_free_end_is_inside_the_part_not_one_past_it():
    """A box's right and bottom are exclusive. Taking the far end as `y1` put
    the socket a pixel outside the limb, and an item hung there floats."""
    part = R.Part("arm_near", "arm_near", (8, 4, 10, 18), "torso", (8, 4), 2)
    x, y = outfit._free_end(part)
    assert 8 <= x < 10 and 4 <= y < 18
    assert y == 17


def test_sockets_still_answer_without_a_picture():
    """A caller holding only a rig still gets every socket, by the box rule."""
    _pixels, rig = _figure(40, 14)
    by_box = outfit.sockets(rig)
    assert set(by_box) == {"hand", "head", "waist", "chest"}
    assert all(isinstance(point, tuple) for _owner, point in by_box.values())


def test_the_picture_moves_the_socket_onto_the_character():
    """Both rules answer; they are not the same answer, and the one that used
    the picture is the one on a drawn pixel."""
    pixels, rig = _figure(40, 14)
    box_point = outfit.sockets(rig)["chest"][1]
    pixel_point = outfit.sockets(rig, pixels)["chest"][1]
    assert pixels[pixel_point[1], pixel_point[0], 3] > 0
    assert isinstance(box_point, tuple)


def test_the_item_still_rides_the_arm_after_being_resized():
    """The whole point of attaching before anything else runs. A sword parented
    to the root would also build and verify, and sit motionless in the hand."""
    pixels, rig = _figure(40, 14)
    composed, built = outfit.attach(pixels, rig, [
        {"socket": "hand", "pixels": _blade(24), "name": "sword"}])
    sword = built.by_name("sword")
    assert sword.parent == "arm_near"
    # The sword's own pose is rest in every frame and says nothing; what moves
    # is its WORLD transform, carried by the arm it is parented to.
    from spritepipe import skeleton
    walk = motion.get("walk")
    places = {np.round(skeleton.world_transforms(built, pose)["sword"], 4).tobytes()
              for pose in walk.applied(built).poses(built)}
    assert len(places) > 1
