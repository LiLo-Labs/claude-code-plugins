"""Tests for the rig: lighting that carries signal, coverage that is a guarantee,
and the solver that replaced a hand-set merge threshold.

Two of these pin failures this project has already paid for. A lighting whose
key is cancelled returns a picture with no evidence in it and reads as a real
look (circumstance 12). A coverage plan that silently stops short leaves
features visible in too few views to ever clear consensus, which is what made
recall the limiting factor on the dragon.
"""

import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from paintpipe import rig, segment3d                      # noqa: E402


def ball(subdivisions=2, radius=10.0):
    import trimesh
    return trimesh.creation.icosphere(subdivisions=subdivisions, radius=radius)


def flat_tree(mesh, regions=8):
    """A cheap partition standing in for the scale-space index's regions."""
    centres = mesh.triangles.mean(axis=1)
    order = np.argsort(centres[:, 2])
    base = np.zeros(len(mesh.faces), dtype=np.int64)
    for slot, chunk in enumerate(np.array_split(order, regions)):
        base[chunk] = slot
    total = 2 * regions - 1
    children = np.full((total, 2), -1, dtype=np.int64)
    return {"children": children, "base": base, "regions": regions,
            "area": np.ones(total)}


class TestLightingCarriesSignal(unittest.TestCase):
    """Circumstance 12: a look with no variation in it is not a look."""

    def setUp(self):
        self.mesh = ball()
        self.pose = rig.poses(self.mesh, (0, 0, 1), pixels=96, per_ring=1,
                              elevations=((14.0, 0.0),))[0]

    def test_every_raking_lighting_varies_across_the_surface(self):
        for name in ("raking_l", "raking_t", "raking_tr", "studio"):
            image = rig.light(self.pose, name)
            visible = image[self.pose.visible]
            self.assertGreater(
                float(visible.max() - visible.min()), 0.05,
                "%s is flat -- it returns a picture carrying no relief "
                "information, which is exactly the raking_b defect" % name)

    def test_flat_lighting_is_deliberately_flat(self):
        image = rig.light(self.pose, "flat")
        visible = image[self.pose.visible]
        self.assertAlmostEqual(float(visible.min()), float(visible.max()), 6)

    def test_no_lighting_can_be_cancelled_by_camera_position(self):
        """The screen-basis construction is the fix. Sweep the camera all the
        way round and no direction may flatten a raking key."""
        for elevation in (-60.0, -20.0, 0.0, 35.0, 80.0):
            pose = rig.poses(self.mesh, (0, 0, 1), pixels=64, per_ring=2,
                             elevations=((elevation, 0.0),))[0]
            image = rig.light(pose, "raking_l")
            visible = image[pose.visible]
            self.assertGreater(float(visible.max() - visible.min()), 0.05,
                               "raking_l went flat at elevation %s" % elevation)


