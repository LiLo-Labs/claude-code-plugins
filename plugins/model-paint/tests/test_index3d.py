"""Tests for the identify loop: routing, the climb, and consensus scoring.

The climb is the part worth pinning. It answers "how big is this instance"
without a threshold, using one signal: two points in ONE view are two
instances, so any node holding both has over-merged. Get that backwards, or
drop the per-view grouping, and the failure is silent in exactly the way this
project has been bitten by before -- every instance still gets a node, the
nodes are simply too big, and the render looks plausible until a whole colony
comes back one colour.
"""

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from paintpipe import index3d, rig                        # noqa: E402


def small_tree():
    """Four regions in two pairs.

        node 6           (everything)
        /     \\
      node 4   node 5    (the two instances)
      /   \\   /   \\
     r0   r1 r2   r3     (base regions)
    """
    total = 2 * 4 - 1
    children = np.full((total, 2), -1, dtype=np.int64)
    children[4] = (0, 1)
    children[5] = (2, 3)
    children[6] = (4, 5)
    # Twelve faces, three to a region.
    base = np.repeat(np.arange(4, dtype=np.int64), 3)
    return {"children": children, "base": base, "regions": 4,
            "area": np.array([1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 4.0]),
            "node_of_atom": [4, 5]}


def points(*spec):
    """(view, region) pairs as the resolved-point dicts climb() consumes."""
    return [{"view": view, "pose": "p%d" % view, "ordinal": index,
             "region": region, "x": 0, "y": 0}
            for index, (view, region) in enumerate(spec)]


class TestAncestors(unittest.TestCase):
    def test_chain_runs_from_region_to_root(self):
        tree = small_tree()
        self.assertEqual(rig.ancestors(tree, 0), [0, 4, 6])
        self.assertEqual(rig.ancestors(tree, 3), [3, 5, 6])

    def test_node_regions_are_the_leaves_below(self):
        tree = small_tree()
        self.assertEqual(list(rig.node_regions(tree, 4)), [0, 1])
        self.assertEqual(list(rig.node_regions(tree, 6)), [0, 1, 2, 3])

    def test_face_mask_follows_the_regions(self):
        tree = small_tree()
        mask = rig.face_mask(tree, [0, 1])
        self.assertEqual(int(mask.sum()), 6)
        self.assertTrue(mask[:6].all())
        self.assertFalse(mask[6:].any())


class TestClimb(unittest.TestCase):
    def test_stops_below_a_node_that_merges_two_instances(self):
        """The rule, stated as a test: one view saw r0 and r2 as separate
        things, so node 6 -- which holds both -- is too big for either."""
        tree = small_tree()
        stopped, ladders, _ = index3d.climb(
            points((0, 0), (0, 2), (1, 1), (1, 3)), tree)
        self.assertEqual(stopped[0], 4)      # r0 climbed to its own pair
        self.assertEqual(stopped[2], 4)      # r1, from the other view, agrees
        self.assertEqual(stopped[1], 5)
        self.assertEqual(stopped[3], 5)

    def test_points_on_one_instance_fuse_with_no_matching_step(self):
        tree = small_tree()
        stopped, _, _ = index3d.climb(
            points((0, 0), (0, 2), (1, 1), (1, 3)), tree)
        instances = set(stopped.values())
        self.assertEqual(instances, {4, 5})

    def test_a_lone_instance_climbs_to_the_root_and_keeps_its_ladder(self):
        """Nothing contradicts it, so nothing stops it. That is why the ladder
        exists and why confirm_ladder is not optional in a real run."""
        tree = small_tree()
        stopped, ladders, _ = index3d.climb(points((0, 0), (1, 0)), tree)
        self.assertEqual(stopped[0], 6)
        self.assertEqual(ladders[0], [0, 4, 6])

    def test_same_view_twice_in_one_region_does_not_split_an_instance(self):
        tree = small_tree()
        resolved, missed = index3d.resolve(
            [(0, 0, 5, 5), (0, 1, 6, 6)], [_FakeView(_FakePose())],
            tree, np.zeros(12, dtype=np.int64))
        self.assertEqual(len(resolved), 1)
        self.assertEqual(missed, 0)


class _FakePose:
    """A 16x16 view of region 0 only, with a hole at the corner."""

    name = "fake"

    def __init__(self):
        self.hit_id = np.zeros((16, 16), dtype=np.int64)
        self.hit_id[0, 0] = -1
        self.hit_id[:2, 14:] = -1
        self.camera = type("C", (), {"pixels": 16})()

    @property
    def visible(self):
        return self.hit_id >= 0


class _FakeView:
    def __init__(self, pose, lighting="studio"):
        self.pose = pose
        self.lighting = lighting
        self.path = "fake-%s.png" % lighting

    @property
    def pixels(self):
        return 16


