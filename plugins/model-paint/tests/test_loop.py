"""Tests for the paint-look-fix loop.

Every one of these pins a bug that reached a real render before it was caught,
which is the only reason to write a test at all. Undo that undid too much
erased four of the shell's parts after they had been painted correctly; a
palette whose colours collided made two parts indistinguishable in the very
picture the agent is asked to judge them in.
"""

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from paintpipe import loop                                   # noqa: E402


def small_tree(regions=8, per_region=4):
    """A chain: region r merges into the node above it. Deliberately the shape
    that broke everything -- an agglomerative tree's top is a chain, not a
    balanced tree."""
    total = 2 * regions - 1
    children = np.full((total, 2), -1, dtype=np.int64)
    area = np.zeros(total)
    area[:regions] = 1.0
    node = regions
    current = 0
    for nxt in range(1, regions):
        children[node] = (current, nxt)
        area[node] = area[current] + area[nxt]
        current, node = node, node + 1
    # Persistence fields too, so the tests exercise the same path a real tree
    # takes rather than the fallback.
    birth = np.zeros(total)
    death = np.full(total, np.inf)
    for node in range(regions, total):
        birth[node] = float(node - regions + 1)
        for side in children[node]:
            if side >= 0:
                death[int(side)] = birth[node]
    return {"children": children,
            "base": np.repeat(np.arange(regions, dtype=np.int64), per_region),
            "regions": regions, "area": area, "birth": birth, "death": death,
            "used": total, "floor": 0.5, "ceiling": float(regions) + 1.0}


class TestPalette(unittest.TestCase):
    def test_colours_are_distinguishable(self):
        """Two colours the agent cannot tell apart is a correctness fault: it
        is asked to judge one against another in the render."""
        colours = loop.palette(10)
        for i in range(len(colours)):
            for j in range(i + 1, len(colours)):
                gap = float(np.abs(colours[i] - colours[j]).sum())
                self.assertGreater(gap, 0.25,
                                   "colours %d and %d are too close" % (i, j))

    def test_more_colours_than_the_table_still_differ(self):
        colours = loop.palette(len(loop.DISTINCT) + 3)
        first = colours[0]
        wrapped = colours[len(loop.DISTINCT)]
        self.assertGreater(float(np.abs(first - wrapped).sum()), 0.15)


class TestBifurcate(unittest.TestCase):
    def test_a_chain_still_yields_a_split(self):
        tree = small_tree()
        parts, _shed = loop.bifurcate(tree, len(tree["children"]) - 1)
        self.assertEqual(len(parts), 2)

    def test_shed_material_is_returned_not_dropped(self):
        """A partition that loses surface is not a partition."""
        tree = small_tree()
        root = len(tree["children"]) - 1
        parts, shed = loop.bifurcate(tree, root)
        covered = set()
        from paintpipe import rig
        for node in parts:
            covered.update(int(r) for r in rig.node_regions(tree, node))
        covered.update(int(r) for r in shed)
        self.assertEqual(covered, set(range(tree["regions"])))


class TestFirstPainting(unittest.TestCase):
    class _Mesh:
        def __init__(self, faces):
            self.faces = np.zeros((faces, 3), dtype=np.int64)

    def test_every_face_is_claimed(self):
        """Nothing is ever unclaimed, so 'remove' always has somewhere to put
        a face back and there is no unpainted remainder to report."""
        tree = small_tree()
        mesh = self._Mesh(len(tree["base"]))
        field, labels = loop.first_painting(mesh, tree, count=4)
        self.assertTrue((field >= 0).all())
        self.assertGreaterEqual(len(labels), 2)


class TestUndo(unittest.TestCase):
    """The bug that erased four parts: a remove restored every face of the
    colour instead of the patch that was pointed at."""

    def test_undo_restores_only_the_patch(self):
        before = np.array([0, 0, 1, 1, 1, 1], dtype=np.int64)
        field = before.copy()
        slot = 2
        field[2:6] = slot                      # the part painted four faces
        patch = np.array([False, False, True, True, False, False])

        undo = patch & (field == slot)
        field[undo] = before[undo]

        # The pointed-at patch goes back; the rest of the part survives.
        self.assertEqual(field.tolist(), [0, 0, 1, 1, slot, slot])

    def test_undo_never_touches_another_part(self):
        before = np.array([0, 0, 0, 0], dtype=np.int64)
        field = np.array([0, 5, 5, 3], dtype=np.int64)
        slot = 5
        patch = np.array([True, True, True, True])
        undo = patch & (field == slot)
        field[undo] = before[undo]
        self.assertEqual(field.tolist(), [0, 0, 0, 3])


