"""Real Bash Step 2 menu/dispatch with a disposable helper; no VM access."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark/module-main.sh"
HARNESS = r'''set -e
source "$1"
BIG_DATA_SPARK_MODULE_DIR="$2"
workshop_ui_heading() { printf 'HEADING:%s\n' "$*"; }
workshop_ui_section() { printf 'SECTION:%s\n' "$*"; }
workshop_ui_option() { printf 'OPTION:%s:%s\n' "$1" "$2"; }
workshop_ui_prompt() { :; }
ensure_workshop_activation_allowed() {
  printf 'CALL_GUARD:%s\n' "$1"
  return "${GUARD_RC:-0}"
}
big_data_spark_runtime_action() { printf 'FORBIDDEN_RUNTIME\n'; return 99; }
big_data_spark_activate_selected_mode() { printf 'FORBIDDEN_PUBLICATION\n'; return 99; }
big_data_spark_computation_test() { printf 'FORBIDDEN_COMPUTATION\n'; return 99; }
"$3" "${4:-}"
'''


class SparkStep2MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.helper = Path(self.temp.name) / "stage-livy-candidate.sh"
        self.helper.write_text(
            "#!/usr/bin/env bash\nprintf 'CALL_CANDIDATE:%s\\n' \"$*\"\n"
            "exit \"${HELPER_RC:-0}\"\n")
        self.helper.chmod(0o700)

    def run_menu(self, choices, *, helper_rc=0, guard_rc=0,
                 entry="big_data_spark_step2_menu", arg=""):
        env = dict(os.environ, HELPER_RC=str(helper_rc), GUARD_RC=str(guard_rc))
        result = subprocess.run(
            ["bash", "-c", HARNESS, "spark-step2-test", str(MODULE),
             self.temp.name, entry, arg], input=choices, text=True,
            capture_output=True, timeout=10, env=env)
        text = result.stdout + result.stderr
        self.assertNotIn("FORBIDDEN_", text)
        return result.returncode, text

    def test_back_and_eof_perform_no_action(self):
        for choices in ("0\n", ""):
            with self.subTest(choices=choices):
                rc, text = self.run_menu(choices)
                self.assertEqual(rc, 0)
                self.assertNotIn("CALL_", text)
                self.assertIn("execution readiness remain unvalidated", text)
                self.assertIn("maintenance confirmation required", text)

    def test_primary_option_two_opens_real_submenu_without_operations(self):
        rc, text = self.run_menu("2\n0\n0\n", entry="run_big_data_spark_menu")
        self.assertEqual(rc, 0)
        self.assertEqual(text.count("HEADING:Spark / Step 2 - submission via Livy REST API"), 1)
        self.assertNotIn("CALL_", text)
        self.assertNotIn("reserved for a future sprint", text)

    def test_syntax_check_forwards_only_syntax_flag_without_activation_guard(self):
        rc, text = self.run_menu("1\n0\n")
        self.assertEqual(rc, 0)
        self.assertEqual(text.count("CALL_CANDIDATE:--syntax-check"), 1)
        self.assertNotIn("CALL_GUARD", text)
        self.assertIn("syntax check passed", text)

    def test_stage_uses_guard_and_calls_wrapper_without_confirmation_bypass(self):
        rc, text = self.run_menu("2\n0\n")
        self.assertEqual(rc, 0)
        self.assertEqual(text.count("CALL_CANDIDATE:\n"), 1)
        self.assertEqual(text.count("CALL_GUARD:big-data"), 1)
        self.assertLess(text.index("CALL_GUARD"), text.index("CALL_CANDIDATE"))
        self.assertNotIn("CALL_CANDIDATE:--", text)
        self.assertIn("Confirm the maintenance window with [y/N] before staging.", text)
        self.assertIn("execution readiness remain unvalidated", text)

    def test_guard_failure_blocks_wrapper(self):
        rc, text = self.run_menu("2\n0\n", guard_rc=7)
        self.assertEqual(rc, 0)
        self.assertNotIn("CALL_CANDIDATE", text)
        self.assertIn("Candidate staging did not complete", text)

    def test_wrapper_failure_does_not_claim_success_or_retry(self):
        for choices, success in (("1\n0\n", "syntax check passed"),
                                 ("2\n0\n", "Candidate-staging helper completed")):
            with self.subTest(choices=choices):
                rc, text = self.run_menu(choices, helper_rc=7)
                self.assertEqual(rc, 0)
                self.assertEqual(text.count("CALL_CANDIDATE:"), 1)
                self.assertIn("status 7", text)
                self.assertNotIn(success, text)

    def test_missing_helper_blocks_dispatch_before_guard(self):
        self.helper.unlink()
        rc, text = self.run_menu("2\n0\n")
        self.assertEqual(rc, 0)
        self.assertIn("Missing executable candidate-staging helper", text)
        self.assertNotIn("CALL_", text)

    def test_unsupported_action_returns_failure_without_operations(self):
        rc, text = self.run_menu("", entry="big_data_spark_step2_action", arg="start")
        self.assertEqual(rc, 2)
        self.assertIn("Unsupported Step 2 candidate action", text)
        self.assertNotIn("CALL_", text)

    def test_invalid_submenu_choice_performs_no_action(self):
        rc, text = self.run_menu("9\n0\n")
        self.assertEqual(rc, 0)
        self.assertIn("Choose a value from 0 through 5", text)
        self.assertNotIn("CALL_", text)


if __name__ == "__main__":
    unittest.main()
