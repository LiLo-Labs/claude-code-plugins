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


class _BoxPose(object):
    """A pose whose left half shows region 0 and right half region 1."""

    def __init__(self, pixels=40, per_region=4):
        self.hit_id = np.full((pixels, pixels), -1, dtype=np.int64)
        self.hit_id[:, :pixels // 2] = 0
        self.hit_id[:, pixels // 2:] = per_region
        self.camera = type("C", (), {"pixels": pixels})()

    @property
    def visible(self):
        return self.hit_id >= 0


class TestAddPartRuns(unittest.TestCase):
    """The entry point, not just its helpers. apply_fixes once vanished from
    this module and every test still passed, because nothing called the thing
    a run actually calls."""

    def setUp(self):
        self.tree = two_lobe_tree(per_region=4)
        self.mesh = _Mesh(len(self.tree["base"]))
        self.geometry = (40, 8)
        self.poses = [_BoxPose(), _BoxPose(), _BoxPose()]

        def fake_show(mesh, up, field, labels, out_dir, tag, views=3,
                      pixels=520, directions=None, colours=None, focus=None):
            return (os.path.join(HERE, "..", "README.md"), self.poses,
                    self.geometry)

        self._show = loop.show
        loop.show = fake_show

    def tearDown(self):
        loop.show = self._show

    def _backend(self, script):
        """A backend that answers a different thing on each successive look."""
        state = {"n": 0}

        class Fake(object):
            calls = []

            def _run(inner, paths, prompt, key):
                index = state["n"]
                state["n"] += 1
                inner.calls.append(key)
                if index < len(script):
                    return script[index]
                return {"add": [], "remove": []}
        return Fake()

    def _box(self, view, x0, x1):
        origin = 8 + view * (2 * 40 + 8) + 40
        return {"view": view,
                "points": [{"x": origin + x0, "y": 8},
                           {"x": origin + x1, "y": 8},
                           {"x": origin + x1, "y": 8 + 39},
                           {"x": origin + x0, "y": 8 + 39}]}

    def _part(self, name="lobe"):
        return {"name": name, "where": "left", "detail": "flat", "order": 1}

    def test_an_outline_gives_the_part_its_surface(self):
        backend = self._backend([{"add": [self._box(0, 0, 19)]}])
        seeds, labels, field, used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {}, [], self._part(),
            "test", "/tmp/unused", "0", log=None)
        self.assertEqual(labels, ["lobe"])
        self.assertIn(0, seeds[0])
        self.assertTrue((field == 0).any())
        self.assertGreaterEqual(used, 1)

    def test_it_looks_again_after_each_stroke(self):
        """The correction that matters: painting one colour is itself a loop.
        A stroke that covered half the part is SEEN to have covered half, and
        the next one covers the rest -- so no single stroke has to be right."""
        backend = self._backend([{"add": [self._box(0, 0, 19)]},
                                 {"add": [self._box(0, 20, 39)]}])
        seeds, _labels, _field, used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {}, [], self._part(),
            "test", "/tmp/unused", "0", rounds=4, log=None)
        self.assertEqual(used, 3, "two strokes, then the empty answer")
        self.assertEqual(sorted(seeds[0]), [0, 1],
                         "the second stroke added what the first missed")

    def test_an_empty_answer_is_the_finish(self):
        backend = self._backend([{"add": [self._box(0, 0, 39)]},
                                 {"add": [], "remove": []},
                                 {"add": [self._box(0, 0, 19)]}])
        _s, _l, _f, used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {}, [], self._part(),
            "test", "/tmp/unused", "0", rounds=8, log=None)
        self.assertEqual(used, 2, "it must stop being asked once it is right")

    def test_it_never_looks_more_than_its_rounds(self):
        backend = self._backend([{"add": [self._box(0, 0, 19)]}] * 20)
        _s, _l, _f, used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {}, [], self._part(),
            "test", "/tmp/unused", "0", rounds=2, log=None)
        self.assertEqual(used, 2)

    def test_unclaimed_surface_looks_unclaimed_while_working(self):
        """The base coat must not be laid during the loop. Filling the gaps
        with colour 1 makes colour 1 cover the whole model from the first
        look, so its own check has nothing to check -- measured, 25 removals
        on the rocky base changed nothing, because every one of them pointed
        at surface that had defaulted rather than been painted."""
        backend = self._backend([{"add": [self._box(0, 0, 19)]},
                                 {"add": [], "remove": []}])
        _s, _l, field, _used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {}, [], self._part(),
            "test", "/tmp/unused", "0", rounds=2, log=None)
        self.assertTrue((field < 0).any(),
                        "what was not drawn round must stay unpainted")
        self.assertTrue((field == 0).any(), "and what was drawn must be painted")

    def test_a_broad_stroke_does_not_also_get_the_fine_brush(self):
        """`not drawn` on a numpy array raises for more than one element and,
        for exactly one, asks whether that element is zero -- so a flat part
        whose only claim was region 0 silently got the fine brush too, and
        picked up its neighbour off the outline's own perimeter."""
        backend = self._backend([{"add": [self._box(0, 0, 19)]},
                                 {"add": [], "remove": []}])
        seeds, _labels, _field, _used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {}, [], self._part(),
            "test", "/tmp/unused", "0", rounds=2, log=None)
        self.assertEqual(sorted(seeds[0]), [0],
                         "an outline over region 0 alone claims region 0 alone")

    def test_a_removal_can_be_drawn_round_not_only_pointed_at(self):
        """One outline takes thousands of regions in a gesture; a removal used
        to be a single point. On the shell the agent saw its colour covering
        the whole coil, asked for seventeen removals, and took back six
        regions out of three thousand. Seeing a mistake is worthless if the
        correction cannot reach it."""
        wide = self._box(0, 0, 39)
        backend = self._backend([{"add": [wide]},
                                 {"remove": [dict(wide)]}])
        seeds, _labels, _field, _used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {0: [0], 1: [4]},
            ["rock", "shell"], self._part("detail"), "test", "/tmp/unused",
            "4", rounds=3, log=None)
        self.assertNotIn(2, seeds,
                         "an area painted wrongly must be recoverable in one "
                         "gesture, as it was laid")

    def test_a_part_nobody_finds_takes_no_colour(self):
        backend = self._backend([{"add": [], "remove": []}])
        seeds, labels, _field, _used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {0: [4]}, ["base"],
            self._part("ghost"), "test", "/tmp/unused", "1", log=None)
        self.assertEqual(labels, ["base"])
        self.assertNotIn(1, seeds)

    def test_remove_hands_the_ground_back_to_who_had_it(self):
        """Not to colour 1. Sending undo to the first colour turned shell into
        rock every time a detail was said to have spread."""
        origin = 8 + 40
        backend = self._backend([
            {"add": [self._box(0, 0, 39)]},
            {"remove": [{"view": 0, "x": origin + 5, "y": 8 + 5}]},
        ])
        seeds, labels, field, _used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {0: [0], 1: [4]},
            ["rock", "shell"], self._part("detail"), "test", "/tmp/unused",
            "2", rounds=3, log=None)
        self.assertEqual(len(labels), 3)
        self.assertNotIn(0, seeds[2], "the mark that was wrong must be dropped")
        self.assertIn(1, seeds[2], "the rest of the part must survive the undo")
        self.assertIn(0, seeds[0], "and the ground goes back to who had it")
        self.assertEqual(int(field[0]), 0)

    def test_a_part_undone_back_to_nothing_gives_its_colour_up(self):
        """A colour covering no surface is not a colour. It must not sit in
        the palette taking a filament slot."""
        origin = 8 + 40
        backend = self._backend([
            {"add": [self._box(0, 0, 19)]},
            {"remove": [{"view": 0, "x": origin + 5, "y": 8 + 5}]},
        ])
        seeds, labels, _field, _used = loop.add_part(
            backend, self.mesh, self.tree, (0, 0, 1), {0: [0], 1: [4]},
            ["rock", "shell"], self._part("detail"), "test", "/tmp/unused",
            "3", rounds=3, log=None)
        self.assertEqual(labels, ["rock", "shell"])
        self.assertNotIn(2, seeds)


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

    def test_a_barely_visible_region_is_not_decided_by_a_drawing(self):
        """A majority of three pixels is not evidence. The shell's spiral eye
        went 742 -> 3555 regions in one round while barely changing on screen:
        the extra three thousand were surfaces the drawing could hardly see."""
        pose = _BoxPose()
        pose.hit_id[:] = -1
        pose.hit_id[0, 0:3] = 0          # region 0 shows three pixels
        pose.hit_id[10:40, 20:40] = 4    # region 1 shows plenty
        # Four pixels, the same number rig.coverage uses to decide whether a
        # pose sees a region at all. Measured on the shell: across six views
        # the median region gets 42 pixels and four rejects 3.5% of them.
        got = loop.outline_regions(self.tree, [pose], self.geometry,
                                   self._shape(0, 39))
        self.assertEqual(got.tolist(), [1],
                         "three pixels is not enough to claim a surface")

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

    def test_a_view_on_the_second_row_lands_in_that_view(self):
        """Six views is what covering a model actually takes, and six pairs in
        a line is an eleven-to-one strip nobody can read. Once the sheet wraps,
        a coordinate carries a row as well as a column."""
        pixels, gap, columns = 40, 8, 3
        cell = 2 * pixels + gap
        # view 4 -> column 1, row 1
        x = gap + 1 * cell + pixels + 5
        y = gap + 1 * (pixels + 18 + gap) + 10
        self.assertEqual(loop.panel_point((pixels, gap, columns), 6, 4, x, y),
                         (5, 10))

    def test_a_sheet_that_never_wrapped_still_reads(self):
        """A two-tuple geometry is the old single-row sheet; it must keep
        working rather than silently mapping every point into row zero."""
        stride = 2 * 40 + 8
        self.assertEqual(loop.panel_point((40, 8), 3, 1, 8 + stride + 40 + 5,
                                          8 + 10), (5, 10))