class TestCoverage(unittest.TestCase):
    def test_plan_covers_the_surface_and_stops(self):
        mesh = ball()
        tree = flat_tree(mesh)
        directions, covered, areas = rig.plan_poses(
            mesh, tree, (0, 0, 1), target_views=2, budget=12, candidates=16,
            scout_pixels=96)
        self.assertGreater(len(directions), 0)
        self.assertLessEqual(len(directions), 12)
        # A convex ball is easy: every region should reach the target.
        self.assertGreaterEqual(int(covered.min()), 2)

    def test_budget_is_respected(self):
        mesh = ball()
        tree = flat_tree(mesh, regions=16)
        directions, _covered, _areas = rig.plan_poses(
            mesh, tree, (0, 0, 1), target_views=8, budget=3, candidates=12,
            scout_pixels=96)
        self.assertLessEqual(len(directions), 3)

    def test_a_direction_is_never_chosen_twice(self):
        mesh = ball()
        tree = flat_tree(mesh)
        directions, _c, _a = rig.plan_poses(
            mesh, tree, (0, 0, 1), target_views=4, budget=10, candidates=12,
            scout_pixels=96)
        seen = {tuple(np.round(d, 9)) for d in directions}
        self.assertEqual(len(seen), len(directions))

    def test_plan_and_audit_report_the_same_statistic(self):
        """Found on the dragon: the plan said 92.3% covered and the audit said
        65.3%, and neither was wrong -- one was area-weighted, the other
        counted regions. Two numbers both called coverage that cannot be
        compared hide whether the plan delivered what it promised."""
        areas = np.array([100.0, 1.0, 1.0, 1.0])
        counted = np.array([3, 0, 0, 0])
        report = rig.coverage_report(counted, areas, target_views=3)
        # Area-weighted and region-counted must both be reported, and they
        # must be allowed to differ wildly without either being a lie.
        self.assertAlmostEqual(report["area_share_met"], 100.0 / 103.0, 6)
        self.assertAlmostEqual(report["region_share_met"], 0.25, 6)
        self.assertEqual(report["unreachable_regions"], 3)

    def test_unreachable_surface_is_reported_not_counted_as_shortfall(self):
        """A print-in-place model has real interior faces between its joints.
        Counting them against coverage makes every articulated model look
        uncovered forever, however many views are bought."""
        areas = np.array([10.0, 10.0, 5.0])
        counted = np.array([4, 4, 0])
        report = rig.coverage_report(counted, areas, target_views=3)
        self.assertEqual(report["unreachable_regions"], 1)
        self.assertAlmostEqual(report["unreachable_area_share"], 0.2, 6)
        self.assertAlmostEqual(report["area_share_met"], 0.8, 6)

    def test_coverage_audit_agrees_with_the_plan(self):
        """plan_poses scouts at low resolution; coverage() measures the real
        poses. They must not disagree about whether the model was covered."""
        mesh = ball()
        tree = flat_tree(mesh)
        directions, _covered, _areas = rig.plan_poses(
            mesh, tree, (0, 0, 1), target_views=2, budget=8, candidates=16,
            scout_pixels=96)
        made = rig.poses_from(mesh, directions, (0, 0, 1), pixels=128)
        counted = rig.coverage(made, tree)
        self.assertGreaterEqual(int(counted.min()), 2)


class TestEdgeEvidence(unittest.TestCase):
    def test_shapes_and_unseen_pairs(self):
        mesh = ball(subdivisions=1)
        evidence = rig.edge_evidence(mesh, pixels=128,
                                     directions=[[0, 0, -1], [0, 0, 1]],
                                     lightings=("raking_l",))
        pairs = len(mesh.face_adjacency)
        self.assertEqual(evidence["evidence"].shape,
                         (len(rig.EVIDENCE_BLURS), pairs))
        self.assertEqual(evidence["seen"].shape, (pairs,))
        self.assertGreater(int((evidence["seen"] > 0).sum()), 0)

    def test_an_unseen_pair_stays_unseen(self):
        """Interior pairs must contribute nothing rather than a zero, or every
        enclosed cavity merges into whatever surrounds it."""
        mesh = ball(subdivisions=1)
        evidence = rig.edge_evidence(mesh, pixels=64,
                                     directions=[[0, 0, -1]],
                                     lightings=("raking_l",))
        unseen = evidence["seen"] == 0
        if unseen.any():
            self.assertTrue(np.all(evidence["evidence"][:, unseen] == 0))


class TestSolveBaseK(unittest.TestCase):
    """A line of faces whose weights step up in the middle."""

    def graph(self, count=64):
        pairs = np.stack([np.arange(count - 1), np.arange(1, count)], axis=1)
        weights = np.linspace(0.1, 4.0, count - 1)
        return pairs, weights, count

    def test_region_count_falls_as_k_rises(self):
        """Monotonicity is what makes the bisection valid at all."""
        import index_regions
        pairs, weights, count = self.graph()
        counts = [int(index_regions.felzenszwalb(pairs, weights, count, k,
                                                 1).max()) + 1
                  for k in (0.05, 0.5, 5.0, 50.0)]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_solver_lands_near_the_target(self):
        pairs, weights, count = self.graph()
        k, labels = segment3d.solve_base_k(pairs, weights, count, 1, 8)
        found = int(labels.max()) + 1
        self.assertLessEqual(abs(found - 8), 3)
        self.assertGreater(k, 0.0)

    def test_an_unreachable_target_reports_rather_than_pinning(self):
        """Asking for more regions than the mesh can express must return the
        finest it has, not an endpoint dressed up as a solution."""
        pairs, weights, count = self.graph(count=8)
        _k, labels = segment3d.solve_base_k(pairs, weights, count, 1, 500)
        self.assertLessEqual(int(labels.max()) + 1, 8)