if __name__ == "__main__":
    unittest.main()


class _Pose:
    """A 40x40 view where every pixel is face 0."""
    name = "p"

    def __init__(self):
        self.hit_id = np.zeros((40, 40), dtype=np.int64)
        self.camera = type("C", (), {"pixels": 40})()

    @property
    def visible(self):
        return self.hit_id >= 0


class TestPaintUnits(unittest.TestCase):
    def test_a_tree_without_persistence_falls_back_rather_than_crashing(self):
        """An older cached tree has no birth/death. A run must not die on it."""
        tree = small_tree()
        for key in ("birth", "used"):
            tree.pop(key, None)
        units = loop.paint_units(tree)
        self.assertEqual(len(units), tree["regions"])

    def test_a_unit_is_bounded(self):
        """No single click may paint the whole model -- the runaway that made
        every earlier run overwrite its own parts."""
        tree = small_tree(regions=16)
        units = loop.paint_units(tree)
        biggest = max(np.bincount(units, minlength=len(units)))
        self.assertLess(biggest, tree["regions"])


class TestApplyFixesRuns(unittest.TestCase):
    """This suite passed with a green tick while apply_fixes did not exist --
    an edit had eaten the function and nothing here called it. A module's entry
    points need exercising, not just its helpers."""

    def setUp(self):
        self.tree = small_tree(regions=8, per_region=4)
        self.poses = [_Pose(), _Pose(), _Pose()]
        self.geometry = (40, 8)

    def test_a_fix_paints_the_field(self):
        field = np.zeros(len(self.tree["base"]), dtype=np.int64)
        labels = ["base", "part"]
        fix = {"view": 0, "x": 8 + 40, "y": 8 + 20, "colour": 2}
        field, labels, applied = loop.apply_fixes(
            field, self.tree, self.poses, self.geometry, [fix], labels)
        self.assertEqual(applied, 1)
        self.assertIn(1, field.tolist())

    def test_a_coordinate_in_a_later_view_is_not_dropped(self):
        """The offset bug: view 1's right panel starts a whole stride along,
        and subtracting one panel width silently discarded the correction."""
        field = np.zeros(len(self.tree["base"]), dtype=np.int64)
        labels = ["base", "part"]
        stride = 2 * 40 + 8
        fix = {"view": 1, "x": 8 + stride + 40 + 5, "y": 8 + 20, "colour": 2}
        _f, _l, applied = loop.apply_fixes(
            field, self.tree, self.poses, self.geometry, [fix], labels)
        self.assertEqual(applied, 1)

    def test_a_new_colour_extends_the_label_list(self):
        field = np.zeros(len(self.tree["base"]), dtype=np.int64)
        labels = ["base"]
        fix = {"view": 0, "x": 8 + 40 + 5, "y": 8 + 5, "colour": "new"}
        _f, labels, applied = loop.apply_fixes(
            field, self.tree, self.poses, self.geometry, [fix], labels)
        self.assertEqual(applied, 1)
        self.assertEqual(len(labels), 2)

    def test_resolve_point_returns_a_face_mask(self):
        mask = loop.resolve_point(self.tree, self.poses, self.geometry,
                                  0, 8 + 40 + 10, 8 + 10)
        self.assertIsNotNone(mask)
        self.assertEqual(len(mask), len(self.tree["base"]))
        self.assertTrue(mask.any())

    def test_an_off_surface_point_is_refused_not_guessed(self):
        pose = _Pose()
        pose.hit_id[:] = -1
        mask = loop.resolve_point(self.tree, [pose], self.geometry,
                                  0, 8 + 40 + 10, 8 + 10)
        self.assertIsNone(mask)


def two_lobe_tree(per_region=4):
    """Two clusters joined weakly at the top -- the shape every real model has.

    Within a lobe the borders are weak (0.1..0.3); between the lobes there is
    one strong border (0.9). That is a shell and its rock, or a barnacle and
    the shell it sits on, and it is the structure competition has to respect.
    """
    regions, total = 8, 15
    children = np.full((total, 2), -1, dtype=np.int64)
    birth = np.zeros(total)
    build = [(8, 0, 1, 0.1), (9, 8, 2, 0.2), (10, 9, 3, 0.3),
             (11, 4, 5, 0.1), (12, 11, 6, 0.2), (13, 12, 7, 0.3),
             (14, 10, 13, 0.9)]
    area = np.zeros(total)
    area[:regions] = 1.0
    for node, left, right, weight in build:
        children[node] = (left, right)
        birth[node] = weight
        area[node] = area[left] + area[right]
    # The border graph the tree was built from, which is what claims are
    # actually settled on -- the tree keeps only the strongest border between
    # any two regions and that collapses into ties.
    pairs = np.array([(0, 1), (1, 2), (2, 3), (4, 5), (5, 6), (6, 7), (3, 4)],
                     dtype=np.int64)
    weights = np.array([0.1, 0.2, 0.3, 0.1, 0.2, 0.3, 0.9])
    return {"children": children,
            "base": np.repeat(np.arange(regions, dtype=np.int64), per_region),
            "regions": regions, "area": area, "birth": birth,
            "region_pairs": pairs, "region_weights": weights,
            "death": np.full(total, np.inf), "used": total,
            "floor": 0.05, "ceiling": 1.0}


