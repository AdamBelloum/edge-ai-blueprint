"""Offline HPC reset delegation contract; no deployment operations."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("openmp-01-basics", "mpi-01-basics")


def invoke(arguments, *, missing=False, check_status=0, execute_status=0):
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        wrapper = directory / "reset-workshop.sh"
        shutil.copy2(ROOT / "scripts/workshops/hpc/reset-workshop.sh", wrapper)
        log = directory / "calls.log"
        if not missing:
            helper = directory / "cleanup-staging.sh"
            helper.write_text(
                '#!/bin/sh\n'
                'printf "%s\\n" "$*" >> "$MOCK_LOG"\n'
                'case "$1" in\n'
                '  --check) exit "$MOCK_CHECK_STATUS" ;;\n'
                '  --execute) exit "$MOCK_EXECUTE_STATUS" ;;\n'
                '  *) exit 98 ;;\n'
                'esac\n'
            )
            helper.chmod(0o700)
        environment = os.environ.copy()
        for key in ("BASH_ENV", "ENV"):
            environment.pop(key, None)
        environment.update(
            MOCK_LOG=str(log),
            MOCK_CHECK_STATUS=str(check_status),
            MOCK_EXECUTE_STATUS=str(execute_status),
        )
        result = subprocess.run(
            ["bash", str(wrapper), *arguments], env=environment,
            capture_output=True, text=True, timeout=10,
        )
        calls = log.read_text().splitlines() if log.exists() else []
        return result, calls


class HPCResetEntrypointTests(unittest.TestCase):
    def test_both_modules_preflight_then_clean_shared_staging(self):
        for module in MODULES:
            with self.subTest(module=module):
                result, calls = invoke(["--runtime-only", "--module", module])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, ["--check", "--execute"])
                self.assertIn("NOT verified", result.stdout)

    def test_missing_cleanup_helper_blocks(self):
        for module in MODULES:
            with self.subTest(module=module):
                result, calls = invoke(
                    ["--runtime-only", "--module", module], missing=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(calls, [])

    def test_preflight_failure_blocks_execution(self):
        for module in MODULES:
            with self.subTest(module=module):
                result, calls = invoke(
                    ["--runtime-only", "--module", module], check_status=13)
                self.assertEqual(result.returncode, 13, result.stderr)
                self.assertEqual(calls, ["--check"])
                self.assertNotIn("cleanup verified", result.stdout)

    def test_cleanup_failure_propagates(self):
        for module in MODULES:
            with self.subTest(module=module):
                result, calls = invoke(
                    ["--runtime-only", "--module", module], execute_status=17)
                self.assertEqual(result.returncode, 17, result.stderr)
                self.assertEqual(calls, ["--check", "--execute"])
                self.assertNotIn("cleanup verified", result.stdout)

    def test_help_and_invalid_arguments_do_not_call_cleanup(self):
        arguments_list = (
            ["--help"], ["-h"], [], ["--execute"], ["--runtime-only"],
            ["--runtime-only", "--module"],
            ["--runtime-only", "--module", "mpi"],
            ["--runtime-only", "--module", "unsupported"],
            ["--runtime-only", "--module", MODULES[0], "--extra"],
        )
        for arguments in arguments_list:
            with self.subTest(arguments=arguments):
                result, calls = invoke(arguments)
                expected = 0 if arguments in (["--help"], ["-h"]) else 2
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