class TestCalibrate(unittest.TestCase):
    def test_min_faces_tracks_the_nozzle_not_the_triangle_count(self):
        # Fine enough that the physical floor actually binds: on a coarse mesh
        # a single triangle is already wider than the nozzle, both answers
        # clamp to the minimum, and the test would pass or fail on tessellation
        # rather than on the quantity it means to check.
        mesh = ball(subdivisions=5, radius=20.0)
        index = {"characteristic_mm": np.full(len(mesh.faces), 4.0)}
        coarse, _t = segment3d.calibrate(mesh, index, nozzle_mm=0.8)
        fine, _t2 = segment3d.calibrate(mesh, index, nozzle_mm=0.2)
        self.assertGreater(coarse, fine)

    def test_a_mesh_too_coarse_to_resolve_the_nozzle_clamps_to_the_floor(self):
        """The clamp is correct behaviour and worth pinning: a region cannot be
        fewer than a few triangles however fine the nozzle is."""
        mesh = ball(subdivisions=2, radius=20.0)
        index = {"characteristic_mm": np.full(len(mesh.faces), 4.0)}
        min_faces, _t = segment3d.calibrate(mesh, index, nozzle_mm=0.1)
        self.assertEqual(min_faces, 4)

    def test_report_carries_the_scale_facts_it_measured(self):
        """calibrate reports rather than derives base_k -- the measurement that
        refused a derived value is written up in its docstring. What it must
        still do is hand back the quantities that measurement was about."""
        small = ball(subdivisions=2, radius=10.0)
        large = ball(subdivisions=2, radius=40.0)
        index_s = {"characteristic_mm": np.full(len(small.faces), 2.0)}
        index_l = {"characteristic_mm": np.full(len(large.faces), 3.0)}
        _m, small_report = segment3d.calibrate(small, index_s)
        _m2, large_report = segment3d.calibrate(large, index_l)
        self.assertGreater(large_report["surface_mm2"],
                           small_report["surface_mm2"])
        self.assertAlmostEqual(small_report["fine_radius_mm"], 2.0, 3)
        self.assertAlmostEqual(large_report["quartile_radius_mm"], 3.0, 3)


if __name__ == "__main__":
    unittest.main()


