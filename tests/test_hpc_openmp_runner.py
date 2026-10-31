"""Offline OpenMP runner tests using a simulated compiler."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "workshop_assets/hpc/OpenMP/helpers/openmp_start"


class OpenMPRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="openmp-runner-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace with spaces"
        self.helper = self.root / "OpenMP/helpers/openmp_start"
        self.helper.parent.mkdir(parents=True)
        shutil.copy2(RUNNER, self.helper)

        self.exercise = self.root / "OpenMP/exercises/code1"
        self.exercise.mkdir(parents=True)
        self.source = self.exercise / "code.c"
        self.source.write_text("participant working source\n")
        (self.exercise / "problem.md").write_text("Exercise problem\n")
        (self.exercise / "solution.c").write_text("reference solution\n")
        (self.exercise / "solution.md").write_text("Solution explanation\n")

        self.log = self.root / "compiler-log.json"
        compiler = self.root / "fake compiler.py"
        compiler.write_text(
            """import json, os
from pathlib import Path
import sys
args = sys.argv[1:]
output = Path(args[args.index("-o") + 1])
source = Path(args[args.index("-o") - 1])
Path(os.environ["FAKE_LOG"]).write_text(json.dumps({
    "args": args,
    "output": str(output),
    "source": source.read_text(),
}))
program = (
    "#!" + sys.executable + "\\n"
    "import os, time\\n"
    "print('EXECUTED', flush=True)\\n"
    "print('THREADS=' + os.environ['OMP_NUM_THREADS'], flush=True)\\n"
    "print('DYNAMIC=' + os.environ['OMP_DYNAMIC'], flush=True)\\n"
    "print('LIMIT=' + os.environ['OMP_THREAD_LIMIT'], flush=True)\\n"
    "time.sleep(float(os.environ.get('FAKE_SLEEP', '0')))\\n"
    "raise SystemExit(int(os.environ.get('FAKE_EXIT', '0')))\\n"
)
if os.environ.get("FAKE_BUILD") != "missing":
    output.write_text(program)
    output.chmod(0o755)
if os.environ.get("FAKE_BUILD") == "fail":
    raise SystemExit(7)
"""
        )
        self.environment = dict(os.environ)
        self.environment.update(
            CC=shlex.join([sys.executable, str(compiler)]),
            FAKE_LOG=str(self.log),
            FAKE_BUILD="ok",
            FAKE_SLEEP="0",
            FAKE_EXIT="0",
        )

    def invoke(self, *arguments, **overrides):
        environment = dict(self.environment)
        environment.update(overrides)
        return subprocess.run(
            [sys.executable, str(self.helper), *arguments],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def assert_build_cleaned(self):
        record = json.loads(self.log.read_text())
        self.assertFalse(Path(record["output"]).parent.exists())
        return record

    def test_display_actions_do_not_modify_files_or_compile(self):
        before = {
            path.name: path.read_bytes()
            for path in self.exercise.iterdir()
        }
        for arguments, expected in (
            (("code1",), "participant working source"),
            (("code1", "--problem"), "Exercise problem"),
            (("code1", "--solution"), "reference solution"),
        ):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout)
                if "--solution" in arguments:
                    self.assertIn("Solution explanation", result.stdout)
        self.assertEqual(before, {
            path.name: path.read_bytes()
            for path in self.exercise.iterdir()
        })
        self.assertFalse(self.log.exists())

    def test_run_compiles_current_source_and_repeats(self):
        self.source.write_text("participant edited source\n")
        result = self.invoke(
            "code1", "--run", "--threads", "3", "--repeat", "2"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("EXECUTED"), 2)
        self.assertEqual(result.stdout.count("THREADS=3"), 2)
        self.assertIn("DYNAMIC=FALSE", result.stdout)
        self.assertIn("LIMIT=3", result.stdout)
        self.assertIn("does not prove correctness", result.stdout)
        record = self.assert_build_cleaned()
        self.assertIn("-fopenmp", record["args"])
        self.assertEqual(record["source"], "participant edited source\n")
        self.assertEqual(self.source.read_text(), record["source"])

    def test_default_run_requests_two_threads(self):
        result = self.invoke("code1", "--run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("EXECUTED"), 1)
        self.assertIn("THREADS=2", result.stdout)
        self.assert_build_cleaned()

    def test_failed_compilation_never_runs_produced_executable(self):
        result = self.invoke("code1", "--run", FAKE_BUILD="fail")
        self.assertEqual(result.returncode, 7)
        self.assertIn("Compilation failed; nothing executed", result.stderr)
        self.assertNotIn("EXECUTED", result.stdout)
        self.assert_build_cleaned()

    def test_missing_compiler_output_is_rejected(self):
        result = self.invoke("code1", "--run", FAKE_BUILD="missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not produce an executable", result.stderr)
        self.assertNotIn("EXECUTED", result.stdout)
        self.assert_build_cleaned()

    def test_execution_failure_stops_repetitions(self):
        result = self.invoke(
            "code1", "--run", "--repeat", "3", FAKE_EXIT="3"
        )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.count("EXECUTED"), 1)
        self.assert_build_cleaned()

    def test_timeout_stops_execution_and_cleans_build(self):
        result = self.invoke(
            "code1", "--run", "--timeout", "1", FAKE_SLEEP="30"
        )
        self.assertEqual(result.returncode, 124)
        self.assertIn("Execution timed out", result.stderr)
        self.assert_build_cleaned()

    def test_missing_cc_and_unavailable_compiler_are_rejected(self):
        for compiler in ("", "/nonexistent/openmp-test-compiler"):
            with self.subTest(compiler=compiler):
                result = self.invoke("code1", "--run", CC=compiler)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR", result.stderr)
                self.assertFalse(self.log.exists())

    def test_invalid_arguments_are_rejected_before_compilation(self):
        cases = (
            ("../code1", "--run"),
            ("code1", "--threads", "2"),
            ("code1", "--run", "--threads", "0"),
            ("code1", "--run", "--threads", "65"),
            ("code1", "--run", "--repeat", "21"),
            ("code1", "--run", "--timeout", "0"),
            ("code1", "--run", "--timeout", "301"),
            ("code1", "--run", "--problem"),
            ("code1", "--solution", "--problem"),
            ("code99", "--run"),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.log.exists())

    def test_missing_solution_explanation_does_not_show_partial_solution(self):
        (self.exercise / "solution.md").unlink()
        result = self.invoke("code1", "--solution")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Required solution file is missing", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
