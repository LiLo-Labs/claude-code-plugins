"""The rig's structural guarantees. Validation catches what a picture cannot."""


from spritepipe import rig as R


def part(name, role="body", box=(0, 0, 4, 4), parent=None, pivot=(2, 2), z=0):
    return R.Part(name, role, box, parent, pivot, z)


def build(parts, size=(10, 10)):
    return R.Rig(size, parts)


def test_a_sound_rig_has_no_problems():
    assert R.validate(build([
        part("torso", "torso", (2, 3, 8, 7), None, (5, 7), 1),
        part("head", "head", (3, 0, 7, 4), "torso", (5, 3), 2),
        part("arm_near", "arm_near", (7, 3, 9, 7), "torso", (8, 3), 3),
        part("arm_far", "arm_far", (1, 3, 3, 7), "torso", (2, 3), 0),
    ])) == []


def test_no_root_is_caught():
    problems = R.validate(build([part("a", parent="b"), part("b", parent="a")]))
    assert any("no root" in problem for problem in problems)


def test_two_roots_are_caught():
    problems = R.validate(build([part("a"), part("b")]))
    assert any("2 root parts" in problem for problem in problems)


def test_a_parent_cycle_is_caught():
    problems = R.validate(build([part("root"), part("a", parent="b"),
                                 part("b", parent="a")]))
    assert any("cycle" in problem for problem in problems)


def test_an_unreachable_part_is_caught():
    """FK never visits it, so it would silently never move."""
    problems = R.validate(build([part("root"), part("a", parent="ghost")]))
    assert any("not a part" in problem for problem in problems)


def test_a_box_outside_the_reference_is_caught():
    problems = R.validate(build([part("root", box=(0, 0, 40, 4))], size=(10, 10)))
    assert any("outside" in problem for problem in problems)


def test_an_empty_box_is_caught():
    problems = R.validate(build([part("root", box=(4, 4, 4, 8))]))
    assert any("empty box" in problem for problem in problems)


def test_an_unknown_role_is_caught():
    problems = R.validate(build([part("root", role="elbow")]))
    assert any("not one of" in problem for problem in problems)


def test_a_missing_pivot_is_caught():
    lone = part("root")
    lone.pivot = None
    assert any("no pivot" in problem for problem in R.validate(build([lone])))


def test_a_paired_limb_with_no_partner_is_caught():
    """A one-armed walk cycle is a rigging miss, not a design choice."""
    problems = R.validate(build([
        part("torso", "torso", (2, 3, 8, 7), None, (5, 7)),
        part("arm_near", "arm_near", (7, 3, 9, 7), "torso", (8, 3)),
    ]))
    assert any("no arm_far" in problem for problem in problems)


def test_duplicate_names_are_caught():
    problems = R.validate(build([part("a"), part("a", parent="a")]))
    assert any("duplicate" in problem for problem in problems)


def test_descend_visits_parents_before_children():
    rig = build([part("c", parent="b"), part("b", parent="a"), part("a")])
    order = [p.name for p in rig.descend()]
    assert order.index("a") < order.index("b") < order.index("c")


def test_draw_order_is_by_z_then_name_so_it_is_stable():
    rig = build([part("z", z=1), part("a", z=1), part("root", z=0)])
    assert [p.name for p in rig.draw_order()] == ["root", "a", "z"]


def test_serialisation_round_trips(tmp_path, hero_rig):
    path = str(tmp_path / "r.json")
    hero_rig.save(path)
    again = R.Rig.load(path)
    assert again.to_dict() == hero_rig.to_dict()


def test_anchor_defaults_to_the_bottom_centre():
    rig = R.Rig((10, 20), [part("root")])
    assert R.anchor_of(rig) == (5, 20)


def test_an_explicit_anchor_wins():
    rig = R.Rig((10, 20), [part("root")], anchor=(3, 17))
    assert R.anchor_of(rig) == (3, 17)
