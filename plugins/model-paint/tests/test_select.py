"""Tests for local growth and the edge-strength wall that bounds it.

Written against a measured failure: with the old statistic -- how often an ensemble
kept two faces in the same patch -- 0.0% of pairs on the shell fell below the
blocking threshold, so blocking was wired up, enabled by default, and did nothing.
One click still ran away across 28.06% of the model. These tests pin the direction
of the comparison, because getting it backwards fails exactly that quietly: growth
still works, selections still look plausible, and the wall is simply never there.
"""

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from patch_select import grow_local, patch_contacts      # noqa: E402


def chain(count):
    """Patches 0..count-1 in a line, each touching the next."""
    touching = {}
    for patch in range(count - 1):
        touching.setdefault(patch, set()).add(patch + 1)
        touching.setdefault(patch + 1, set()).add(patch)
    return touching


class TestGrowLocal(unittest.TestCase):
    def test_spreads_through_similar_patches(self):
        similar = np.ones(5, dtype=bool)
        keep = grow_local([0], similar, chain(5), {}, 1000.0)
        self.assertTrue(keep.all())

    def test_stops_at_dissimilar_patches(self):
        similar = np.array([True, True, False, True, True])
        keep = grow_local([0], similar, chain(5), {}, 1000.0)
        self.assertTrue((keep == [True, True, False, False, False]).all())

    def test_a_coarse_edge_blocks_growth(self):
        """An edge that already comes apart at 250 patches is real structure."""
        similar = np.ones(5, dtype=bool)
        keep = grow_local([0], similar, chain(5), {(1, 2): 250.0}, 1000.0)
        self.assertTrue((keep == [True, True, False, False, False]).all())

    def test_a_fine_edge_does_not_block(self):
        """One appearing only at 4,600 is the segmentation running out of cuts."""
        similar = np.ones(5, dtype=bool)
        keep = grow_local([0], similar, chain(5), {(1, 2): 4600.0}, 1000.0)
        self.assertTrue(keep.all())

    def test_direction_of_the_comparison(self):
        """Low strength blocks, high strength does not -- not the other way round.

        The bug this guards against is inheriting the old statistic's direction,
        where a *high* score meant a boundary. Under that reading these two
        assertions swap, and nothing else in the pipeline notices.
        """
        similar = np.ones(3, dtype=bool)
        major = grow_local([0], similar, chain(3), {(0, 1): 250.0}, 1000.0)
        minor = grow_local([0], similar, chain(3), {(0, 1): 4600.0}, 1000.0)
        self.assertEqual(int(major.sum()), 1)
        self.assertEqual(int(minor.sum()), 3)

    def test_threshold_boundary_is_inclusive(self):
        """A contact exactly at the threshold blocks; the help text says 'or coarser'."""
        similar = np.ones(3, dtype=bool)
        keep = grow_local([0], similar, chain(3), {(0, 1): 1000.0}, 1000.0)
        self.assertEqual(int(keep.sum()), 1)

    def test_unmeasured_contacts_let_growth_through(self):
        """Absent strengths default to infinity, never to a silent wall."""
        similar = np.ones(4, dtype=bool)
        keep = grow_local([0], similar, chain(4), {(2, 3): 250.0}, 1000.0)
        self.assertTrue((keep == [True, True, True, False]).all())

    def test_disabled_blocking_ignores_strengths(self):
        similar = np.ones(4, dtype=bool)
        keep = grow_local([0], similar, chain(4), {}, 0.0)
        self.assertTrue(keep.all())


class TestPatchContacts(unittest.TestCase):
    def setUp(self):
        # Six faces, two patches of three, touching along one pair of faces.
        self.labels = np.array([0, 0, 0, 1, 1, 1])
        self.pairs = np.array([[0, 1], [1, 2], [2, 3], [3, 4], [4, 5]])

    def test_finds_the_contact_and_ignores_interior_pairs(self):
        touching, strengths = patch_contacts(self.labels, self.pairs,
                                             np.array([np.inf, np.inf, 400.0,
                                                       np.inf, np.inf]))
        self.assertEqual(touching, {0: {1}, 1: {0}})
        self.assertEqual(strengths, {(0, 1): 400.0})

    def test_no_strengths_gives_contacts_only(self):
        touching, strengths = patch_contacts(self.labels, self.pairs, None)
        self.assertEqual(touching, {0: {1}, 1: {0}})
        self.assertEqual(strengths, {})

    def test_median_survives_never_separating_pairs(self):
        """A mean would return infinity here; the contact is genuinely major."""
        labels = np.array([0, 0, 1, 1])
        pairs = np.array([[0, 2], [1, 3], [0, 3]])
        _touching, strengths = patch_contacts(labels, pairs,
                                              np.array([250.0, 400.0, np.inf]))
        self.assertEqual(strengths[(0, 1)], 400.0)

    def test_a_contact_that_mostly_never_separates_is_not_an_edge(self):
        labels = np.array([0, 0, 1, 1])
        pairs = np.array([[0, 2], [1, 3], [0, 3]])
        _touching, strengths = patch_contacts(labels, pairs,
                                              np.array([250.0, np.inf, np.inf]))
        self.assertEqual(strengths[(0, 1)], np.inf)


if __name__ == "__main__":
    unittest.main()
