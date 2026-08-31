"""Every module must import, and the command must run.

This suite exists because a sweep that deleted eighteen thousand lines left
124 tests green while `python3 -m paintpipe.cli --help` died on an import of a
module that no longer existed. Nothing in the suite touched the entry point,
so nothing noticed. A test that never imports the thing the user runs is not
testing the thing the user runs.
"""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))


class TestEveryModuleImports(unittest.TestCase):
    def test_every_module_in_the_package_imports(self):
        import importlib
        folder = os.path.join(ROOT, "paintpipe")
        names = sorted(f[:-3] for f in os.listdir(folder)
                       if f.endswith(".py") and not f.startswith("_"))
        self.assertGreater(len(names), 5, "the package should not be empty")
        for name in names:
            with self.subTest(module=name):
                importlib.import_module("paintpipe.%s" % name)

    def test_the_command_runs(self):
        """--help exercises the whole import graph of the entry point."""
        finished = subprocess.run(
            [sys.executable, "-m", "paintpipe.cli", "--help"],
            cwd=ROOT, capture_output=True, timeout=120)
        self.assertEqual(finished.returncode, 0,
                         finished.stderr.decode("utf-8", "replace")[-2000:])
        self.assertIn(b"--filaments", finished.stdout)

    def test_no_module_imports_something_deleted(self):
        """Import every module in a fresh interpreter, so a missing name in a
        rarely-imported module cannot hide behind another test's imports."""
        folder = os.path.join(ROOT, "paintpipe")
        names = sorted(f[:-3] for f in os.listdir(folder)
                       if f.endswith(".py") and not f.startswith("_"))
        code = "import sys; sys.path[:0] = %r\n" % [ROOT, os.path.join(ROOT, "scripts")]
        code += "\n".join("import paintpipe.%s" % n for n in names)
        finished = subprocess.run([sys.executable, "-c", code],
                                  capture_output=True, timeout=180)
        self.assertEqual(finished.returncode, 0,
                         finished.stderr.decode("utf-8", "replace")[-2000:])


if __name__ == "__main__":
    unittest.main()
