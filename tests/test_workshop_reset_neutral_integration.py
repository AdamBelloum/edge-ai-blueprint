"""Offline reset integration tests; no operational command is executed."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / (
    "scripts/workshops/reset-workshops.sh"
)).read_text()
START = "# BEGIN NEUTRAL RESET RECONCILIATION"
END = "# END NEUTRAL RESET RECONCILIATION"
if SOURCE.count(START) != 1 or SOURCE.count(END) != 1:
    raise RuntimeError("Expected unique neutral reconciliation boundaries.")
BLOCK = SOURCE.split(START, 1)[1].split(END, 1)[0]
TAIL = SOURCE.split(END, 1)[1]

SETUP = r'''
set -euo pipefail
DIGITAFRICA_NAMESPACE=mock-namespace
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
run_deployment_remote() {
  # Record the supplied patch, but NEVER execute it.
  if [[ "$1" == *"--type json"* ]]; then
    printf 'EVENT completion-patch\n%s\n' "$1"
    return "$MOCK_COMPLETION_STATUS"
  fi
  printf 'EVENT patch\n%s\n' "$1"
  return "$MOCK_PATCH_STATUS"
}
mock_reconcile() {
  printf 'EVENT reconcile'
  printf ' <%s>' "$@"
  printf '\n'
  return "$MOCK_RECONCILE_STATUS"
}
warn() { printf '\n------ WARNING: %s ------\n\n' "$*" >&2; }
RECONCILIATION_HELPER=mock_reconcile
'''


def run_block(patch_status=0, reconcile_status=0, tail=False, completion_status=0):
    environment = dict(os.environ)
    environment.pop("BASH_ENV", None)
    environment.pop("ENV", None)
    environment.update(
        MOCK_PATCH_STATUS=str(patch_status),
        MOCK_RECONCILE_STATUS=str(reconcile_status),
        MOCK_COMPLETION_STATUS=str(completion_status),
    )
    script = SETUP + BLOCK
    script += TAIL if tail else "\nprintf 'EVENT next-boundary\\n'\n"
    return subprocess.run(
        ["bash", "-c", script],
        env=environment, capture_output=True, text=True, timeout=10,
    )


class ResetNeutralIntegrationTests(unittest.TestCase):
    def test_patch_precedes_reset_scoped_reconciliation(self):
        result = run_block()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EVENT reconcile <--neutral-for-reset>", result.stdout)
        self.assertLess(
            result.stdout.index("EVENT patch"),
            result.stdout.index("EVENT reconcile"),
        )
        self.assertIn("EVENT next-boundary", result.stdout)
        self.assertLess(
            result.stdout.index("EVENT reconcile"),
            result.stdout.index("EVENT completion-patch"),
        )
        self.assertIn(
            '{"op":"replace","path":"/data/cleanup_status","value":"complete"}',
            result.stdout,
        )

    def test_patch_failure_prevents_reconciliation(self):
        result = run_block(patch_status=9)
        self.assertEqual(result.returncode, 9)
        self.assertNotIn("EVENT reconcile", result.stdout)
        self.assertNotIn("EVENT completion-patch", result.stdout)
        self.assertNotIn("EVENT next-boundary", result.stdout)

    def test_reconciliation_failures_propagate(self):
        for status in (1, 7, 10):
            with self.subTest(status=status):
                result = run_block(reconcile_status=status)
                self.assertEqual(result.returncode, status)
                self.assertNotIn("EVENT next-boundary", result.stdout)
                self.assertNotIn("EVENT completion-patch", result.stdout)
                self.assertNotIn("RESET COMPLETE", result.stdout)
                self.assertNotIn("rollout verified", result.stdout)
                self.assertIn("cleanup remains in_progress", result.stderr)

    def test_success_records_completion_and_exits_zero(self):
        result = run_block(tail=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EVENT completion-patch", result.stdout)
        self.assertIn("RESET COMPLETE", result.stdout)
        self.assertNotIn("RESET INCOMPLETE", result.stdout)
        self.assertIn("------ WARNING:", result.stderr)
        self.assertIn("fresh notebook startup", result.stderr)

    def test_completion_patch_failure_blocks_success(self):
        for status in (1, 9):
            with self.subTest(status=status):
                result = run_block(tail=True, completion_status=status)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("EVENT reconcile", result.stdout)
                self.assertIn("EVENT completion-patch", result.stdout)
                self.assertNotIn("RESET COMPLETE", result.stdout)
                self.assertIn("Could not record reset completion", result.stderr)

    def test_completion_patch_checks_neutral_state(self):
        result = run_block()
        completion = result.stdout.split("EVENT completion-patch", 1)[1]
        for field, value in (
            ("cleanup_status", "in_progress"),
            ("workshop_type", "none"),
            ("workshop_module", "none"),
            ("mode", "beginner"),
            ("solutions_released", "false"),
        ):
            with self.subTest(field=field):
                self.assertIn(
                    '{"op":"test","path":"/data/' + field
                    + '","value":"' + value + '"}',
                    completion,
                )

    def test_cleanup_and_identity_actions_precede_reconciliation(self):
        position = SOURCE.index(START)
        for action in (
            '"$COHORT_HELPER" "${workspace_args[@]}"',
            '"$IDENTITY_RESET_HELPER" "${identity_reset_args[@]}"',
        ):
            self.assertLess(SOURCE.index(action), position)
        self.assertLess(
            SOURCE.index('"$RECONCILIATION_HELPER" --neutral-for-reset'),
            SOURCE.index(
                '{"op":"replace","path":"/data/cleanup_status","value":"complete"}'
            ),
        )

    def test_helper_is_checked_before_context_loading(self):
        check = SOURCE.index('[[ -x "$RECONCILIATION_HELPER" ]]')
        self.assertLess(check, SOURCE.index("load_workshop_context"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