class TestRouting(unittest.TestCase):
    def test_a_hit_uses_its_own_pixel(self):
        pose, base = _FakePose(), np.array([7] * 12, dtype=np.int64)
        self.assertEqual(rig.point_to_region(pose, base, 8, 8), 7)

    def test_a_near_miss_takes_the_nearest_surface(self):
        """A coordinate one pixel off a silhouette is an aim that missed the
        edge, not an absence of feature."""
        pose, base = _FakePose(), np.array([7] * 12, dtype=np.int64)
        self.assertEqual(rig.point_to_region(pose, base, 0, 0), 7)

    def test_pointing_at_empty_space_returns_nothing(self):
        pose = _FakePose()
        pose.hit_id[:] = -1
        base = np.array([7] * 12, dtype=np.int64)
        self.assertEqual(rig.point_to_region(pose, base, 8, 8), -1)

    def test_off_frame_returns_nothing(self):
        pose, base = _FakePose(), np.array([7] * 12, dtype=np.int64)
        self.assertEqual(rig.point_to_region(pose, base, 999, 999), -1)

    def test_visible_regions_drops_slivers(self):
        pose = _FakePose()
        pose.hit_id[:] = 0
        pose.hit_id[0, :3] = 1          # three faces of another region
        base = np.array([0, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.int64)
        regions, counts = rig.visible_regions(pose, base, min_pixels=4)
        self.assertIn(0, regions.tolist())
        self.assertNotIn(5, regions.tolist())


class TestScore(unittest.TestCase):
    def test_a_node_is_only_judged_on_views_that_could_see_it(self):
        """The whole point of reading visibility off the depth buffer: an
        instance hidden in half the looks is not punished for them."""
        tree = small_tree()
        near, far = _FakePose(), _FakePose()
        near.name, far.name = "near", "far"
        near.hit_id[:] = 0              # face 0 -> region 0 -> node 4
        far.hit_id[:] = 6               # face 6 -> region 2 -> node 5
        base = np.asarray(tree["base"])
        views = [_FakeView(near), _FakeView(near, "raking_l"), _FakeView(far)]
        shown = index3d.score([4, 5], [near, far], views, tree, base)
        self.assertEqual(shown[4], 2)   # both lightings of the near pose
        self.assertEqual(shown[5], 1)

    def test_a_failed_call_is_not_counted_as_a_look_that_saw_nothing(self):
        """The bug this pins cost the fixture an eye. A call that never
        returned is not evidence of absence, so it must leave the denominator
        rather than silently making every share harsher."""
        tree = small_tree()
        near, far = _FakePose(), _FakePose()
        near.name, far.name = "near", "far"
        near.hit_id[:] = 0
        far.hit_id[:] = 0
        base = np.asarray(tree["base"])
        views = [_FakeView(near), _FakeView(near, "raking_l"), _FakeView(far)]
        everything = index3d.score([4], [near, far], views, tree, base)
        self.assertEqual(everything[4], 3)
        # The second and third looks failed; only the first answered.
        partial = index3d.score([4], [near, far], views, tree, base,
                                answered={0})
        self.assertEqual(partial[4], 1)


class TestNearestByArea(unittest.TestCase):
    """The fallback that sizes an unconfirmed group from the confirmed ones."""

    areas = np.array([1.0, 2.0, 4.0, 40.0, 400.0])

    def test_picks_the_rung_closest_in_ratio(self):
        self.assertEqual(index3d.nearest_by_area([0, 1, 2], self.areas, 3.5), 2)
        self.assertEqual(index3d.nearest_by_area([0, 1, 2], self.areas, 1.1), 0)

    def test_ratio_not_difference(self):
        """Against a target of 4, the rung at 40 is off by a factor of 10 and
        the rung at 1 by a factor of 4, so 1 wins -- even though 40 is far
        closer in absolute area terms to nothing in particular. Absolute
        difference would rank 40 as 36 away and 1 as 3 away and agree here by
        accident; the case that separates them is a target between two rungs
        spanning orders of magnitude."""
        self.assertEqual(index3d.nearest_by_area([3, 4], self.areas, 63.2), 3)
        self.assertEqual(index3d.nearest_by_area([3, 4], self.areas, 127.0), 4)

    def test_a_single_rung_is_returned_unchanged(self):
        self.assertEqual(index3d.nearest_by_area([1], self.areas, 999.0), 1)


class _StubBackend:
    """Answers some looks and fails others, the way a real one does."""

    def __init__(self, answers):
        self.answers = answers
        self.seen = []

    def _run(self, paths, prompt, key):
        self.seen.append(key)
        return self.answers.pop(0) if self.answers else None


class TestAskViews(unittest.TestCase):
    def test_failed_looks_are_reported_separately_from_empty_ones(self):
        views = [_FakeView(_FakePose(), "studio"),
                 _FakeView(_FakePose(), "raking_l"),
                 _FakeView(_FakePose(), "flat")]
        backend = _StubBackend([{"found": [{"n": 1, "x": 5, "y": 5}]},
                                {"found": []},
                                None])
        clicks, answered = index3d.ask_views(backend, views, "horn", "", "",
                                             workers=1, retries=0)
        self.assertEqual(len(clicks), 1)
        # The empty answer counts as a look; the failure does not.
        self.assertEqual(answered, {0, 1})

    def test_a_retry_recovers_a_look_instead_of_losing_it(self):
        views = [_FakeView(_FakePose(), "studio")]
        backend = _StubBackend([None, {"found": [{"n": 1, "x": 5, "y": 5}]}])
        clicks, answered = index3d.ask_views(backend, views, "horn", "", "",
                                             workers=1, retries=1)
        self.assertEqual(answered, {0})
        self.assertEqual(len(clicks), 1)


if __name__ == "__main__":
    unittest.main()
