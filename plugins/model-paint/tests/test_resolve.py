"""Tests for the partition resolver.

Written after the resolver caught a real error: 24 independently made selections
left 24.6% of a model in no part and 26.9% claimed by two or more, and a naive
single fallback then painted 42% of a rocky base as shell.
"""

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from resolve_parts import UNASSIGNED, fill_nearest, resolve      # noqa: E402


def part(name, faces, area):
    return {"name": name, "face_indices": list(faces), "area": area}


class TestResolve(unittest.TestCase):
    def test_specific_beats_general(self):
        """A small part inside a big one keeps its faces."""
        parts = [part("body", range(0, 100), 0.9), part("detail", range(40, 50), 0.1)]
        labels, _order, stolen = resolve(parts, 100)
        self.assertTrue((labels[40:50] == 1).all())
        self.assertTrue((labels[0:40] == 0).all())
        self.assertEqual(stolen[("body", "detail")], 10)

    def test_every_claimed_face_lands_somewhere(self):
        parts = [part("a", range(0, 60), 0.6), part("b", range(50, 100), 0.4)]
        labels, _order, _stolen = resolve(parts, 100)
        self.assertFalse((labels[0:100] == UNASSIGNED).any())

    def test_unclaimed_stays_unassigned_before_filling(self):
        parts = [part("a", range(0, 40), 1.0)]
        labels, _order, _stolen = resolve(parts, 100)
        self.assertTrue((labels[40:] == UNASSIGNED).all())

    def test_explicit_priority_overrides_area(self):
        parts = [part("small", range(0, 10), 0.1), part("big", range(0, 100), 0.9)]
        labels, _order, _stolen = resolve(parts, 100, priority=["small", "big"])
        self.assertTrue((labels[0:10] == 1).all(), "later part should win the overlap")

    def test_out_of_range_indices_are_ignored(self):
        parts = [part("a", [0, 1, 500, -3], 1.0)]
        labels, _order, _stolen = resolve(parts, 10)
        self.assertTrue((labels[0:2] == 0).all())
        self.assertTrue((labels[2:] == UNASSIGNED).all())


class TestFillNearest(unittest.TestCase):
    """A chain of faces: 0-1-2-3-4-5-6-7-8-9, with a gap in the middle."""

    def setUp(self):
        self.pairs = np.array([[i, i + 1] for i in range(9)])

    def test_gap_is_filled_from_both_sides(self):
        labels = np.full(10, UNASSIGNED, dtype=np.int32)
        labels[0] = 0
        labels[9] = 1
        filled = fill_nearest(labels, self.pairs)
        self.assertFalse((filled == UNASSIGNED).any())
        self.assertTrue((filled[:5] == 0).all(), "near end should take part 0")
        self.assertTrue((filled[5:] == 1).all(), "far end should take part 1")

    def test_a_gap_takes_the_part_that_borders_it(self):
        """The failure that motivated this: a hole in the rock must become rock.

        With a single global fallback the whole gap went to whichever part was
        named, which painted a rocky base as shell.
        """
        labels = np.full(10, UNASSIGNED, dtype=np.int32)
        labels[0] = 0          # "shell", far away
        labels[7] = 1          # "rock", adjacent to the gap
        filled = fill_nearest(labels, self.pairs)
        self.assertEqual(filled[8], 1)
        self.assertEqual(filled[9], 1)
        self.assertEqual(filled[6], 1)

    def test_already_assigned_faces_are_never_changed(self):
        labels = np.array([0, 0, UNASSIGNED, 1, 1, UNASSIGNED, 2, 2, 2, 2], dtype=np.int32)
        filled = fill_nearest(labels, self.pairs)
        for index in (0, 1, 3, 4, 6, 7, 8, 9):
            self.assertEqual(filled[index], labels[index])

    def test_isolated_faces_stay_unassigned(self):
        """An island with no assigned neighbour cannot be filled, and must not lie."""
        labels = np.full(4, UNASSIGNED, dtype=np.int32)
        labels[0] = 0
        pairs = np.array([[0, 1], [2, 3]])      # 2 and 3 are a separate island
        filled = fill_nearest(labels, pairs)
        self.assertEqual(filled[1], 0)
        self.assertTrue((filled[2:] == UNASSIGNED).all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
