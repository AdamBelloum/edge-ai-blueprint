"""Offline tests of the global reset's actual Module 3 attestation block."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "scripts/workshops/reset-workshops.sh").read_text()
BLOCK = SOURCE.split("# BEGIN MODULE3 RESET ATTESTATION", 1)[1].split(
    "# END MODULE3 RESET ATTESTATION", 1
)[0]

STUB_OK = 'module3_runtime_removal() { printf "STUB_REMOVAL_CALLED\\n"; return 0; }\n'
STUB_FAIL = 'module3_runtime_removal() { printf "STUB_REMOVAL_CALLED\\n"; return 1; }\n'


def invoke(workshop, module, answer, preamble=""):
    script = (
        'set -euo pipefail\n'
        'fail() { printf "%s\\n" "$*" >&2; exit 1; }\n'
        'cleanup_workshop="$1"; cleanup_module="$2"\n'
        + preamble
        + BLOCK
        + '\nprintf "ARG=%s\\n" "${runtime_reset_args[@]}"\n'
    )
    return subprocess.run(
        ["bash", "-c", script, "attestation-test", workshop, module],
        input=answer, capture_output=True, text=True, timeout=10,
    )


class Module3AttestationTests(unittest.TestCase):
    def test_yes_adds_scoped_confirmation(self):
        result = invoke("cloud-computing-soa", "module3", "y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ARG=--confirm-no-external-module3-runtime", result.stdout)
        self.assertIn("NOT automated resource verification", result.stdout)

    def test_decline_empty_unknown_and_eof_block_dispatch(self):
        for answer in ("n\n", "\n", "unknown\n", ""):
            with self.subTest(answer=answer):
                result = invoke("cloud-computing-soa", "module3", answer)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("ARG=", result.stdout)
                self.assertIn("cleanup remains in_progress", result.stderr)

    def test_other_routes_never_receive_confirmation(self):
        for workshop, module in (
            ("cloud-computing-soa", "module1"),
            ("cloud-computing-soa", "module4"),
            ("cloud-computing-soa", "module5"),
            ("introduction-to-ai", "module3"),
        ):
            with self.subTest(workshop=workshop, module=module):
                result = invoke(workshop, module, "")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("--confirm-no-external-module3-runtime", result.stdout)
                self.assertNotIn("Confirm no external", result.stdout)

    def test_no_then_successful_removal_adds_confirmation(self):
        result = invoke("cloud-computing-soa", "module3", "n\n", STUB_OK)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STUB_REMOVAL_CALLED", result.stdout)
        self.assertIn("ARG=--confirm-no-external-module3-runtime", result.stdout)

    def test_no_then_failed_or_declined_removal_blocks_dispatch(self):
        result = invoke("cloud-computing-soa", "module3", "n\n", STUB_FAIL)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STUB_REMOVAL_CALLED", result.stdout)
        self.assertNotIn("ARG=", result.stdout)
        self.assertIn("cleanup remains in_progress", result.stderr)

    def test_unknown_answer_never_offers_removal(self):
        result = invoke("cloud-computing-soa", "module3", "unknown\n", STUB_OK)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("STUB_REMOVAL_CALLED", result.stdout)
        self.assertNotIn("ARG=", result.stdout)

    def test_yes_never_calls_removal(self):
        result = invoke("cloud-computing-soa", "module3", "y\n", STUB_OK)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("STUB_REMOVAL_CALLED", result.stdout)


if __name__ == "__main__":
    unittest.main()