class TestOutlineAcrossViews(unittest.TestCase):
    """A drawing is judged against the views it was drawn on, and no others."""

    def setUp(self):
        self.tree = two_lobe_tree(per_region=4)
        self.geometry = (40, 8, 3)

    def _shape(self, view, x0, x1):
        origin = 8 + (view % 3) * (2 * 40 + 8) + 40
        top = 8 + (view // 3) * (40 + 18 + 8)
        return {"view": view,
                "points": [{"x": origin + x0, "y": top},
                           {"x": origin + x1, "y": top},
                           {"x": origin + x1, "y": top + 39},
                           {"x": origin + x0, "y": top + 39}]}

    def test_views_never_drawn_on_do_not_veto_the_ones_that_were(self):
        """Six views and one outline used to claim nothing at all: the region
        reached a sixth of its visible pixels and lost the majority to five
        views the agent had not been asked about."""
        poses = [_BoxPose() for _ in range(6)]
        got = loop.outline_regions(self.tree, poses, self.geometry,
                                   [self._shape(0, 0, 19)])
        self.assertEqual(got.tolist(), [0])

    def test_drawing_the_same_part_in_two_views_agrees_with_itself(self):
        poses = [_BoxPose() for _ in range(6)]
        got = loop.outline_regions(self.tree, poses, self.geometry,
                                   [self._shape(0, 0, 19),
                                    self._shape(4, 0, 19)])
        self.assertEqual(got.tolist(), [0])

    def test_a_region_avoided_in_most_drawn_views_is_refused(self):
        """Disagreement between drawings is the whole point of counting across
        views rather than trusting one. Inside in one of three drawn views is
        not a majority, so it does not join the part."""
        poses = [_BoxPose() for _ in range(6)]
        got = loop.outline_regions(self.tree, poses, self.geometry,
                                   [self._shape(0, 0, 19),
                                    self._shape(4, 20, 39),
                                    self._shape(5, 20, 39)])
        self.assertEqual(got.tolist(), [1])

    def test_an_even_split_counts_as_inside(self):
        """Deliberate: the prompt tells the agent that cutting a little short
        costs nothing, so a tie has to fall its way or the advice is a trap."""
        poses = [_BoxPose() for _ in range(6)]
        got = loop.outline_regions(self.tree, poses, self.geometry,
                                   [self._shape(0, 0, 19),
                                    self._shape(4, 20, 39)])
        self.assertEqual(got.tolist(), [0, 1])


class TestStrokeRegions(unittest.TestCase):
    """The fine brush: only what the line runs over."""

    def setUp(self):
        self.tree = two_lobe_tree(per_region=4)
        self.poses = [_BoxPose()]
        self.geometry = (40, 8, 1)

    def _line(self, points):
        origin = 8 + 40
        return [{"view": 0, "points": [{"x": origin + x, "y": 8 + y}
                                       for x, y in points]}]

    def test_a_line_paints_what_it_runs_over(self):
        got = loop.stroke_regions(self.tree, self.poses, self.geometry,
                                  self._line([(2, 2), (2, 30)]))
        self.assertEqual(got.tolist(), [0])

    def test_a_line_does_not_close_back_to_its_start(self):
        """A stroke that ends far from where it began used to get a closing
        segment running straight back, painting a chord across everything
        between -- which is how a brush drawn along a crack streaked over the
        middle of the shell. The stroke here stays in region 1; only the
        return leg would cross into region 0."""
        got = loop.stroke_regions(self.tree, self.poses, self.geometry,
                                  self._line([(38, 2), (22, 2), (22, 35),
                                              (38, 35)]))
        self.assertEqual(got.tolist(), [1],
                         "the return leg must not be drawn")

    def test_a_line_crossing_a_border_takes_both_sides(self):
        got = loop.stroke_regions(self.tree, self.poses, self.geometry,
                                  self._line([(2, 20), (38, 20)]))
        self.assertEqual(got.tolist(), [0, 1])

    def test_the_brush_does_not_reach_past_the_line(self):
        """One pixel, not three. A crack region is narrow and its neighbour is
        one big smooth region, so reaching a pixel past the line hands over
        that whole neighbour."""
        got = loop.stroke_regions(self.tree, self.poses, self.geometry,
                                  self._line([(19, 2), (19, 30)]))
        self.assertEqual(got.tolist(), [0], "x=19 is region 0; x=20 is not")

    def test_a_single_point_still_marks_its_region(self):
        got = loop.stroke_regions(self.tree, self.poses, self.geometry,
                                  self._line([(30, 30)]))
        self.assertEqual(got.tolist(), [1])

    def test_corroboration_is_off_by_default(self):
        """Demanding a second view mark the SAME base region tests whether two
        lines land on the same few pixels, not whether they are right: on the
        shell it left 28 strokes along the ribs holding 43 regions."""
        poses = [_BoxPose() for _ in range(2)]
        geometry = (40, 8, 2)
        cell = 2 * 40 + 8
        shapes = [{"view": 0,
                   "points": [{"x": 8 + 40 + 2, "y": 8 + 2},
                              {"x": 8 + 40 + 2, "y": 8 + 30}]},
                  {"view": 1,
                   "points": [{"x": 8 + cell + 40 + 30, "y": 8 + 2},
                              {"x": 8 + cell + 40 + 30, "y": 8 + 30}]}]
        self.assertEqual(
            loop.stroke_regions(self.tree, poses, geometry, shapes).tolist(),
            [0, 1], "both marks stand when nothing is vetoing them")

    def test_a_mark_made_from_two_sides_is_kept(self):
        """Six views of one object: where two of them agree, that is a
        statement about the object rather than about one picture."""
        poses = [_BoxPose() for _ in range(2)]
        geometry = (40, 8, 2)
        cell = 2 * 40 + 8
        shapes = [{"view": v,
                   "points": [{"x": 8 + v * cell + 40 + 2, "y": 8 + 2},
                              {"x": 8 + v * cell + 40 + 2, "y": 8 + 30}]}
                  for v in (0, 1)]
        got = loop.stroke_regions(self.tree, poses, geometry, shapes,
                                  agree=True)
        self.assertEqual(got.tolist(), [0])

    def test_a_mark_the_other_drawn_views_could_see_and_did_not_make_is_dropped(self):
        """A slip of the hand: one view marks surface that the other drawn
        view can see perfectly well and did not mark."""
        poses = [_BoxPose() for _ in range(2)]
        geometry = (40, 8, 2)
        cell = 2 * 40 + 8
        shapes = [{"view": 0,
                   "points": [{"x": 8 + 40 + 2, "y": 8 + 2},
                              {"x": 8 + 40 + 2, "y": 8 + 30}]},
                  {"view": 1,
                   "points": [{"x": 8 + cell + 40 + 30, "y": 8 + 2},
                              {"x": 8 + cell + 40 + 30, "y": 8 + 30}]}]
        got = loop.stroke_regions(self.tree, poses, geometry, shapes,
                                  agree=True)
        self.assertEqual(got.tolist(), [],
                         "neither mark has a second opinion, and both could "
                         "have had one")

    def test_a_surface_only_one_drawn_view_can_see_needs_no_second_opinion(self):
        """Corroboration is required where it is possible, not where it is
        not -- otherwise nothing on a self-occluded face could ever be
        painted."""
        poses = [_BoxPose(), _BoxPose()]
        poses[1].hit_id[:] = -1              # this view sees nothing at all
        geometry = (40, 8, 2)
        cell = 2 * 40 + 8
        shapes = [{"view": 0,
                   "points": [{"x": 8 + 40 + 2, "y": 8 + 2},
                              {"x": 8 + 40 + 2, "y": 8 + 30}]},
                  {"view": 1,
                   "points": [{"x": 8 + cell + 40 + 2, "y": 8 + 2},
                              {"x": 8 + cell + 40 + 3, "y": 8 + 30}]}]
        got = loop.stroke_regions(self.tree, poses, geometry, shapes,
                                  agree=True)
        self.assertEqual(got.tolist(), [0])


class TestReview(unittest.TestCase):
    """The question nobody in the loop was ever asked.

    Each part is painted alone, and each of those calls can be right about its
    own colour while the picture falls apart -- it is asked "what is missing
    from THIS colour", never "is this any good". And a part's turn ends and
    never returns, so when a later coat eats an earlier one there is nobody
    left who is allowed to say so.
    """

    def setUp(self):
        self.tree = two_lobe_tree(per_region=4)
        self.mesh = _Mesh(len(self.tree["base"]))
        self.poses = [_BoxPose()]
        self.geometry = (40, 8, 1)
        self._show = loop.show

        def fake_show(mesh, up, field, labels, out_dir, tag, views=3,
                      pixels=520, directions=None, colours=None, focus=None):
            return (os.path.join(HERE, "..", "README.md"), self.poses,
                    self.geometry)
        loop.show = fake_show

    def tearDown(self):
        loop.show = self._show

    def _backend(self, script):
        state = {"n": 0}

        class Fake(object):
            def _run(inner, paths, prompt, key):
                index = state["n"]
                state["n"] += 1
                return script[index] if index < len(script) else {"fixes": []}
        return Fake()

    def _box(self, x0, x1):
        origin = 8 + 40
        return [{"x": origin + x0, "y": 8}, {"x": origin + x1, "y": 8},
                {"x": origin + x1, "y": 8 + 39}, {"x": origin + x0, "y": 8 + 39}]

    def test_it_takes_surface_back_off_a_colour_that_took_it(self):
        """The earlier colour's turn is over and it cannot defend itself. This
        pass stands in for it."""
        seeds = {0: [0, 1], 1: []}
        backend = self._backend([{"fixes": [{"colour": 2, "view": 0,
                                             "points": self._box(0, 19)}]}])
        seeds, field = loop.review(backend, self.mesh, self.tree, (0, 0, 1),
                                   seeds, ["rock", "shell"], "test",
                                   "/tmp/unused", None, rounds=2, log=None)
        self.assertIn(0, seeds[1], "the surface must move to the named colour")
        self.assertNotIn(0, seeds[0], "and off the one that was holding it")
        self.assertEqual(int(field[0]), 1)

    def test_an_empty_answer_ends_the_review(self):
        calls = []

        class Counting(object):
            def _run(inner, paths, prompt, key):
                calls.append(key)
                return {"fixes": []}
        loop.review(Counting(), self.mesh, self.tree, (0, 0, 1), {0: [0]},
                    ["rock"], "test", "/tmp/unused", None, rounds=5, log=None)
        self.assertEqual(len(calls), 1, "a painting called right is finished")

    def test_a_colour_that_does_not_exist_is_refused(self):
        seeds = {0: [0, 1]}
        backend = self._backend([{"fixes": [{"colour": 9, "view": 0,
                                             "points": self._box(0, 19)}]}])
        seeds, _field = loop.review(backend, self.mesh, self.tree, (0, 0, 1),
                                    seeds, ["rock"], "test", "/tmp/unused",
                                    None, rounds=1, log=None)
        self.assertEqual(sorted(seeds[0]), [0, 1])

    def test_a_fix_for_a_detailed_part_uses_the_fine_brush(self):
        """The review filled an outline for every fix, whatever the part. A
        four-corner box named "cracks" then handed the whole shell between the
        fractures to the crack colour -- the exact failure the fine brush
        exists to stop, reintroduced by the one pass not told about it."""
        seeds = {0: [0, 1], 1: []}
        parts = [{"name": "rock", "detail": "flat"},
                 {"name": "cracks", "detail": "detailed"}]
        backend = self._backend([{"fixes": [{"colour": 2, "view": 0,
                                             "points": self._box(0, 19)}]}])
        seeds, _field = loop.review(backend, self.mesh, self.tree, (0, 0, 1),
                                    seeds, ["rock", "cracks"], "test",
                                    "/tmp/unused", None, parts=parts,
                                    rounds=2, log=None)
        self.assertNotIn(1, seeds.get(1, []),
                         "a line round the box must not fill its interior")

    def test_a_fix_for_a_flat_part_still_fills(self):
        seeds = {0: [0, 1], 1: []}
        parts = [{"name": "rock", "detail": "flat"},
                 {"name": "shell", "detail": "flat"}]
        backend = self._backend([{"fixes": [{"colour": 2, "view": 0,
                                             "points": self._box(0, 19)}]}])
        seeds, _field = loop.review(backend, self.mesh, self.tree, (0, 0, 1),
                                    seeds, ["rock", "shell"], "test",
                                    "/tmp/unused", None, parts=parts,
                                    rounds=2, log=None)
        self.assertIn(0, seeds[1], "a flat part's fix fills its outline")


class TestCacheIdentity(unittest.TestCase):
    """A cached answer must belong to the question that was asked.

    Keying on the image alone means editing a prompt silently replays the
    answer to the previous prompt. That is failure circumstance 5 -- cache
    identity is not question identity -- which this module reintroduced in
    two more places after it was fixed once.
    """

    def test_every_cache_key_includes_its_prompt(self):
        import re
        src = open(os.path.join(HERE, "..", "paintpipe", "loop.py")).read()
        keys = re.findall(r'key = "(\w+)-%s" % rig_module\.digest\(\s*'
                          r'(?:handle\.read\(\),|handle\.read\(\))([^)]*)\)',
                          src)
        self.assertTrue(keys, "no cache keys found; the pattern moved")
        for name, rest in keys:
            with self.subTest(key=name):
                self.assertIn("prompt", rest,
                              "%s keys on the image but not the question" % name)