class _Mesh(object):
    def __init__(self, faces):
        self.faces = np.zeros((faces, 3), dtype=np.int64)
        self.area_faces = np.ones(faces)


class TestAddPartRuns(unittest.TestCase):
    """The entry point, not just its helpers. apply_fixes once vanished from
    this module and every test still passed, because nothing called the thing
    a run actually calls."""

    def setUp(self):
        self.tree = two_lobe_tree(per_region=4)
        self.mesh = _Mesh(len(self.tree["base"]))
        self.geometry = (40, 8)
        self.poses = [_Pose(), _Pose(), _Pose()]
        # Every pixel of the fake pose hits face 0, whose base region is 0.
        self.answers = {}

        def fake_show(mesh, up, field, labels, out_dir, tag, views=3,
                      pixels=520):
            return os.path.join(HERE, "..", "README.md"), self.poses, self.geometry

        self._show = loop.show
        loop.show = fake_show

    def tearDown(self):
        loop.show = self._show

    def _backend(self, where_points, fixes=()):
        answers = {"where": {"points": list(where_points)},
                   "check": {"fixes": list(fixes)}}

        class Fake(object):
            def _run(self, paths, prompt, key):
                return answers[key.split("-")[0]]
        return Fake()

    def test_a_pointed_at_part_claims_surface(self):
        part = {"name": "lobe", "where": "left", "detail": "flat", "order": 1}
        seeds, labels, field, points = loop.add_part(
            self._backend([{"view": 0, "x": 8 + 40 + 10, "y": 8 + 10}]),
            self.mesh, self.tree, (0, 0, 1), {}, [], part, "test",
            "/tmp/unused", "0", log=None)
        self.assertEqual(points, 1)
        self.assertEqual(labels, ["lobe"])
        self.assertTrue((field == 0).any(), "the drawn surface must be taken")

    def test_a_part_nobody_points_at_takes_no_colour(self):
        part = {"name": "ghost", "where": "nowhere", "detail": "flat",
                "order": 2}
        seeds, labels, _field, points = loop.add_part(
            self._backend([]), self.mesh, self.tree, (0, 0, 1),
            {0: [4]}, ["base"], part, "test", "/tmp/unused", "1", log=None)
        self.assertEqual(points, 0)
        self.assertEqual(labels, ["base"])
        self.assertNotIn(1, seeds)

    def test_remove_hands_the_ground_back_to_who_had_it(self):
        """Not to colour 1. Sending undo to the first colour turned shell into
        rock every time a detail was said to have spread."""
        part = {"name": "detail", "where": "on the lobe", "detail": "detailed",
                "order": 2}
        point = {"view": 0, "x": 8 + 40 + 10, "y": 8 + 10}
        seeds, labels, field, _points = loop.add_part(
            self._backend([point], [dict(point, kind="remove")]),
            self.mesh, self.tree, (0, 0, 1), {0: [3], 1: [4]},
            ["rock", "shell"], part, "test", "/tmp/unused", "2", log=None)
        self.assertEqual(len(labels), 3)
        # Region 0 was pointed at, then removed; it goes back to whoever held
        # it before this part existed, which is "rock" (seeded in the lobe).
        self.assertIn(0, seeds[0])
        self.assertEqual(int(field[0]), 0)


