"""Offline tests of workshop reset entry points using fake runtime helpers."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    ("federated-learning", "manage-flower-server.sh",
     ["--runtime-only"], "stop"),
    ("big-data", "spark/teardown-runtime.sh",
     ["--runtime-only", "--module", "spark"], "--execute"),
)


def run_wrapper(workshop, helper_path, arguments, status=0, missing=False):
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        wrapper = directory / "reset-workshop.sh"
        shutil.copy2(
            ROOT / "scripts/workshops" / workshop / (
                "reset-federated-learning-workshop.sh"
                if workshop == "federated-learning"
                else "reset-workshop.sh"
            ),
            wrapper,
        )
        log = directory / "calls.log"
        if not missing:
            helper = directory / helper_path
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$*" >> "$MOCK_LOG"\n'
                'exit "$MOCK_STATUS"\n'
            )
            helper.chmod(0o700)
        environment = os.environ.copy()
        for name in ("BASH_ENV", "ENV"):
            environment.pop(name, None)
        environment.update(MOCK_LOG=str(log), MOCK_STATUS=str(status))
        result = subprocess.run(
            ["bash", str(wrapper), *arguments],
            env=environment, capture_output=True, text=True, timeout=10,
        )
        calls = log.read_text().splitlines() if log.exists() else []
        return result, calls


class ResetEntrypointTests(unittest.TestCase):
    def test_runtime_delegation(self):
        for workshop, helper, arguments, expected in CASES:
            with self.subTest(workshop=workshop):
                result, calls = run_wrapper(workshop, helper, arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [expected])
                self.assertIn("NOT verified", result.stdout)

    def test_helper_failure_propagates(self):
        for workshop, helper, arguments, expected in CASES:
            with self.subTest(workshop=workshop):
                result, calls = run_wrapper(
                    workshop, helper, arguments, status=7
                )
                self.assertEqual(result.returncode, 7)
                self.assertEqual(calls, [expected])
                self.assertIn("cleanup remains unverified", result.stderr)

    def test_missing_helper_blocks_execution(self):
        for workshop, helper, arguments, _ in CASES:
            with self.subTest(workshop=workshop):
                result, calls = run_wrapper(
                    workshop, helper, arguments, missing=True
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(calls, [])

    def test_help_and_invalid_arguments_never_call_helpers(self):
        for workshop, helper, _, _ in CASES:
            for arguments in (
                ["--help"], ["-h"], [], ["--execute"],
                ["--runtime-only", "--module", "unsupported"],
                ["--runtime-only", "--unexpected"],
            ):
                with self.subTest(workshop=workshop, arguments=arguments):
                    result, calls = run_wrapper(workshop, helper, arguments)
                    expected = 0 if arguments in (["--help"], ["-h"]) else 2
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertEqual(calls, [])



class ModuleResetBoundaryTests(unittest.TestCase):
    def invoke(self, workshop, arguments):
        # Run copied wrappers without operational helpers.
        return run_wrapper(
            workshop, "unused-helper", arguments, missing=True
        )

    def test_supported_module_boundaries(self):
        cases = {
            "introduction-to-ai": ("module1", "module2", "module3"),
            "cloud-computing-soa": ("module1", "module2", "module5"),
            "hpc": ("openmp-01-basics",),
        }
        for workshop, modules in cases.items():
            for module in modules:
                with self.subTest(workshop=workshop, module=module):
                    result, calls = self.invoke(
                        workshop, ["--runtime-only", "--module", module]
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(calls, [])
                    self.assertIn("module=" + module, result.stdout)
                    self.assertIn("NOT verified", result.stdout)

    def test_module3_explicit_no_external_runtime_confirmation(self):
        result, calls = self.invoke(
            "cloud-computing-soa",
            ["--runtime-only", "--module", "module3",
             "--confirm-no-external-module3-runtime"],
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        self.assertIn("operator-attested", result.stdout)
        self.assertIn("NOT verified", result.stdout)

    def test_module3_confirmation_is_scoped_and_rejects_unknown_options(self):
        for module, option in (
            ("module1", "--confirm-no-external-module3-runtime"),
            ("module4", "--confirm-no-external-module3-runtime"),
            ("module5", "--confirm-no-external-module3-runtime"),
            ("module3", "--unexpected"),
        ):
            with self.subTest(module=module, option=option):
                result, calls = self.invoke(
                    "cloud-computing-soa",
                    ["--runtime-only", "--module", module, option],
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(calls, [])

    def test_unimplemented_external_cleanup_is_refused(self):
        for module in ("module3", "module4"):
            with self.subTest(module=module):
                result, calls = self.invoke(
                    "cloud-computing-soa",
                    ["--runtime-only", "--module", module],
                )
                self.assertEqual(result.returncode, 3)
                self.assertEqual(calls, [])
                self.assertIn("not implemented", result.stderr)
                self.assertNotIn("cleanup verified", result.stdout)

    def test_help_and_invalid_arguments(self):
        for workshop in ("introduction-to-ai", "cloud-computing-soa", "hpc"):
            for arguments in (
                ["--help"], ["-h"], [], ["--execute"],
                ["--runtime-only"],
                ["--runtime-only", "--module"],
                ["--runtime-only", "--module", "unsupported"],
                ["--execute", "--module", "module1"],
                ["--runtime-only", "--module", "module1", "--extra"],
            ):
                with self.subTest(workshop=workshop, arguments=arguments):
                    result, calls = self.invoke(workshop, arguments)
                    expected = 0 if arguments in (["--help"], ["-h"]) else 2
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertEqual(calls, [])

    def test_mpi_is_not_silently_accepted(self):
        result, calls = self.invoke(
            "hpc", ["--runtime-only", "--module", "mpi"]
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
