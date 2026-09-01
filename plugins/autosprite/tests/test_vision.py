"""What the silhouette says, and what a model's answer is repaired into."""

import json

import numpy as np
import pytest

import make_fixture
from spritepipe import image, ingest, rig as R, vision


def rig_of(pixels, **kwargs):
    reference = ingest.Reference(pixels, image.unique_colors(pixels), 1,
                                 (pixels.shape[1], pixels.shape[0]), {})
    return vision.TemplateBackend().rig(reference, **kwargs)


# -- measurements ---------------------------------------------------------

def test_runs_finds_the_spans_not_the_width():
    row = np.array([0, 1, 1, 0, 0, 1, 0], dtype=bool)
    assert vision.runs(row) == [(1, 3), (5, 6)]


def test_the_neck_is_the_last_narrow_row_not_the_first():
    """Taking the first cuts a uniform-width head in half."""
    mask = image.alpha_mask(make_fixture.humanoid())
    neck = vision.find_neck(mask)
    shoulder = vision.find_shoulder(mask, neck)
    assert neck < shoulder
    widths = vision.row_widths(mask)
    assert widths[neck] <= widths[shoulder]
    # The head is rows 1..6 in this fixture; the neck must be at its bottom.
    assert neck >= 4


def test_the_neck_is_found_when_the_head_is_wider_than_the_shoulders():
    """A chibi's head is the widest part of the character, so the body never
    widens below it. A landmark that looks for widening shoulders puts the neck
    two rows below the crown, and the rig then animates the face as torso."""
    art = image.blank(18, 12)
    art[0:8, 1:11] = [230, 190, 140, 255]      # a big head, 10 wide
    art[8:9, 4:8] = [230, 190, 140, 255]       # a narrow neck, 4 wide
    art[9:14, 3:9] = [40, 90, 200, 255]        # a smaller body, 6 wide
    art[14:18, 3:5] = [60, 60, 90, 255]        # legs, parted
    art[14:18, 7:9] = [60, 60, 90, 255]
    mask = image.alpha_mask(image.trim(art)[0])
    neck = vision.find_neck(mask)
    assert neck == 8, "the neck is the narrow row, not the top of the skull"
    assert vision.find_shoulder(mask, neck) > neck


def test_a_chibi_gets_a_head_worth_the_name():
    """The failure this fixes: a 2-row head on a 17-row character."""
    art = image.blank(18, 12)
    art[0:8, 1:11] = [230, 190, 140, 255]
    art[8:9, 4:8] = [230, 190, 140, 255]
    art[9:14, 3:9] = [40, 90, 200, 255]
    art[14:18, 3:5] = [60, 60, 90, 255]
    art[14:18, 7:9] = [60, 60, 90, 255]
    built = rig_of(image.trim(art)[0])
    head = built.first_role("head")
    assert head is not None
    assert head.height >= 7, "the head box must actually contain the head"


def test_the_leg_split_is_found_from_the_feet_not_from_the_middle():
    """Scanning down finds the armpit; scanning up from the floor finds the hips."""
    art = make_fixture.humanoid()
    mask = image.alpha_mask(art)
    armpit = next(y for y in range(mask.shape[0]) if vision.row_runs(mask[y]) >= 2)
    hips = vision.find_split(mask)
    assert armpit < hips
    assert hips > mask.shape[0] * 0.4


def test_no_split_when_the_legs_never_part():
    mask = image.alpha_mask(make_fixture.humanoid(legs_parted=False))
    assert vision.find_split(mask) is None