class TestCeiling(unittest.TestCase):
    """The base-region ceiling: a boundary inside a region cannot be expressed
    by any union of regions, so the survey can never reach it however well it
    looks. These pin the detection and the local re-cut that lowers it."""

    def strip(self, faces=40):
        """A line of faces, split into two regions, with a strong camera edge
        hidden in the middle of the first one."""
        pairs = np.stack([np.arange(faces - 1), np.arange(1, faces)], axis=1)
        base = np.zeros(faces, dtype=np.int64)
        base[faces // 2:] = 1
        strength = np.full((3, faces - 1), 0.01)
        seen = np.ones(faces - 1)
        strength[:, faces // 4] = 10.0        # a bright edge inside region 0
        return pairs, base, {"evidence": strength, "seen": seen}

    def test_a_hidden_edge_is_found(self):
        pairs, base, evidence = self.strip()
        hidden, _cut = segment3d.hidden_edges(base, pairs, evidence)
        self.assertTrue(hidden.any())
        # It is inside region 0, not on the boundary between 0 and 1.
        found = pairs[hidden]
        self.assertTrue(np.all(base[found[:, 0]] == base[found[:, 1]]))

    def test_an_edge_already_on_a_boundary_is_not_hidden(self):
        pairs, base, evidence = self.strip()
        # Move the bright edge onto the region boundary; nothing is hidden now.
        evidence["evidence"][:] = 0.01
        evidence["evidence"][:, len(base) // 2 - 1] = 10.0
        hidden, _cut = segment3d.hidden_edges(base, pairs, evidence)
        self.assertFalse(hidden.any())

    def test_an_unseen_pair_cannot_hide_anything(self):
        """No observation means no contradiction. A pair nothing looked at is
        not evidence that the substrate is wrong."""
        pairs, base, evidence = self.strip()
        evidence["seen"][:] = 0.0
        hidden, _cut = segment3d.hidden_edges(base, pairs, evidence)
        self.assertFalse(hidden.any())

    def test_splitting_lowers_the_ceiling(self):
        pairs, base, evidence = self.strip(faces=60)
        weights = np.full(len(pairs), 0.1)
        weights[len(pairs) // 4] = 9.0
        areas = np.ones(60)
        refined, report = segment3d.split_hidden(
            base, pairs, weights, areas, evidence, min_faces=2, base_k=15.0,
            min_hidden=1)
        self.assertGreater(int(refined.max()) + 1, int(base.max()) + 1)
        before, _ = segment3d.hidden_edges(base, pairs, evidence)
        after, _ = segment3d.hidden_edges(refined, pairs, evidence)
        self.assertLess(int(after.sum()), int(before.sum()))

    def test_a_region_with_no_hidden_edge_is_left_alone(self):
        """Refinement is conditional. It may only add detail where something
        observed a contradiction, never everywhere."""
        pairs, base, evidence = self.strip()
        evidence["evidence"][:] = 0.01          # nothing stands out
        weights = np.full(len(pairs), 0.1)
        refined, _report = segment3d.split_hidden(
            base, pairs, weights, np.ones(len(base)), evidence, min_faces=2)
        self.assertEqual(int(refined.max()) + 1, int(base.max()) + 1)

    def test_refinement_stops_at_the_printer_floor(self):
        """A region that cannot split into parts the printer could lay down as
        separate colours is left whole: splitting it would manufacture a
        boundary finer than anything printable."""
        pairs, base, evidence = self.strip(faces=40)
        weights = np.full(len(pairs), 0.1)
        refined, _report = segment3d.split_hidden(
            base, pairs, weights, np.ones(40), evidence, min_faces=1000,
            min_hidden=1)
        self.assertEqual(int(refined.max()) + 1, int(base.max()) + 1)


class TestFrameOn(unittest.TestCase):
    """The camera goes to the part when the part is small.

    A barnacle in a 520px view of a 190mm shell is about ten pixels across,
    and nobody can draw a boundary they cannot see -- the limit is the render,
    not the loop.
    """

    def setUp(self):
        import trimesh
        # A sphere, not a box: a box's six faces are each as big as the model,
        # so framing on one cannot be tighter than framing on all of it and
        # the fixture would pass whatever the code did.
        self.mesh = trimesh.creation.icosphere(subdivisions=3, radius=50.0)

    def test_a_small_patch_gets_a_small_radius(self):
        from paintpipe import rig
        centre, radius = rig.frame_on(self.mesh, [0])
        whole = float(np.ptp(self.mesh.vertices, axis=0).max()) / 2.0 * 1.06
        self.assertIsNotNone(centre)
        self.assertLess(radius, whole,
                        "framing on one face must be tighter than the model")

    def test_the_frame_never_exceeds_the_model(self):
        from paintpipe import rig
        _c, radius = rig.frame_on(self.mesh,
                                  np.arange(len(self.mesh.faces)))
        whole = float(np.ptp(self.mesh.vertices, axis=0).max()) / 2.0 * 1.06
        self.assertLessEqual(radius, whole + 1e-6)

    def test_nothing_to_frame_is_refused_not_guessed(self):
        from paintpipe import rig
        centre, radius = rig.frame_on(self.mesh, [])
        self.assertIsNone(centre)
        self.assertIsNone(radius)

    def test_a_frame_keeps_the_neighbours_in_shot(self):
        """A boundary is a statement about two things; the other one has to be
        visible to place it."""
        from paintpipe import rig
        _c, tight = rig.frame_on(self.mesh, [0], margin=1.0)
        _c, roomy = rig.frame_on(self.mesh, [0], margin=1.35)
        self.assertGreater(roomy, tight)

    def test_framing_actually_changes_the_pixel_footprint(self):
        """It is a real camera move, not a crop: the part must occupy more of
        the frame than it did in the whole-model view."""
        from paintpipe import rig, preview
        up = (0.0, 0.0, 1.0)
        directions = preview.orbit(1, 20.0, up=up)
        wide = rig.poses_from(self.mesh, directions, up, pixels=96)[0]
        centre, radius = rig.frame_on(self.mesh, [0, 1])
        near = rig.poses_from(self.mesh, directions, up, pixels=96,
                              centre=centre, radius=radius)[0]
        self.assertLess(near.camera.footprint_mm, wide.camera.footprint_mm)
