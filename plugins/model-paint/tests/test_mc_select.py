"""Tests for Monte Carlo consensus selection.

The claim being tested is the one the whole approach rests on: a face reached in
every draw scores 1.0, a face reached in a minority scores below any sensible
threshold, and the threshold therefore separates a stable core from a drift tail.

Built on a synthetic strip rather than a real model, because what needs pinning is
the accounting -- votes land on the right faces, probabilities are a fraction of
runs, patch ids are never compared across runs -- not whether the shell's barnacles
come out right. That question is settled by the click trial, not by a unit test.
"""

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from mc_select import vote                                        # noqa: E402


def strip(count):
    """A chain of `count` triangles, each sharing an edge with the next."""
    vertices = []
    faces = []
    for i in range(count):
        vertices.extend([[float(i), 0.0, 0.0], [float(i) + 1, 0.0, 0.0],
                         [float(i), 1.0, 0.0]])
        faces.append([3 * i, 3 * i + 1, 3 * i + 2])
    vertices = np.array(vertices, dtype=np.float32)
    faces = np.array(faces, dtype=np.int32)
    pairs = np.array([[i, i + 1] for i in range(count - 1)], dtype=np.int32)
    return {
        "vertices": vertices,
        "faces": faces,
        "normals": np.tile(np.array([0.0, 0.0, 1.0], np.float32), (count, 1)),
        "areas": np.ones(count, dtype=np.float32),
        "pairs": pairs,
    }


def flat_fields(count):
    return {name: np.zeros(count, dtype=np.float32)
            for name in ("relief", "occlusion", "roughness", "thickness")}


class TestVote(unittest.TestCase):
    def setUp(self):
        self.count = 12
        self.session = strip(self.count)
        self.fields = flat_fields(self.count)

    def test_probability_is_a_fraction_of_runs(self):
        """Identical draws give a deterministic answer: every face 0.0 or 1.0."""
        labels = np.arange(self.count, dtype=np.int32)
        mc = np.tile(labels, (5, 1))
        probability = vote(self.session, mc, self.fields, [0],
                           tolerance=1.0, jitter=0.0, seed=1)
        self.assertTrue(((probability == 0.0) | (probability == 1.0)).all())
        self.assertGreaterEqual(probability[0], 1.0)

    def test_bounded_between_zero_and_one(self):
        mc = np.stack([np.arange(self.count, dtype=np.int32) // (run + 1)
                       for run in range(4)])
        probability = vote(self.session, mc, self.fields, [0],
                           tolerance=0.4, jitter=0.3, seed=2)
        self.assertTrue((probability >= 0.0).all())
        self.assertTrue((probability <= 1.0).all())

    def test_the_clicked_face_is_always_selected(self):
        """It is its own exemplar in every draw, whatever the tiling."""
        mc = np.stack([np.arange(self.count, dtype=np.int32) // (run + 1)
                       for run in range(4)])
        probability = vote(self.session, mc, self.fields, [5],
                           tolerance=0.2, jitter=0.2, seed=3)
        self.assertEqual(probability[5], 1.0)

    def test_a_split_alone_does_not_stop_growth(self):
        """Resegmenting is not by itself a wall, and it must not be mistaken for one.

        Two patches that touch and look alike are still grown across -- that is the
        whole point of growth. So a draw that merely cuts the strip in half changes
        nothing, and the ensemble cannot help when every patch along a chain
        genuinely resembles its neighbour. It helps only where membership is
        marginal enough to flip between draws.
        """
        split = np.array([0] * 6 + [1] * 6, dtype=np.int32)
        probability = vote(self.session, np.stack([split, split]), self.fields, [0],
                           tolerance=1.0, jitter=0.0, seed=4)
        self.assertTrue((probability == 1.0).all())

    def test_a_face_selected_in_a_minority_falls_below_threshold(self):
        """The core claim: unstable membership does not survive the vote.

        The far half is made genuinely unlike the near half, so where a draw puts a
        patch boundary on that change growth stops there, and where a draw spans the
        change it does not. Six draws: two span it and four stop. The far face is
        selected twice in six, so any threshold at or above 0.5 drops it while the
        clicked face keeps 1.0.
        """
        fields = flat_fields(self.count)
        fields["roughness"] = np.array([0.0] * 6 + [1.0] * 6, dtype=np.float32)
        whole = np.zeros(self.count, dtype=np.int32)
        split = np.array([0] * 6 + [1] * 6, dtype=np.int32)
        mc = np.stack([whole, whole, split, split, split, split])
        probability = vote(self.session, mc, fields, [0],
                           tolerance=0.30, jitter=0.0, seed=4)
        self.assertAlmostEqual(probability[self.count - 1], 2.0 / 6.0, places=6)
        self.assertEqual(probability[0], 1.0)
        self.assertLess(probability[self.count - 1], 0.5)

    def test_patch_ids_are_never_compared_across_runs(self):
        """Relabelling a draw must not change the answer.

        Patch 0 in one draw has nothing to do with patch 0 in another. If the vote
        ever compared ids between runs this would shift, and the bug would be
        invisible on a real model.
        """
        split = np.array([0] * 6 + [1] * 6, dtype=np.int32)
        relabelled = np.array([7] * 6 + [3] * 6, dtype=np.int32)
        first = vote(self.session, np.stack([split, split]), self.fields, [0],
                     tolerance=1.0, jitter=0.0, seed=5)
        second = vote(self.session, np.stack([split, relabelled]), self.fields, [0],
                      tolerance=1.0, jitter=0.0, seed=5)
        self.assertTrue((first == second).all())


if __name__ == "__main__":
    unittest.main()
