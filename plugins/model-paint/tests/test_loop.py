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
