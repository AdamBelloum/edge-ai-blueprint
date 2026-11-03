"""Offline organiser pilot-menu tests with disposable helpers; no VM access."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / (
    "scripts/workshops/big-data/spark/module-main.sh")
HARNESS = r'''set -e
source "$1"
BIG_DATA_SPARK_MODULE_DIR="$2"
DIGITAFRICA_INVENTORY="$TEST_INVENTORY"
DIGITAFRICA_DEPLOYMENT_WORKER_GROUP="$TEST_WORKER_GROUP"
workshop_ui_heading() { printf 'HEADING:%s\n' "$*"; }
workshop_ui_section() { printf 'SECTION:%s\n' "$*"; }
workshop_ui_option() { printf 'OPTION:%s:%s\n' "$1" "$2"; }
workshop_ui_prompt() { :; }
big_data_spark_stage1_preflight() {
  printf 'CALL_PREFLIGHT\n'
  return "${PREFLIGHT_RC:-0}"
}
ensure_workshop_activation_allowed() { printf 'CALL_GUARD\n'; }
big_data_spark_runtime_action() { printf 'FORBIDDEN_RUNTIME\n'; return 99; }
big_data_spark_activate_selected_mode() { printf 'FORBIDDEN_PUBLICATION\n'; return 99; }
big_data_spark_computation_test() { printf 'FORBIDDEN_COMPUTATION\n'; return 99; }
if [[ -n "${5:-}" ]]; then "$3" "${4:-}" "$5"; else "$3" "${4:-}"; fi
'''


class PilotMenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        self.sentinel = self.home / "unchanged-fixture"
        self.sentinel.write_text("original offline fixture")
        self.helper = self.root / "warm-transition.sh"
        self.helper.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'CALL_WARM'; printf ':<%s>' \"$@\"; printf '\\n'\n"
            "exit \"${HELPER_RC:-0}\"\n")
        self.helper.chmod(0o700)
        candidate = self.root / "stage-livy-candidate.sh"
        candidate.write_text("#!/usr/bin/env bash\nprintf 'CALL_CANDIDATE\\n'\n")
        candidate.chmod(0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shutil.copyfile(MODULE.parent / "livy_transition_scope.py",
                        self.root / "livy_transition_scope.py")
        inventory = self.bin / "ansible-inventory"
        inventory.write_text(
            '#!/usr/bin/env python3\n'
            'import json, os, pathlib, sys\n'
            'pathlib.Path(os.environ["INVENTORY_LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
            'print(os.environ["INVENTORY_JSON"])\n'
            'sys.exit(int(os.environ["INVENTORY_RC"]))\n')
        inventory.chmod(0o700)
        self.inventory_log = self.root / "inventory-calls.json"

    def run_entry(self, choices="", *, entry="big_data_spark_step2_menu",
                  action="", pilot="", preflight_rc=0, helper_rc=0,
                  hosts=("vm1", "vm2"), inventory_rc=0, missing_context=False):
        self.inventory_log.unlink(missing_ok=True)
        env = dict(os.environ, HOME=str(self.home),
                   PREFLIGHT_RC=str(preflight_rc), HELPER_RC=str(helper_rc),
                   TEST_INVENTORY=str(self.root / "inventory.ini"),
                   TEST_WORKER_GROUP="" if missing_context else "workers",
                   INVENTORY_LOG=str(self.inventory_log),
                   INVENTORY_JSON=json.dumps({"workers": {"hosts": list(hosts)}}),
                   INVENTORY_RC=str(inventory_rc),
                   PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        result = subprocess.run(
            ["bash", "-c", HARNESS, "pilot-menu-test", str(MODULE),
             str(self.root), entry, action, pilot],
            input=choices, text=True, capture_output=True, timeout=10, env=env)
        text = result.stdout + result.stderr
        self.assertNotIn("FORBIDDEN_", text)
        self.assertEqual(self.sentinel.read_text(), "original offline fixture")
        return result.returncode, text

    def transition(self, action="transition", pilot="", **kwargs):
        return self.run_entry(entry="big_data_spark_step2_transition_action",
                              action=action, pilot=pilot, **kwargs)

    def test_open_back_and_eof_do_not_operate(self):
        for choices in ("0\n", ""):
            with self.subTest(choices=choices):
                rc, text = self.run_entry(choices)
                self.assertEqual(rc, 0)
                self.assertNotIn("CALL_", text)
                self.assertIn("execution readiness remain unvalidated", text)

    def test_primary_menu_opens_submenu_without_operations(self):
        rc, text = self.run_entry("2\n0\n0\n", entry="run_big_data_spark_menu")
        self.assertEqual(rc, 0)
        self.assertEqual(text.count("HEADING:Spark / Step 2 - submission via Livy REST API"), 1)
        self.assertNotIn("CALL_", text)

    def test_syntax_delegates_exact_host_and_syntax_flag_after_preflight(self):
        rc, text = self.transition("syntax-check")
        self.assertEqual(rc, 0)
        self.assertEqual(text.count("CALL_PREFLIGHT"), 1)
        self.assertEqual(text.count("CALL_WARM:<--all-workers>:<--syntax-check>"), 1)
        self.assertLess(text.index("CALL_PREFLIGHT"), text.index("CALL_WARM"))
        self.assertIn("syntax check passed", text)
        self.assertNotIn("CALL_CANDIDATE", text)

    def test_transition_delegates_without_confirmation_bypass(self):
        rc, text = self.transition()
        self.assertEqual(rc, 0)
        self.assertEqual(text.count("CALL_WARM:<--all-workers>\n"), 1)
        self.assertLess(text.index("CALL_PREFLIGHT"), text.index("CALL_WARM"))
        self.assertIn("The helper asks for [y/N] confirmation", text)
        self.assertIn("execution readiness remain unvalidated", text)
        self.assertNotIn("<--syntax-check>", text)
        self.assertNotIn("<--yes>", text)
        self.assertNotIn("<--execute>", text)
        self.assertNotIn("CALL_CANDIDATE", text)








    def test_preflight_failure_prevents_wrapper(self):
        for action in ("syntax-check", "transition"):
            with self.subTest(action=action):
                rc, text = self.transition(action, preflight_rc=7)
                self.assertEqual(rc, 7)
                self.assertEqual(text.count("CALL_PREFLIGHT"), 1)
                self.assertNotIn("CALL_WARM", text)
                self.assertNotIn("CALL_CANDIDATE", text)

    def test_missing_wrapper_blocks_before_preflight(self):
        self.helper.unlink()
        rc, text = self.transition()
        self.assertEqual(rc, 2)
        self.assertIn("Missing executable warm-transition helper", text)
        self.assertNotIn("CALL_", text)

    def test_wrapper_failure_or_cancellation_propagates_without_retry(self):
        for action, success in (
            ("syntax-check", "Warm-transition syntax check passed"),
            ("transition", "Warm-transition helper completed"),
        ):
            for status in (1, 7):
                with self.subTest(action=action, status=status):
                    rc, text = self.transition(action, helper_rc=status)
                    self.assertEqual(rc, status)
                    self.assertEqual(text.count("CALL_WARM"), 1)
                    self.assertIn("status " + str(status), text)
                    self.assertIn("no automatic rollback or retry", text)
                    self.assertNotIn(success, text)
                    self.assertNotIn("CALL_CANDIDATE", text)

    def test_unsupported_actions_do_not_reach_any_helper(self):
        for action in ("prepare", "build", "start", "stop", "reset", "publish", "verify"):
            with self.subTest(action=action):
                rc, text = self.transition(action)
                self.assertEqual(rc, 2)
                self.assertNotIn("CALL_", text)

    def test_verification_guidance_does_not_run_probe_or_preflight(self):
        rc, text = self.run_entry(
            entry="big_data_spark_step2_verification_guidance")
        self.assertEqual(rc, 0)
        self.assertNotIn("CALL_", text)
        for required in (
            "GUIDANCE ONLY",
            "existing managed participant identity",
            "asset hashes",
            "--expected-ssh-host",
            "--expected-ssh-port",
            "--workspace",
            "--evidence-dir",
            "--maintenance-window-confirmed",
            "--submissions-paused-confirmed",
            "HTTP 404",
            "empty post-cleanup inventory",
            "closed forwarding",
            "not a remote submission lock",
            "never guess session IDs",
            "not establish cohort capacity or full-activity readiness",
            "Workspace delivery of the verifier is not automated",
        ):
            self.assertIn(required, text)

    def test_guidance_menu_option_has_no_operational_side_effect(self):
        rc, text = self.run_entry("5\n0\n")
        self.assertEqual(rc, 0)
        self.assertNotIn("CALL_", text)
        self.assertEqual(text.count("GUIDANCE ONLY:"), 1)

    def test_invalid_choice_is_not_an_operation(self):
        rc, text = self.run_entry("9\n0\n")
        self.assertEqual(rc, 0)
        self.assertIn("Choose a value from 0 through 5", text)
        self.assertNotIn("CALL_", text)

    def test_numbered_actions_dispatch_all_workers_without_host_input(self):
        for choice, suffix in (("3", ":<--syntax-check>"), ("4", "")):
            with self.subTest(choice=choice):
                rc, text = self.run_entry(choice + "\n0\n")
                self.assertEqual(rc, 0)
                self.assertEqual(text.count("CALL_WARM:<--all-workers>" + suffix + "\n"), 1)
                self.assertEqual(text.count("CALL_PREFLIGHT"), 1)
                self.assertNotIn("Choose the workshop machine", text)
                self.assertNotIn("<--limit>", text)
                self.assertFalse(self.inventory_log.exists())

    def test_host_arguments_are_refused_before_preflight(self):
        for pilot in ("vm1", "vm1,vm2", "vm*", "$(false)"):
            rc, text = self.transition(pilot=pilot)
            self.assertEqual(rc, 2)
            self.assertNotIn("CALL_", text)

    def test_menu_advertises_all_worker_local_livy(self):
        rc, text = self.run_entry("0\n")
        self.assertEqual(rc, 0)
        self.assertIn("Switch all worker nodes to local Livy", text)
        self.assertNotIn("Choose the workshop machine", text)
        self.assertNotIn("CALL_", text)


if __name__ == "__main__":
    unittest.main()
