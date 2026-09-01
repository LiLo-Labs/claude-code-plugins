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
    assert outfit._free_end(down)[1] == 16
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
