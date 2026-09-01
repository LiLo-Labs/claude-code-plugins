"""Props animate as one piece, and the spin is the only interesting one."""

import pytest

from spritepipe import motion, props, rig as R


@pytest.fixture
def gem_rig():
    return R.Rig((10, 10), [R.Part("body", "body", (0, 0, 10, 10), None, (5, 10))])


def test_every_prop_animation_validates():
    for name, animation in props.LIBRARY.items():
        assert motion.validate_animation(animation.to_dict()) == [], name


def test_spin_squashes_to_edge_on_at_the_quarter_points():
    spin = props.get("spin")
    widths = [spin.root.sample(t, True).sx for t in spin.times()]
    assert min(widths) < 0.2
    assert max(widths) == pytest.approx(1.0)


def test_spin_mirrors_for_the_second_half_because_there_is_no_back_face(gem_rig):
    spin = props.get("spin")
    flips = [spin.pose_at(gem_rig, t).flip for t in spin.times()]
    assert flips[:4] == [False] * 4
    assert flips[4:] == [True] * 4


def test_tumble_turns_exactly_once_per_loop():
    tumble = props.get("tumble")
    angles = [tumble.root.sample(t, True).angle for t in tumble.times()]
    assert angles[0] == pytest.approx(0.0)
    assert angles[-1] < 360.0
    assert all(b >= a for a, b in zip(angles, angles[1:])), "a tumble must not reverse"


def test_tumble_turns_at_a_constant_rate():
    """Easing a tumble makes it look like it is hitting something."""
    tumble = props.get("tumble")
    angles = [tumble.root.sample(t, True).angle for t in tumble.times()]
    steps = [round(b - a, 3) for a, b in zip(angles, angles[1:])]
    assert len(set(steps)) == 1


def test_pulse_keeps_the_volume_so_it_reads_as_elastic():
    pulse = props.get("pulse")
    for t in pulse.times():
        sample = pulse.root.sample(t, True)
        assert 0.9 < sample.sx * sample.sy < 1.1


def test_presets_expand():
    assert [a.name for a in props.resolve(["pickup"])] == ["bob", "spin"]


def test_an_unknown_prop_animation_lists_what_exists():
    with pytest.raises(KeyError) as error:
        props.get("explode")
    assert "spin" in str(error.value)


def test_the_prop_and_character_libraries_do_not_collide():
    assert not set(props.LIBRARY) & set(motion.LIBRARY)