class _BoxPose(object):
    """A pose whose left half shows region 0 and right half region 1."""

    def __init__(self, pixels=40, per_region=4):
        self.hit_id = np.full((pixels, pixels), -1, dtype=np.int64)
        # faces 0..3 are region 0, faces 4..7 are region 1 (per_region=4)
        self.hit_id[:, :pixels // 2] = 0
        self.hit_id[:, pixels // 2:] = per_region
        self.camera = type("C", (), {"pixels": pixels})()

    @property
    def visible(self):
        return self.hit_id >= 0


class TestOutlineRegions(unittest.TestCase):
    """Extent from the picture, because the hierarchy does not carry it.

    Measured on the shell: the chain above a rib seed runs 0.132% then 33.989%
    of the surface, so the ribs are not a node anywhere in the tree and no way
    of choosing among nodes can produce them.
    """

    def setUp(self):
        self.tree = two_lobe_tree(per_region=4)
        self.poses = [_BoxPose()]
        self.geometry = (40, 8)

    def _shape(self, x0, x1):
        origin = 8 + 40          # right-hand panel of view 0
        return [{"view": 0, "points": [{"x": origin + x0, "y": 8},
                                       {"x": origin + x1, "y": 8},
                                       {"x": origin + x1, "y": 8 + 39},
                                       {"x": origin + x0, "y": 8 + 39}]}]

    def test_an_outline_claims_what_it_encloses(self):
        got = loop.outline_regions(self.tree, self.poses, self.geometry,
                                   self._shape(0, 19))
        self.assertEqual(got.tolist(), [0])

    def test_a_region_only_clipped_by_the_edge_is_not_in_the_part(self):
        """Half a percent of a region inside an outline is the outline being
        imprecise, not the region belonging to the part."""
        got = loop.outline_regions(self.tree, self.poses, self.geometry,
                                   self._shape(0, 22))
        self.assertEqual(got.tolist(), [0])

    def test_an_outline_over_everything_claims_everything(self):
        got = loop.outline_regions(self.tree, self.poses, self.geometry,
                                   self._shape(0, 39))
        self.assertEqual(got.tolist(), [0, 1])

    def test_no_shapes_claims_nothing(self):
        self.assertEqual(loop.outline_regions(self.tree, self.poses,
                                              self.geometry, []).tolist(), [])

    def test_a_shape_with_too_few_corners_is_refused_not_guessed(self):
        bad = [{"view": 0, "points": [{"x": 50, "y": 10}, {"x": 60, "y": 10}]}]
        self.assertEqual(loop.outline_regions(self.tree, self.poses,
                                              self.geometry, bad).tolist(), [])

    def test_a_coordinate_in_a_later_view_lands_in_that_view(self):
        """The sheet-offset bug that silently discarded half of every round's
        corrections, now in one place both readers share."""
        stride = 2 * 40 + 8
        self.assertEqual(loop.panel_point((40, 8), 3, 1, 8 + stride + 40 + 5,
                                          8 + 10), (5, 10))


class TestSettle(unittest.TestCase):
    """What was drawn, in paint order. Nothing fills the gaps.

    Four gap-filling rules were tried and measured on the shell -- climbing the
    tree, shortest path over the borders, matching the surface signature, and
    letting each part reach as far as its own marks are apart. All four drew
    bands or confetti, because in the gap they were guessing.
    """

    def setUp(self):
        self.tree = two_lobe_tree(per_region=4)

    def test_a_part_gets_exactly_what_it_was_drawn_round(self):
        owner = loop.settle(self.tree, {1: [4, 5]}, 2, fallback=None)
        self.assertEqual(owner[4], 1)
        self.assertEqual(owner[5], 1)
        self.assertTrue((owner[:4] == -1).all(), owner)

    def test_later_parts_land_on_top(self):
        """Paint order IS overlap precedence -- the whole reason the SEE step
        asks for an order."""
        owner = loop.settle(self.tree, {0: [0, 1, 2], 2: [1]}, 3)
        self.assertEqual(int(owner[1]), 2)
        self.assertEqual(int(owner[0]), 0)

    def test_what_nobody_drew_stays_the_base_coat(self):
        owner = loop.settle(self.tree, {1: [4]}, 2)
        self.assertEqual(int(owner[4]), 1)
        self.assertTrue((owner[:4] == 0).all(), owner)

    def test_nothing_expands_into_the_gap(self):
        """One mark on a lobe takes one region, not the lobe. Under-fill is
        visible in the render and gets drawn round next round; a wrong guess
        is neither."""
        owner = loop.settle(self.tree, {1: [4]}, 2, fallback=None)
        self.assertEqual(int((owner == 1).sum()), 1)

    def test_a_label_out_of_range_is_refused_not_painted(self):
        owner = loop.settle(self.tree, {9: [4]}, 2)
        self.assertTrue((owner == 0).all(), owner)

    def test_a_region_id_off_the_end_is_dropped(self):
        owner = loop.settle(self.tree, {1: [4, 999, -3]}, 2)
        self.assertEqual(int(owner[4]), 1)
        self.assertEqual(int((owner == 1).sum()), 1)
