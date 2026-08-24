"""Tests for surface over-segmentation.

The property that matters: an even tiling with no degenerate patches. The failure
this replaced produced one patch covering 60% of a model and 77% single triangles,
and both of those are visible in these numbers.
"""

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from paintlib.mesh_slic import edge_costs, superpatches                # noqa: E402


def fixture():
    import trimesh
    stl = os.path.join(os.path.dirname(HERE), "samples", "creature.stl")
    if not os.path.exists(stl):
        import subprocess
        subprocess.check_call([sys.executable,
                               os.path.join(HERE, "make_fixture.py"), stl])
    mesh = trimesh.load(stl, process=False, force="mesh").copy()
    mesh.merge_vertices()
    return mesh


class TestEdgeCosts(unittest.TestCase):
    def setUp(self):
        self.mesh = fixture()

    def test_a_crease_costs_more_than_flat_surface(self):
        """The whole method rests on this: turning the surface must be expensive."""
        costs = edge_costs(self.mesh.triangles_center, self.mesh.face_normals,
                           self.mesh.face_adjacency)
        turn = 1.0 - np.einsum(
            "ij,ij->i",
            self.mesh.face_normals[self.mesh.face_adjacency[:, 0]],
            self.mesh.face_normals[self.mesh.face_adjacency[:, 1]])
        sharp = turn > np.percentile(turn, 95)
        flat = turn < np.percentile(turn, 50)
        self.assertGreater(costs[sharp].mean(), costs[flat].mean() * 2.0)

    def test_costs_are_positive(self):
        costs = edge_costs(self.mesh.triangles_center, self.mesh.face_normals,
                           self.mesh.face_adjacency)
        self.assertTrue((costs > 0).all())


class TestSuperpatches(unittest.TestCase):
    def setUp(self):
        self.mesh = fixture()
        self.labels = superpatches(
            self.mesh.triangles_center, self.mesh.face_normals,
            self.mesh.face_adjacency, target_patches=120, iterations=2)

    def test_every_face_is_in_exactly_one_patch(self):
        self.assertEqual(len(self.labels), len(self.mesh.faces))
        self.assertTrue((self.labels >= 0).all())

    def test_no_degenerate_patches(self):
        sizes = np.bincount(self.labels)
        self.assertEqual(int((sizes == 0).sum()), 0)
        self.assertLess((sizes == 1).mean(), 0.05, "too many single-face patches")

    def test_tiling_is_even(self):
        """No patch may swallow the model, which is the failure this replaced."""
        sizes = np.bincount(self.labels)
        self.assertLess(sizes.max() / len(self.mesh.faces), 0.25)

    def test_patches_are_connected(self):
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        pairs = self.mesh.face_adjacency
        same = self.labels[pairs[:, 0]] == self.labels[pairs[:, 1]]
        graph = coo_matrix((np.ones(int(same.sum())), (pairs[same, 0], pairs[same, 1])),
                           shape=(len(self.labels),) * 2)
        total, pieces = connected_components(graph, directed=False)
        # Each patch should be one piece; the fixture's separate bodies add a few.
        self.assertLess(total, len(np.unique(self.labels)) + 12)

    def test_deterministic(self):
        again = superpatches(self.mesh.triangles_center, self.mesh.face_normals,
                             self.mesh.face_adjacency, target_patches=120, iterations=2)
        self.assertTrue((self.labels == again).all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
