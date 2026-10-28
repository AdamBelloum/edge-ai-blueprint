"""Mocked Bash menu tests: no inventory, services or credential access."""
from pathlib import Path
import subprocess
import unittest

MODULE = Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark/module-main.sh"
HARNESS = r'''set -e
source "$1"
workshop_ui_heading() { printf 'HEADING:%s\n' "$*"; }
workshop_ui_section() { printf 'SECTION:%s\n' "$*"; }
workshop_ui_option() { printf 'OPTION:%s:%s\n' "$1" "$2"; }
workshop_ui_prompt() { :; }
big_data_spark_activate_selected_mode() {
  printf 'CALL_WORKSPACE:%s\n' "$1"
  return "${MOCK_PREPARE_RC:-0}"
}
big_data_spark_future_unavailable() {
  printf 'CALL_UNAVAILABLE:%s\n' "$1"
  return 2
}
big_data_spark_show_status() { printf 'CALL_STATUS\n'; }
big_data_spark_runtime_action() { printf 'CALL_RUNTIME:%s\n' "$1"; }
big_data_spark_computation_test() { printf 'CALL_TEST:%s\n' "$1"; }
MOCK_PREPARE_RC="$2"
run_big_data_spark_menu
'''


class SparkMenuSimplificationTests(unittest.TestCase):
    def run_menu(self, choices, prepare_rc=0):
        result = subprocess.run(
            ["bash", "-c", HARNESS, "spark-menu-test", str(MODULE), str(prepare_rc)],
            input=choices, text=True, capture_output=True, timeout=10, check=True)
        return result.stdout + result.stderr

    def test_primary_menu_has_four_choices_and_explicit_wip_limits(self):
        text = self.run_menu("0\n")
        self.assertIn("OPTION:1:Prepare Step 1 - work-in-progress", text)
        self.assertIn("OPTION:2:Prepare Step 2 - work-in-progress", text)
        self.assertIn("OPTION:3:Show workshop status", text)
        self.assertIn("OPTION:4:Maintenance and organiser tests", text)
        self.assertIn("does not start services", text)
        self.assertIn("selecting it performs no changes", text)
        self.assertNotIn("OPTION:5:", text)
        self.assertNotIn("Advanced", text)
        self.assertNotIn("CALL_", text)

    def test_step1_retains_workspace_only_action(self):
        text = self.run_menu("1\n0\n")
        self.assertEqual(text.count("CALL_WORKSPACE:beginner"), 1)
        self.assertNotIn("CALL_RUNTIME", text)
        self.assertNotIn("CALL_TEST", text)

    def test_step2_is_unavailable_without_publication_or_runtime_action(self):
        text = self.run_menu("2\n0\n")
        self.assertIn("CALL_UNAVAILABLE:Step 2 integrated preparation", text)
        self.assertNotIn("CALL_WORKSPACE", text)
        self.assertNotIn("CALL_RUNTIME", text)
        self.assertNotIn("CALL_TEST", text)

    def test_status_reuses_existing_status_action(self):
        text = self.run_menu("3\n0\n")
        self.assertEqual(text.count("CALL_STATUS"), 1)
        self.assertNotIn("CALL_RUNTIME", text)

    def test_runtime_tools_preserve_existing_actions(self):
        for option, action in ((1, "prepare"), (2, "build"), (3, "start")):
            with self.subTest(option=option):
                text = self.run_menu(f"4\n{option}\n0\n0\n")
                self.assertEqual(text.count("CALL_RUNTIME:" + action), 1)
                self.assertNotIn("CALL_WORKSPACE", text)
                self.assertNotIn("CALL_TEST", text)

    def test_computation_tools_preserve_direct_and_livy_actions(self):
        for option, action in ((4, "direct"), (5, "livy")):
            with self.subTest(option=option):
                text = self.run_menu(f"4\n{option}\n0\n0\n")
                self.assertEqual(text.count("CALL_TEST:" + action), 1)
                self.assertNotIn("CALL_RUNTIME", text)

    def test_republication_is_available_under_recovery(self):
        text = self.run_menu("4\n6\n0\n0\n")
        self.assertEqual(text.count("CALL_WORKSPACE:beginner"), 1)
        self.assertNotIn("CALL_RUNTIME", text)

    def test_submenu_back_returns_to_primary_menu(self):
        text = self.run_menu("4\n0\n0\n")
        self.assertEqual(text.count("HEADING:Big Data / Spark Beginner"), 2)
        self.assertEqual(text.count("HEADING:Spark / Maintenance"), 1)
        self.assertNotIn("CALL_", text)

    def test_eof_exits_without_an_action(self):
        text = self.run_menu("")
        self.assertNotIn("CALL_", text)

    def test_failed_workspace_action_is_not_reported_as_complete(self):
        text = self.run_menu("1\n0\n", prepare_rc=7)
        self.assertIn("Spark Step 1 workspace preparation did not complete.", text)
        self.assertNotIn("CALL_RUNTIME", text)


if __name__ == "__main__":
    unittest.main()
