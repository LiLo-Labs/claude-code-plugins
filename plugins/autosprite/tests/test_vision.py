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
    shoulder = vision.find_shoulder(mask)
    neck = vision.find_neck(mask, shoulder)
    assert neck < shoulder
    widths = vision.row_widths(mask)
    assert widths[neck] <= widths[shoulder]
    # The head is rows 1..6 in this fixture; the neck must be at its bottom.
    assert neck >= 4


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
