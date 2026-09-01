"""Eight directions from the references that actually exist, honestly labelled."""

import pytest

import make_fixture
from spritepipe import directions, image


def test_east_from_a_side_view_is_the_drawing_itself():
    plan = {p.name: p for p in directions.plan("8", {"side": 1})}
    assert plan["E"].fidelity == "drawn"
    assert plan["E"].squash == 1.0 and not plan["E"].flip


def test_west_is_an_exact_mirror_not_an_approximation():
    plan = {p.name: p for p in directions.plan("8", {"side": 1})}
    assert plan["W"].fidelity == "mirrored"
    assert plan["W"].flip and plan["W"].squash == 1.0


def test_the_diagonals_are_foreshortened_and_say_so():
    plan = {p.name: p for p in directions.plan("8", {"side": 1})}
    for name in ("NE", "SE", "NW", "SW"):
        assert plan[name].fidelity == "foreshortened"
        assert 0.5 < plan[name].squash < 1.0


def test_north_and_south_are_substituted_when_nothing_faces_that_way():
    """A profile drawing does not contain the back of the head. Say so."""
    plan = {p.name: p for p in directions.plan("8", {"side": 1})}
    assert plan["S"].fidelity == "substituted"
    assert plan["N"].fidelity == "substituted"
    assert plan["S"].squash == 1.0, "a degenerate squash is worse than none"


def test_a_front_reference_makes_south_exact():
    plan = {p.name: p for p in directions.plan("8", {"side": 1, "front": 1})}
    assert plan["S"].fidelity == "drawn" and plan["S"].source == "front"


def test_a_back_reference_makes_north_exact():
    plan = {p.name: p for p in directions.plan("8", {"side": 1, "back": 1})}
    assert plan["N"].fidelity == "drawn" and plan["N"].source == "back"


def test_advice_asks_for_the_reference_that_would_help():
    note = directions.advice(directions.plan("4", {"side": 1}))
    assert "--reference-front" in note and "--reference-back" in note


def test_advice_does_not_promise_a_reference_can_fix_a_diagonal():
    note = directions.advice(directions.plan("8", {"side": 1, "front": 1, "back": 1}))
    assert "--reference-" not in note
    assert "that exact angle" in note


@pytest.mark.parametrize("name,count", [("1", 1), ("2", 2), ("4", 4), ("8", 8)])
def test_the_named_sets_have_the_right_size(name, count):
    assert len(directions.plan(name, {"side": 1})) == count


def test_an_explicit_comma_list_is_accepted():
    plans = directions.plan("E,S,NW", {"side": 1})
    assert [p.name for p in plans] == ["E", "S", "NW"]


def test_an_unknown_direction_is_refused_by_name():
    with pytest.raises(ValueError) as error:
        directions.plan("UP", {"side": 1})
    assert "UP" in str(error.value)


def test_a_squash_invents_no_colour():
    art = image.trim(make_fixture.humanoid())[0]
    allowed = {tuple(c) for c in image.unique_colors(art)}
    narrowed = directions.squash_frame(art, 0.707)
    assert {tuple(c) for c in image.unique_colors(narrowed)} <= allowed


def test_a_squash_narrows_and_keeps_the_height():
    art = image.trim(make_fixture.humanoid())[0]
    narrowed = directions.squash_frame(art, 0.6)
    before, after = image.content_box(art), image.content_box(narrowed)
    assert after[2] - after[0] < before[2] - before[0]
    assert after[3] - after[1] == before[3] - before[1]


def test_a_squash_of_one_is_a_copy():
    art = image.trim(make_fixture.humanoid())[0]
    assert image.equal(directions.squash_frame(art, 1.0), art)


def test_applying_a_mirrored_plan_twice_returns_the_original():
    art = image.trim(make_fixture.humanoid())[0]
    west = next(p for p in directions.plan("2", {"side": 1}) if p.name == "W")
    assert image.equal(west.apply(west.apply(art)), art)
