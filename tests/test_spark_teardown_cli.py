"""CLI tests; runner execution is mocked."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_spark_teardown_runner import runner

path = Path(__file__).resolve().parents[1] / (
    "scripts/workshops/big-data/spark/teardown_cli.py"
)
spec = importlib.util.spec_from_file_location("teardown_cli", path)
cli = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"teardown_runner": runner}):
    spec.loader.exec_module(cli)


class CliTests(unittest.TestCase):
    def test_help_and_invalid_arguments_never_execute(self):
        cases = [
            (["--help"], 0),
            ([], 2),
            (["--execute", "--unknown"], 2),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments), \
                 patch.object(cli, "run_teardown") as run, \
                 redirect_stdout(io.StringIO()), \
                 redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    cli.main(arguments)
                self.assertEqual(raised.exception.code, expected)
                run.assert_not_called()

    def test_verified_cleanup_reports_removed_ids(self):
        output = io.StringIO()
        result = {"container_ids": ["a" * 64], "network_ids": ["b" * 64]}
        with patch.object(cli, "run_teardown", return_value=result) as run, \
             redirect_stdout(output):
            self.assertEqual(cli.main(["--execute"]), 0)
        run.assert_called_once_with()
        self.assertEqual(json.loads(output.getvalue()), {
            "cleanup_verified": True,
            "changed": True,
            "removed_container_ids": result["container_ids"],
            "removed_network_ids": result["network_ids"],
        })

    def test_already_clean_reports_no_change(self):
        output = io.StringIO()
        with patch.object(cli, "run_teardown", return_value={
            "container_ids": [], "network_ids": [],
        }), redirect_stdout(output):
            self.assertEqual(cli.main(["--execute"]), 0)
        self.assertFalse(json.loads(output.getvalue())["changed"])

    def test_failures_return_nonzero_without_success_output(self):
        errors = [
            PermissionError("root required"),
            ValueError("ownership mismatch"),
            RuntimeError("lock unavailable"),
            subprocess.CalledProcessError(1, ["docker"]),
            subprocess.TimeoutExpired(["docker"], 120),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                output, diagnostic = io.StringIO(), io.StringIO()
                with patch.object(cli, "run_teardown", side_effect=error), \
                     redirect_stdout(output), redirect_stderr(diagnostic):
                    self.assertEqual(cli.main(["--execute"]), 1)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("cleanup is not verified", diagnostic.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
