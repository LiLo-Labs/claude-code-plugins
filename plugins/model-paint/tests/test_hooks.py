"""The guardrails: dangerous commands are caught, ordinary ones are left alone.

Both directions matter equally. A guardrail that misses a re-mesh costs a print;
a guardrail that blocks `grep merge_vertices` costs the user's trust in it, which
costs the next print. The near-miss cases below are the ones worth keeping.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
HOOKS = os.path.join(PLUGIN, "hooks")
sys.path.insert(0, HOOKS)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))

import guard_core                                        # noqa: E402
import guard_lib                                         # noqa: E402
import verify_geometry                                   # noqa: E402

SAMPLE = os.path.join(PLUGIN, "samples", "creature.stl")

DANGEROUS = [
    ("decimation on the user's model",
     'python3 -c "import trimesh; m=trimesh.load(\'/home/u/dragon.stl\', process=False); '
     'm.simplify_quadric_decimation(5000)"'),
    ("subdivision",
     'python3 -c "m.subdivide()" /home/u/dragon.stl'),
    ("vertex welding",
     'python3 -c "m = trimesh.load(\'/home/u/flexi.3mf\', process=False); m.merge_vertices()"'),
    ("duplicate face removal",
     'python3 -c "m.remove_duplicate_faces()" --model /home/u/flexi.3mf'),
    ("hole filling",
     'python3 -c "m.fill_holes()" /home/u/dragon.stl'),
    ("rescaling",
     'python3 -c "m.apply_scale(1.02)" /home/u/dragon.stl'),
    ("reorienting",
     'python3 -c "m.apply_transform(T)" /home/u/dragon.stl'),
    ("convex hull assigned back onto the mesh",
     'python3 -c "mesh = mesh.convex_hull" /home/u/dragon.stl'),
    ("load without process=False",
     'python3 -c "import trimesh; m = trimesh.load(\'/home/u/dragon.stl\')"'),
    ("trimesh.repair",
     'python3 -c "trimesh.repair.fix_winding(m)" /home/u/dragon.stl'),
    ("boolean union",
     'python3 -c "out = trimesh.boolean.union([a, b])" /home/u/dragon.stl'),
    ("boolean difference on a mesh",
     'python3 -c "cut = mesh.difference(tool)" /home/u/dragon.stl'),
    ("export over the input",
     'python3 -c "m.export(\'/home/u/models/dragon.stl\')"'),
    ("mutation hidden behind a benign first command",
     'ls /home/u && python3 -c "m.merge_vertices()" /home/u/dragon.stl'),
    ("no path at all, so nothing proves it is scratch",
     'python3 -c "import sys, trimesh; trimesh.load(sys.argv[1]).fill_holes()"'),
]

BENIGN = [
    ("searching the codebase for the call",
     'grep -rn "\\.merge_vertices(" /home/user/claude-code-plugins/plugins/model-paint/scripts'),
    ("ripgrep with a literal pattern",
     'rg "simplify_quadric_decimation|fill_holes" scripts/'),
    ("git log pickaxe",
     'git log -S ".apply_scale(" -- scripts/'),
    ("the correct read",
     'python3 -c "import trimesh; m = trimesh.load(\'/home/u/dragon.stl\', '
     'process=False, force=\'mesh\'); print(len(m.faces))"'),
    ("mutating a scratch copy",
     'python3 -c "m = trimesh.load(\'/tmp/scratch/proxy.stl\', process=False); '
     'm.simplify_quadric_decimation(2000)"'),
    ("regenerating the sample fixture",
     'python3 /home/user/claude-code-plugins/plugins/model-paint/tests/make_fixture.py'),
    ("apply_scale on the bundled sample",
     'python3 -c "m.apply_scale(2.0)" %s' % SAMPLE),
    ("a temp directory made on the spot",
     'python3 -c "import tempfile; d = tempfile.mkdtemp(); m.apply_transform(T); m.export(d)"'),
    ("running the plugin itself",
     'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/apply_plan.py" --input /home/u/dragon.stl '
     '--segments seg.json --plan plan.json --output /home/u/dragon-painted.3mf'),
    ("set arithmetic that merely reads like a boolean op",
     'python3 -c "used = filaments_used(a).union(filaments_used(b)); print(used)"'),
    ("the segmenter",
     'python3 scripts/segment.py --input /home/u/dragon.stl --output /tmp/seg.json'),
    ("running the test suite",
     'python3 -m unittest discover -s tests'),
    ("a paint_color edit, which is the whole point of the plugin",
     'python3 -c "obj.apply_paint({0: 2})"'),
    ("exporting a preview image, not a mesh",
     'python3 scripts/preview.py --input /home/u/dragon.stl --output /home/u/preview.png'),
]


class TestDangerousCommands(unittest.TestCase):

    def test_each_is_blocked(self):
        for label, command in DANGEROUS:
            with self.subTest(label):
                findings = guard_lib.evaluate(command)
                self.assertTrue(findings, "not blocked: %s" % command)
                message = guard_lib.format_block(command, findings)
                self.assertIn("instead", message)
                self.assertIn(findings[0].rule, message)


class TestBenignCommands(unittest.TestCase):

    def test_each_is_allowed(self):
        for label, command in BENIGN:
            with self.subTest(label):
                findings = guard_lib.evaluate(command)
                self.assertEqual(
                    [], findings,
                    "blocked ordinary work (%s): %s" % (label, command))


class TestMatcherDetails(unittest.TestCase):

    def test_bare_word_is_not_a_call(self):
        # Prose and identifiers are not invocations.
        self.assertEqual([], guard_lib.evaluate(
            'python3 -c "print(\'do not call merge_vertices here\')"'))

    def test_apply_paint_is_not_apply_transform(self):
        self.assertEqual([], guard_lib.evaluate('python3 -c "mesh.apply_paint({1: 2})"'))

    def test_load_with_process_false_across_lines(self):
        self.assertEqual([], guard_lib.evaluate(
            'python3 - <<PY\nm = trimesh.load(\n    path,\n    process=False)\nPY'))

    def test_load_with_process_true_is_blocked(self):
        findings = guard_lib.evaluate(
            'python3 -c "trimesh.load(\'/home/u/x.stl\', process=True)"')
        self.assertEqual(["unprocessed load"], [f.rule for f in findings])

    def test_export_to_temp_is_allowed_export_to_model_is_not(self):
        self.assertEqual([], guard_lib.evaluate('python3 -c "m.export(\'/tmp/probe.stl\')"'))
        self.assertTrue(guard_lib.evaluate('python3 -c "m.export(\'/home/u/x.stl\')"'))

    def test_convex_hull_kept_in_its_own_variable(self):
        self.assertEqual([], guard_lib.evaluate(
            'python3 -c "hull = mesh.convex_hull; print(hull.volume)"'))
        self.assertTrue(guard_lib.evaluate('python3 -c "mesh = mesh.convex_hull"'))

    def test_segments_are_judged_separately(self):
        parts = guard_lib.split_segments('grep -n "x" a.py && python3 run.py | head -5')
        self.assertEqual(['grep -n "x" a.py', "python3 run.py", "head -5"], parts)

    def test_separators_inside_quotes_do_not_split(self):
        self.assertEqual(['python3 -c "a; b | c"'],
                         guard_lib.split_segments('python3 -c "a; b | c"'))

    def test_leading_command_skips_env_and_sudo(self):
        self.assertEqual("python3", guard_lib.leading_command("FOO=1 sudo python3 x.py"))

    def test_sample_and_tmp_paths_are_safe(self):
        self.assertTrue(guard_lib.is_safe_path(SAMPLE))
        self.assertTrue(guard_lib.is_safe_path("/tmp/model-paint-1/copy.3mf"))
        self.assertFalse(guard_lib.is_safe_path("/home/u/models/dragon.stl"))


class TestCoreGuard(unittest.TestCase):

    def test_encoding_is_protected(self):
        self.assertTrue(guard_core.is_protected(
            os.path.join(PLUGIN, "scripts", "paintlib", "encoding.py")))
        self.assertTrue(guard_core.is_protected("scripts/paintlib/encoding.py"))

    def test_other_files_are_not(self):
        for path in ("scripts/paintlib/threemf.py", "scripts/segment.py",
                     "tests/test_paint.py", "docs/encoding.py.md"):
            self.assertFalse(guard_core.is_protected(path), path)


class TestHooksJson(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(HOOKS, "hooks.json"), "r", encoding="utf-8") as handle:
            self.config = json.load(handle)

    def test_shape_matches_the_documented_schema(self):
        hooks = self.config["hooks"]
        self.assertEqual({"PreToolUse", "PostToolUse"}, set(hooks))
        for event, groups in hooks.items():
            for group in groups:
                self.assertIn("matcher", group)
                for entry in group["hooks"]:
                    self.assertEqual("command", entry["type"])
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", entry["command"])
                    self.assertIsInstance(entry.get("timeout", 0), int)

    def test_every_referenced_script_exists(self):
        for groups in self.config["hooks"].values():
            for group in groups:
                for entry in group["hooks"]:
                    name = entry["command"].split("/hooks/")[1].rstrip('"')
                    self.assertTrue(os.path.exists(os.path.join(HOOKS, name)), name)


def run_hook(name, payload):
    process = subprocess.run(
        [sys.executable, os.path.join(HOOKS, name)],
        input=json.dumps(payload), capture_output=True, text=True)
    return process.returncode, process.stdout, process.stderr


class TestHookScripts(unittest.TestCase):
    """The scripts as Claude Code runs them: JSON on stdin, exit code out."""

    def test_bash_guard_blocks_with_a_reason(self):
        code, _out, err = run_hook("guard_mesh.py", {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command":
                           'python3 -c "m.merge_vertices()" /home/u/dragon.stl'},
        })
        self.assertEqual(2, code)
        self.assertIn("vertex welding", err)
        self.assertIn("instead", err)

    def test_bash_guard_allows_ordinary_work(self):
        code, _out, err = run_hook("guard_mesh.py", {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": 'grep -rn "merge_vertices" scripts/'},
        })
        self.assertEqual(0, code)
        self.assertEqual("", err)

    def test_bash_guard_ignores_malformed_input(self):
        process = subprocess.run(
            [sys.executable, os.path.join(HOOKS, "guard_mesh.py")],
            input="not json", capture_output=True, text=True)
        self.assertEqual(0, process.returncode)

    def test_core_guard_warns_without_blocking(self):
        code, out, _err = run_hook("guard_core.py", {
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path":
                           os.path.join(PLUGIN, "scripts", "paintlib", "encoding.py")},
        })
        self.assertEqual(0, code)
        self.assertIn("OrcaSlicer", json.loads(out)["systemMessage"])

    def test_core_guard_is_silent_elsewhere(self):
        code, out, _err = run_hook("guard_core.py", {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(PLUGIN, "scripts", "segment.py")},
        })
        self.assertEqual(0, code)
        self.assertEqual("", out.strip())


class TestOverwriteAndBypass(unittest.TestCase):
    """Holes found by adversarial review of the first guard implementation.

    Every case here was ALLOWED before the fix. They share one shape: the harm
    does not need trimesh in the command at all, or it hides behind a program
    that only reads.
    """

    MODEL = "/home/user/models/dragon.stl"

    def assertBlocked(self, command):
        self.assertTrue(guard_lib.evaluate(command), "should block: %s" % command)

    def assertAllowed(self, command):
        findings = guard_lib.evaluate(command)
        self.assertFalse(findings, "should allow: %s (%s)" % (
            command, [f.rule for f in findings]))

    def test_copying_over_the_model_is_blocked(self):
        for program in ("cp", "mv", "rsync -a", "install"):
            self.assertBlocked("%s /tmp/decimated.stl %s" % (program, self.MODEL))

    def test_redirect_onto_the_model_is_blocked(self):
        self.assertBlocked('python3 -c "print(1)" > %s' % self.MODEL)

    def test_copying_the_model_to_scratch_is_allowed(self):
        self.assertAllowed("cp %s /tmp/copy.stl" % self.MODEL)

    def test_unbalanced_paren_cannot_smuggle_a_second_command(self):
        """A stray '(' in a grep used to swallow the command after it."""
        self.assertBlocked(
            'grep -n "trimesh.load(" scripts/segment.py\n'
            'python3 -c "import trimesh;m=trimesh.load(\'%s\');m.merge_vertices()"'
            % self.MODEL)

    def test_find_exec_payload_is_not_read_only(self):
        self.assertBlocked(
            "find /home/user/models -name '*.stl' -exec python3 -c "
            "\"m.merge_vertices();m.export('%s')\" \\;" % self.MODEL)

    def test_fixture_basename_is_not_a_free_pass(self):
        """Matching on the basename made any file named creature.stl scratch."""
        self.assertBlocked(
            'python3 -c "m.merge_vertices(); m.export(\'/home/user/models/creature.stl\')"')

    def test_real_scratch_work_still_runs(self):
        self.assertAllowed('python3 -c "m.merge_vertices(); m.export(\'/tmp/scratch.stl\')"')
        self.assertAllowed("grep -rn 'merge_vertices' scripts/")
        self.assertAllowed("python3 scripts/segment.py --input %s --output /tmp/s.json"
                           % self.MODEL)
        self.assertAllowed(
            'python3 -c "import trimesh;m=trimesh.load(\'%s\', process=False)"' % self.MODEL)


class TestGeometryVerifier(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from paintlib import build
        cls.workdir = tempfile.mkdtemp(prefix="model-paint-hooks-")
        cls.source = build.from_stl(SAMPLE, os.path.join(cls.workdir, "creature.3mf"))
        cls.painted = os.path.join(cls.workdir, "creature-painted.3mf")

        from paintlib.threemf import ThreeMF
        model = ThreeMF(cls.source)
        obj = model.mesh_objects()[0]
        model.paint_object(obj, {index: 2 for index in range(0, 40)})
        model.save(cls.painted)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def test_command_parsing(self):
        command = ('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/apply_plan.py" '
                   "--input a.stl --segments s.json --plan p.json --output=out/b.3mf")
        self.assertEqual([("a.stl", "out/b.3mf")],
                         verify_geometry.apply_plan_runs(command))

    def test_painting_passes_against_the_3mf_source(self):
        ok, detail = verify_geometry.compare(self.source, self.painted)
        self.assertTrue(ok, detail)

    def test_painting_passes_against_the_original_stl(self):
        ok, detail = verify_geometry.compare(SAMPLE, self.painted)
        self.assertTrue(ok, detail)
        self.assertIn("2016 triangle", detail)

    def test_a_moved_vertex_is_caught(self):
        moved = os.path.join(self.workdir, "moved.3mf")
        _rewrite_first_vertex(self.painted, moved)
        ok, detail = verify_geometry.compare(self.source, moved)
        self.assertFalse(ok)
        self.assertIn("vertex coordinates changed", detail)
        ok, detail = verify_geometry.compare(SAMPLE, moved)
        self.assertFalse(ok)
        self.assertIn("moved by", detail)

    def test_hook_reports_a_pass_through_system_message(self):
        code, out, err = run_hook("verify_geometry.py", {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "cwd": self.workdir,
            "tool_input": {"command":
                           "python3 scripts/apply_plan.py --input %s --segments s.json "
                           "--plan p.json --output %s" % (SAMPLE, self.painted)},
            "tool_response": "ok",
        })
        self.assertEqual(0, code, err)
        self.assertIn("PASS", json.loads(out)["systemMessage"])

    def test_hook_stays_quiet_when_the_run_failed(self):
        """A stale file from an earlier run must never be reported as a PASS.

        apply_plan writes to --output only after its own check passes, so when it
        aborts, anything sitting at that path came from a previous run and says
        nothing about this one.
        """
        for response in ({"stdout": "", "stderr": "apply_plan: unknown segment 's99'"},
                         {"stdout": "", "stderr": "", "exit_code": 1},
                         {"stdout": "", "stderr": "", "interrupted": True}):
            code, out, err = run_hook("verify_geometry.py", {
                "hook_event_name": "PostToolUse",
                "tool_name": "Bash",
                "cwd": self.workdir,
                "tool_input": {"command":
                               "python3 scripts/apply_plan.py --input %s --segments s.json "
                               "--plan p.json --output %s" % (SAMPLE, self.painted)},
                "tool_response": response,
            })
            self.assertEqual(0, code, err)
            self.assertEqual("", out.strip(),
                             "reported on a failed run: %r" % response)

    def test_hook_exits_2_when_geometry_moved(self):
        moved = os.path.join(self.workdir, "moved2.3mf")
        _rewrite_first_vertex(self.painted, moved)
        code, _out, err = run_hook("verify_geometry.py", {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "cwd": self.workdir,
            "tool_input": {"command":
                           "python3 scripts/apply_plan.py --input %s --segments s.json "
                           "--plan p.json --output %s" % (self.source, moved)},
        })
        self.assertEqual(2, code)
        self.assertIn("FAILED", err)
        self.assertIn("Do not print", err)

    def test_hook_stays_quiet_for_unrelated_commands(self):
        code, out, _err = run_hook("verify_geometry.py", {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "cwd": self.workdir,
            "tool_input": {"command": "ls -la"},
        })
        self.assertEqual(0, code)
        self.assertEqual("", out.strip())

    def test_hook_is_quiet_when_the_run_produced_nothing(self):
        code, out, _err = run_hook("verify_geometry.py", {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "cwd": self.workdir,
            "tool_input": {"command":
                           "python3 scripts/apply_plan.py --input %s --segments s.json "
                           "--plan p.json --output %s"
                           % (SAMPLE, os.path.join(self.workdir, "never-written.3mf"))},
        })
        self.assertEqual(0, code)
        self.assertEqual("", out.strip())


def _rewrite_first_vertex(source, target):
    """Copy a 3MF, nudging one vertex: the failure the verifier exists to catch."""
    import re
    import zipfile
    with zipfile.ZipFile(source, "r") as archive:
        entries = [(info.filename, archive.read(info.filename))
                   for info in archive.infolist()]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            if name.lower().endswith(".model"):
                text = data.decode("utf-8")
                text = re.sub(r'<vertex x="([^"]*)"',
                              lambda m: '<vertex x="%s"' % (float(m.group(1)) + 0.5),
                              text, count=1)
                data = text.encode("utf-8")
            archive.writestr(name, data)
    return target


if __name__ == "__main__":
    unittest.main()
