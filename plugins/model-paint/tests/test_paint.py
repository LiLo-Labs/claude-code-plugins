"""The safety net: paint must change paint and nothing else."""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from paintlib import build, threemf                      # noqa: E402
from paintlib.encoding import SOLID, decode, encode_solid, filaments_used  # noqa: E402


class TestEncoding(unittest.TestCase):
    """Fixtures taken from OrcaSlicer's own source, not from guesswork."""

    def test_known_solid_values(self):
        # Derived from TriangleSelector::serialize(); '1C', '0C' and '2C' also
        # appear verbatim in a comment in OrcaSlicer's Model.cpp.
        self.assertEqual(SOLID[1], "4")
        self.assertEqual(SOLID[2], "8")
        self.assertEqual(SOLID[3], "0C")
        self.assertEqual(SOLID[4], "1C")
        self.assertEqual(SOLID[5], "2C")

    def test_unpainted_is_empty(self):
        self.assertEqual(encode_solid(0), "")

    def test_round_trip_all_filaments(self):
        for filament in range(1, 17):
            self.assertEqual(decode(SOLID[filament]), {"state": filament})
            self.assertEqual(filaments_used(SOLID[filament]), {filament})

    def test_decodes_subdivided_triangle(self):
        # A split triangle from OrcaSlicer's Model.cpp comment.
        tree = decode("1C0C2C0C1C13")
        self.assertIn("children", tree)
        self.assertTrue(filaments_used("1C0C2C0C1C13"))


class TestPaintPreservesGeometry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.stl = os.path.join(HERE, "..", "samples", "creature.stl")
        if not os.path.exists(self.stl):
            subprocess.check_call(
                [sys.executable, os.path.join(HERE, "make_fixture.py"), self.stl])
        self.source = build.from_stl(self.stl, os.path.join(self.tmp, "model.3mf"))

    def test_builder_preserves_triangle_count(self):
        import trimesh
        mesh = trimesh.load(self.stl, process=False, force="mesh")
        obj = threemf.ThreeMF(self.source).mesh_objects()[0]
        self.assertEqual(obj.triangle_count, len(mesh.faces))
        self.assertEqual(len(obj.vertices), len(mesh.vertices))

    def test_paint_then_reload(self):
        model = threemf.ThreeMF(self.source)
        obj = model.mesh_objects()[0]
        assignments = {i: (i % 4) + 1 for i in range(0, obj.triangle_count, 3)}
        model.paint_object(obj, assignments)
        out = model.save(os.path.join(self.tmp, "painted.3mf"))

        reloaded = threemf.ThreeMF(out).mesh_objects()[0]
        self.assertTrue(reloaded.is_painted)
        for index, filament in assignments.items():
            self.assertEqual(filaments_used(reloaded.paint[index]), {filament},
                             "triangle %d" % index)
        for index in range(reloaded.triangle_count):
            if index not in assignments:
                self.assertEqual(reloaded.paint[index], "")

    def test_geometry_identical_after_painting(self):
        model = threemf.ThreeMF(self.source)
        obj = model.mesh_objects()[0]
        model.paint_object(obj, {i: 2 for i in range(obj.triangle_count)})
        out = model.save(os.path.join(self.tmp, "fully-painted.3mf"))

        same, detail = threemf.geometry_matches(self.source, out)
        self.assertTrue(same, detail)

    def test_repaint_is_idempotent(self):
        """Painting twice must not stack duplicate attributes."""
        model = threemf.ThreeMF(self.source)
        obj = model.mesh_objects()[0]
        model.paint_object(obj, {0: 3})
        model.paint_object(obj, {0: 4})
        out = model.save(os.path.join(self.tmp, "repainted.3mf"))

        reloaded = threemf.ThreeMF(out).mesh_objects()[0]
        self.assertEqual(reloaded.paint[0], SOLID[4])
        text = threemf.ThreeMF(out)._text_for("3D/3dmodel.model")
        self.assertEqual(text.count("paint_color"), 1)

    def test_clearing_paint_removes_attribute(self):
        model = threemf.ThreeMF(self.source)
        obj = model.mesh_objects()[0]
        model.paint_object(obj, {5: 3})
        model.paint_object(obj, {5: 0})
        out = model.save(os.path.join(self.tmp, "cleared.3mf"))
        self.assertNotIn("paint_color", threemf.ThreeMF(out)._text_for("3D/3dmodel.model"))

    def test_placement_change_is_caught(self):
        """A rotated or re-arranged model is a changed file, even if the mesh survived.

        This is the failure mode that motivated verify.py: a repair step returned
        the "same" model rotated on the plate, and nothing flagged it.
        """
        model = threemf.ThreeMF(self.source)
        text = model._text_for("3D/3dmodel.model")
        rotated = text.replace('transform="1 0 0 0 1 0 0 0 1 0 0 0"',
                               'transform="0 -1 0 1 0 0 0 0 1 0 0 0"')
        self.assertNotEqual(text, rotated, "fixture should contain a build transform")
        model.replace_entry("3D/3dmodel.model", rotated)
        out = model.save(os.path.join(self.tmp, "rotated.3mf"))

        same, detail = threemf.geometry_matches(self.source, out)
        self.assertFalse(same, "rotation should not pass as identical")
        self.assertIn("placement", detail)

    def test_paint_preserves_placement(self):
        model = threemf.ThreeMF(self.source)
        before = model.placement()
        obj = model.mesh_objects()[0]
        model.paint_object(obj, {0: 1, 1: 2, 2: 3})
        out = model.save(os.path.join(self.tmp, "placed.3mf"))
        self.assertEqual(threemf.ThreeMF(out).placement(), before)

    def test_rejects_out_of_range_triangle(self):
        model = threemf.ThreeMF(self.source)
        obj = model.mesh_objects()[0]
        with self.assertRaises(IndexError):
            model.paint_object(obj, {obj.triangle_count: 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