def test_core_and_limbs_excludes_the_torso_from_the_arms():
    art = make_fixture.humanoid(arms_clear=True)
    mask = image.alpha_mask(art)
    core, left, right = vision.core_and_limbs(mask, 8, 15, art.shape[1] // 2)
    assert core and left and right
    assert left[2] <= core[0] and right[0] >= core[2]


# -- the template rigger --------------------------------------------------

def test_a_humanoid_rigs_into_six_parts():
    built = rig_of(image.trim(make_fixture.humanoid())[0])
    assert built.character_class == "humanoid"
    assert {p.role for p in built.parts} == {
        "torso", "head", "arm_near", "arm_far", "leg_near", "leg_far"}
    assert R.validate(built) == []


def test_the_head_box_covers_the_whole_head():
    art = image.trim(make_fixture.humanoid())[0]
    built = rig_of(art)
    head = built.first_role("head")
    mask = image.alpha_mask(art)
    top_row_width = int(mask[1].sum())
    assert head.box[3] - head.box[1] >= 4
    assert head.width >= top_row_width


def test_arms_touching_the_body_fall_back_and_say_so():
    built = rig_of(image.trim(make_fixture.humanoid(arms_clear=False))[0])
    assert any("never separate" in note for note in built.notes)
    assert built.first_role("arm_near") is not None


def test_robed_legs_fall_back_to_a_proportion_and_say_so():
    built = rig_of(image.trim(make_fixture.humanoid(legs_parted=False))[0])
    assert any("never parts" in note for note in built.notes)


def test_near_and_far_swap_with_facing():
    art = image.trim(make_fixture.humanoid())[0]
    right = rig_of(art, facing="right")
    left = rig_of(art, facing="left")
    assert right.first_role("arm_near").box != left.first_role("arm_near").box
    assert right.first_role("arm_near").box == left.first_role("arm_far").box


def test_a_wide_creature_classifies_as_a_creature():
    built = rig_of(image.trim(make_fixture.creature())[0])
    assert built.character_class == "creature"
    assert built.first_role("tail") is not None
    assert R.validate(built) == []


def test_a_compact_shape_classifies_as_a_prop_and_stays_one_piece():
    built = rig_of(image.trim(make_fixture.prop())[0])
    assert built.character_class == "prop"
    assert len(built.parts) == 1
    assert R.validate(built) == []


def test_the_template_records_itself_as_deterministic():
    """Nothing downstream may mistake a silhouette guess for a model's opinion."""
    assert rig_of(image.trim(make_fixture.humanoid())[0]).actor.startswith("deterministic:")


# -- repairing a model's answer -------------------------------------------

def parse(payload, reference):
    return vision.HeadlessBackend("/tmp").parse(json.dumps(payload), reference)


@pytest.fixture
def reference():
    art = image.trim(make_fixture.humanoid())[0]
    return ingest.Reference(art, image.unique_colors(art), 1,
                            (art.shape[1], art.shape[0]), {})


def test_fractional_boxes_become_pixels(reference):
    built = parse({"class": "humanoid", "parts": [
        {"name": "torso", "role": "torso", "box": [0.25, 0.3, 0.75, 0.6],
         "parent": None, "pivot": [0.5, 0.6]}]}, reference)
    width, height = reference.size
    assert built.parts[0].box == (round(0.25 * width), round(0.3 * height),
                                  round(0.75 * width), round(0.6 * height))


def test_a_model_that_answered_in_pixels_is_still_understood(reference):
    width, height = reference.size
    built = parse({"parts": [
        {"name": "torso", "role": "torso", "box": [2, 3, width - 2, height - 3],
         "parent": None, "pivot": [width // 2, height - 3]}]}, reference)
    assert built.parts[0].box == (2, 3, width - 2, height - 3)


def test_a_box_outside_the_image_is_clamped(reference):
    built = parse({"parts": [{"name": "t", "role": "torso", "box": [-0.5, -0.5, 2.0, 2.0],
                              "parent": None}]}, reference)
    assert R.validate(built) == [] or all("outside" not in p for p in R.validate(built))


def test_a_missing_pivot_is_inferred_and_recorded(reference):
    built = parse({"parts": [{"name": "t", "role": "torso", "box": [0, 0, 1, 1],
                              "parent": None}]}, reference)
    assert built.parts[0].pivot is not None
    assert any("no pivot" in note for note in built.notes)


def test_no_root_promotes_the_largest_part(reference):
    built = parse({"parts": [
        {"name": "small", "role": "head", "box": [0.4, 0.0, 0.6, 0.2], "parent": "big"},
        {"name": "big", "role": "torso", "box": [0.2, 0.2, 0.8, 0.9], "parent": "small"},
    ]}, reference)
    assert built.root.name == "big"
    assert any("largest part" in note for note in built.notes)


def test_a_second_root_is_reparented(reference):
    built = parse({"parts": [
        {"name": "a", "role": "torso", "box": [0.2, 0.2, 0.8, 0.9], "parent": None},
        {"name": "b", "role": "head", "box": [0.4, 0.0, 0.6, 0.2], "parent": None},
    ]}, reference)
    assert built.root.name == "a"
    assert built.by_name("b").parent == "a"


def test_an_unknown_parent_is_reparented_to_the_root(reference):
    built = parse({"parts": [
        {"name": "a", "role": "torso", "box": [0.2, 0.2, 0.8, 0.9], "parent": None},
        {"name": "b", "role": "head", "box": [0.4, 0.0, 0.6, 0.2], "parent": "ghost"},
    ]}, reference)
    assert built.by_name("b").parent == "a"


def test_an_unknown_role_animates_as_body_and_says_so(reference):
    built = parse({"parts": [{"name": "a", "role": "elbow", "box": [0, 0, 1, 1],
                              "parent": None}]}, reference)
    assert built.parts[0].role == "body"
    assert any("vocabulary" in note for note in built.notes)


def test_an_empty_answer_is_refused_with_advice(reference):
    with pytest.raises(ValueError) as error:
        parse({"parts": []}, reference)
    assert "--backend template" in str(error.value)


def test_json_is_found_inside_a_markdown_fence():
    payload = vision._extract_json('```json\n{"parts": [], "class": "humanoid"}\n```')
    assert payload["class"] == "humanoid"


def test_json_is_found_after_prose():
    payload = vision._extract_json('Looking at the sprite:\n{"a": {"b": 1}}\nDone.')
    assert payload == {"a": {"b": 1}}


def test_unparseable_output_names_what_it_saw():
    with pytest.raises(ValueError) as error:
        vision._extract_json("I could not see the image.")
    assert "could not see" in str(error.value)


def test_make_backend_rejects_an_unknown_name():
    with pytest.raises(ValueError):
        vision.make_backend("midjourney", "/tmp")


# -- a pair the silhouette only half-resolves ------------------------------

def test_one_arm_is_completed_by_mirroring_rather_than_failing_the_build():
    """A profile hides the far arm, and a cape can swallow one leg entirely.
    Emitting only the limb that was found produces a rig `validate` refuses, so
    a real character would not build at all rather than animate imperfectly."""
    left, right, mirrored = vision._complete_pair((2, 5, 6, 14), None, (6, 4, 18, 16), 24)
    assert mirrored
    assert right is not None
    assert right[2] - right[0] == 6 - 2, "the partner keeps the found limb's width"
    centre = (6 + 18) / 2.0
    assert abs((left[0] + left[2]) / 2.0 - centre) == abs((right[0] + right[2]) / 2.0 - centre)


def test_a_mirror_that_lands_outside_is_shifted_back_in_not_truncated():
    """A truncated box is a one-pixel limb: it validates, animates, and looks
    exactly like the character lost an arm anyway."""
    _, right, mirrored = vision._complete_pair((0, 5, 4, 14), None, (2, 4, 8, 16), 10)
    assert mirrored
    assert right[2] - right[0] == 4
    assert 0 <= right[0] and right[2] <= 10


def test_completing_a_pair_leaves_a_complete_pair_alone():
    left, right, mirrored = vision._complete_pair((1, 2, 3, 4), (7, 2, 9, 4), (0, 0, 10, 10))
    assert not mirrored and left == (1, 2, 3, 4) and right == (7, 2, 9, 4)


def test_completing_a_pair_leaves_two_missing_limbs_alone():
    """Both missing is the other fallback's job, not this one's."""
    left, right, mirrored = vision._complete_pair(None, None, (0, 0, 10, 10))
    assert (left, right, mirrored) == (None, None, False)


def test_a_character_with_one_visible_arm_produces_a_valid_rig():
    """The failure this fixes: the build died on real art with 'no arm_far'."""
    art = image.blank(30, 20)
    art[2:9, 8:13] = [230, 190, 140, 255]        # head
    art[9:20, 6:15] = [40, 90, 200, 255]         # torso
    art[10:18, 2:5] = [230, 190, 140, 255]       # ONE arm, clear of the body
    art[20:29, 6:9] = [60, 60, 90, 255]          # legs, parted
    art[20:29, 12:15] = [60, 60, 90, 255]
    built = rig_of(image.trim(art)[0])
    assert R.validate(built) == []
    assert built.first_role("arm_near") is not None
    assert built.first_role("arm_far") is not None
    assert any("mirror" in note for note in built.notes)


# -- art that is drawn in more than one piece ------------------------------

def with_drop_shadow(art, rows=1, gap=1):
    """A character with a detached shadow blob below its feet, as real art has."""
    height, width = art.shape[:2]
    out = image.blank(height + gap + rows, width)
    image.paste(out, art, 0, 0)
    out[height + gap:height + gap + rows, width // 3:width - width // 3] = [90, 90, 100, 255]
    return out


def test_a_detached_shadow_does_not_stand_in_for_the_feet():
    """Scanning up from the bottom hits the shadow, finds one run, and concludes
    the legs never part -- which demotes a person to a one-piece prop."""
    art = image.trim(make_fixture.humanoid())[0]
    plain = vision.find_split(image.alpha_mask(art))
    shadowed = vision.find_split(image.alpha_mask(with_drop_shadow(art)))
    assert plain is not None
    assert shadowed == plain, "the shadow must not move the hip line"


def test_body_mask_drops_a_detached_shadow():
    art = image.trim(make_fixture.humanoid())[0]
    body = vision.body_mask(image.alpha_mask(with_drop_shadow(art)))
    assert not body[art.shape[0]:].any(), "the shadow must not count as body"
    assert body[:art.shape[0]].any(), "the character must still be there"


def test_body_mask_keeps_a_character_genuinely_drawn_in_two_pieces():
    """A floating sword or a detached head is art, not a shadow."""
    art = image.blank(20, 20)
    art[0:8, 2:10] = [200, 40, 40, 255]
    art[12:20, 2:10] = [40, 90, 200, 255]      # same size, clearly deliberate
    kept = vision.body_mask(image.alpha_mask(art))
    assert kept.sum() == image.alpha_mask(art).sum()


def test_a_shadowed_character_still_rigs_as_a_humanoid():
    built = rig_of(image.trim(with_drop_shadow(image.trim(make_fixture.humanoid())[0]))[0])
    assert built.character_class == "humanoid"
    assert R.validate(built) == []


def test_the_shadow_is_still_owned_by_some_part():
    """Measurements ignore it; the cut must not - it is the user's art."""
    art = image.trim(with_drop_shadow(image.trim(make_fixture.humanoid())[0]))[0]
    built = rig_of(art)
    from spritepipe import cutout
    assert image.equal(cutout.cut(built, art).rest(), art)


def test_the_leg_split_looks_past_merged_hooves():
    """A horse's hooves, boots on a ground line, or a baked contact shadow merge
    the last row back into one span. Requiring the very bottom row to be parted
    threw the whole signal away and demoted a winged pony to a one-piece prop."""
    art = image.trim(make_fixture.humanoid())[0]
    grounded = image.blank(art.shape[0] + 1, art.shape[1])
    image.paste(grounded, art, 0, 0)
    box = image.content_box(art)
    grounded[art.shape[0], box[0]:box[2]] = [60, 60, 90, 255]   # one merged row

    plain = vision.find_split(image.alpha_mask(art))
    merged = vision.find_split(image.alpha_mask(grounded))
    assert plain is not None
    assert merged == plain, "one merged row at the floor must not hide the legs"


def test_a_character_that_never_parts_still_reports_none():
    """The slack must not invent legs on a robe."""
    robed = image.trim(make_fixture.humanoid(legs_parted=False))[0]
    assert vision.find_split(image.alpha_mask(robed)) is None


def test_the_slack_does_not_reach_arbitrarily_far_up():
    """Two merged rows is a ground line; ten is a character with no legs."""
    art = image.trim(make_fixture.humanoid())[0]
    box = image.content_box(art)
    padded = image.blank(art.shape[0] + 8, art.shape[1])
    image.paste(padded, art, 0, 0)
    for row in range(art.shape[0], art.shape[0] + 8):
        padded[row, box[0]:box[2]] = [60, 60, 90, 255]
    assert vision.find_split(image.alpha_mask(padded)) is None


# -- a quadruped's legs are columns, not rows -----------------------------

def test_leg_columns_finds_one_run_per_leg_pair():
    mask = image.alpha_mask(make_fixture.creature())
    belly = vision.find_split(mask, floor=0.45)
    assert vision.leg_columns(mask, belly, mask.shape[0]) == [(7, 10), (17, 20)]


def test_a_shallow_belly_fringe_does_not_widen_a_leg():
    """The horse's underside hangs a pixel or two below the belly line the
    whole length of the animal. Reading legs by presence makes that fringe part
    of a leg and the leg twenty pixels wide; reading them by reach does not."""
    mask = np.zeros((10, 20), dtype=bool)
    mask[:5, :] = True                 # body
    mask[5:6, 2:18] = True             # a one-pixel fringe under all of it
    mask[5:10, 3:6] = True             # hind leg
    mask[5:10, 14:17] = True           # fore leg
    assert vision.leg_columns(mask, 5, 10) == [(3, 6), (14, 17)]


def test_a_notch_inside_one_hoof_does_not_split_it():
    mask = np.zeros((10, 20), dtype=bool)
    mask[:5, :] = True
    mask[5:10, 3:6] = True
    mask[5:10, 7:9] = True             # same leg, one empty column between
    mask[5:10, 15:18] = True
    assert vision.leg_columns(mask, 5, 10) == [(3, 9), (15, 18)]


def test_the_leg_groups_split_at_the_animal_s_length():
    """Three runs: one hind leg, and two forelegs close together."""
    assert vision.split_leg_groups([(3, 6), (20, 23), (24, 27)]) \
        == ([(3, 6)], [(20, 23), (24, 27)])


def test_one_cluster_of_legs_is_not_a_quadruped():
    assert vision.split_leg_groups([(3, 6)]) is None
    assert vision.split_leg_groups([]) is None


def test_a_quadruped_rigs_with_four_legs_and_the_forelegs_lead():
    built = rig_of(make_fixture.creature())
    assert built.character_class == "creature"
    roles = {part.name: part.role for part in built.parts}
    assert roles["foreleg_near"] == "arm_near" and roles["foreleg_far"] == "arm_far"
    assert roles["hindleg_near"] == "leg_near" and roles["hindleg_far"] == "leg_far"
    # Facing right, the forelegs are the cluster nearer the head.
    assert built.by_name("foreleg_near").box[0] > built.by_name("hindleg_near").box[0]


def test_a_leg_box_holds_one_leg_not_the_whole_underside():
    """The bug this replaced: the pegasus's last row is a single merged span,
    `pair_boxes` halved it, and the far leg's box grew from 5 pixels wide to 15
    -- a slab holding both leg pairs, which sheared a tenth of the animal off
    when it swung."""
    mask = np.zeros((26, 27), dtype=bool)
    mask[:18, :] = True
    mask[18:24, 5:10] = True           # hind legs
    mask[18:25, 17:22] = True          # fore legs
    mask[24:25, 19:22] = True          # ... ending in one merged hoof row
    parts = vision.TemplateBackend()._creature(mask, 27, 26, "right")[0]
    for part in parts:
        if part.role.endswith("_near") or part.role.endswith("_far"):
            assert part.box[2] - part.box[0] <= 6, part


def test_a_creature_whose_legs_never_part_falls_back_to_halving():
    mask = np.zeros((14, 16), dtype=bool)
    mask[:8, :] = True
    mask[8:14, 5:11] = True            # one block of legs, never parted
    parts, notes = vision.TemplateBackend()._creature(mask, 16, 14, "right")
    names = {part.name for part in parts}
    assert "leg_near" in names and "leg_far" in names
    assert any("never separate" in note for note in notes)


# -- a character drawn face-on --------------------------------------------

def test_a_face_on_rig_draws_both_arms_in_front_of_the_torso():
    """In profile the far arm is BEHIND the body, which is right there and
    wrong for a character looking at you: both arms are drawn, both in front."""
    built = rig_of(make_fixture.humanoid(), facing="front")
    order = [part.role for part in built.draw_order()]
    assert order.index("arm_far") > order.index("torso")
    assert order.index("leg_far") > order.index("torso")


def test_a_profile_rig_still_hides_the_far_arm():
    built = rig_of(make_fixture.humanoid(), facing="right")
    order = [part.role for part in built.draw_order()]
    assert order.index("arm_far") < order.index("torso")


def test_a_face_on_rig_names_the_limbs_left_and_right():
    built = rig_of(make_fixture.humanoid(), facing="front")
    names = {part.name for part in built.parts}
    assert {"arm_left", "arm_right", "leg_left", "leg_right"} <= names
    # The roles are untouched: every animation and every exporter reads role.
    assert built.by_name("arm_left").role == "arm_far"
    assert any("face-on" in note for note in built.notes)


def test_facing_back_is_face_on_too():
    built = rig_of(make_fixture.humanoid(), facing="back")
    assert built.by_name("arm_left") is not None


def test_a_face_on_rig_still_validates():
    built = rig_of(make_fixture.humanoid(), facing="front")
    assert R.validate(built) == []


def test_a_face_on_character_is_never_rigged_as_a_side_on_animal():
    """`classify` reads the silhouette, and a stocky character drawn face-on is
    wider than it is tall exactly like a horse. The corpus's 16px roguelike hero
    was rigged with its left arm as a head and its right arm as a tail."""
    stocky = np.zeros((14, 16, 4), dtype=np.uint8)
    stocky[2:10, 2:14] = (90, 120, 90, 255)     # a body wider than it is tall
    stocky[0:4, 5:11] = (200, 170, 140, 255)    # a head
    stocky[10:14, 3:6] = (60, 60, 70, 255)      # ... standing on two feet,
    stocky[10:14, 10:13] = (60, 60, 70, 255)    # which is what `classify` reads
    assert rig_of(stocky).character_class == "creature"
    front = rig_of(stocky, facing="front")
    assert front.character_class == "humanoid"
    assert front.by_role("tail") == []
    assert any("face-on" in note for note in front.notes)


def test_a_side_on_animal_is_still_a_creature():
    assert rig_of(make_fixture.creature(), facing="right").character_class == "creature"
    assert rig_of(make_fixture.creature(), facing="left").character_class == "creature"
