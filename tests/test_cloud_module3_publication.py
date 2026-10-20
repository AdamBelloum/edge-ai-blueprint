"""Offline publication sequencing; no deployment or identity access."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts/workshops/cloud-computing-soa/module3-main.sh"


class Module3PublicationTests(unittest.TestCase):
    def run_publication(self, failure="", mode="beginner"):
        return subprocess.run(
            ["bash", "-c", r'''
set -euo pipefail
source "$1"
FAILURE="$2"
step() {
  printf 'STEP:%s\n' "$1"
  [[ "$FAILURE" != "$1" ]]
}
cloud_module2_require_complete_participant_cohort() { step cohort; }
ensure_workshop_activation_allowed() {
  [[ "$1" == cloud-computing-soa ]] || return 2
  step switch
}
cloud_module3_check_activation_readiness() {
  [[ "$1" == beginner || "$1" == advanced ]] || return 2
  step readiness
}
confirm() {
  [[ "$1" == *"teaching files only"* ]] || return 2
  [[ "$1" == *"runtime validation is pending"* ]] || return 2
  step confirmation
}
cloud_module3_set_workshop_state() { printf 'PATCH:%s\n' "$1"; }
ASSUME_YES=true
cloud_module3_activate_selected_mode "$3"
''', "module3-publication-test", str(CONTROLLER), failure, mode],
            capture_output=True, text=True, timeout=10,
        )

    def test_both_modes_require_all_guards_and_confirmation(self):
        for mode in ("beginner", "advanced"):
            with self.subTest(mode=mode):
                result = self.run_publication(mode=mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), [
                    "STEP:cohort", "STEP:switch", "STEP:readiness",
                    "STEP:confirmation", f"PATCH:{mode}",
                ])
                self.assertIn("NOT runtime-validated", result.stderr)
                self.assertIn("does not provide Docker access", result.stderr)

    def test_each_failed_guard_prevents_state_update(self):
        order = ["cohort", "switch", "readiness", "confirmation"]
        for index, failure in enumerate(order):
            with self.subTest(failure=failure):
                result = self.run_publication(failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    result.stdout.splitlines(),
                    [f"STEP:{name}" for name in order[:index + 1]],
                )
                self.assertNotIn("PATCH:", result.stdout)

    def test_invalid_mode_rejects_before_any_guard(self):
        for mode in ("", "solutions", "invalid"):
            with self.subTest(mode=mode):
                result = self.run_publication(mode=mode)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")

    def test_missing_dependencies_fail_closed(self):
        result = subprocess.run(
            ["bash", "-c",
             'set -eu; source "$1"; cloud_module3_activate_selected_mode beginner',
             "module3-test", str(CONTROLLER)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("publication blocked: missing helper", result.stderr)

    def test_assume_yes_does_not_replace_explicit_confirmation(self):
        result = subprocess.run(
            ["bash", "-c", r'''
set -eu
source "$1"
ASSUME_YES=true
cloud_module3_confirm_delivery_only
''', "module3-test", str(CONTROLLER)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Explicit organiser confirmation is unavailable", result.stderr)



class Module3RealConfirmationTests(unittest.TestCase):
    def run_confirmation(self, answer):
        return subprocess.run(
            ["bash", "-c", r'''
set -euo pipefail
source "$1/scripts/lib/common.sh"
source "$1/scripts/workshops/cloud-computing-soa/module3-main.sh"
DIGITAFRICA_ASSUME_YES=true
ASSUME_YES=true
status=0
cloud_module3_confirm_delivery_only || status=$?
printf 'RESULT:%s\n' "$status"
printf 'RESTORED:%s:%s\n' "$DIGITAFRICA_ASSUME_YES" "$ASSUME_YES"
exit "$status"
''', "module3-real-confirmation", str(ROOT)],
            input=answer, capture_output=True, text=True, timeout=10,
        )

    def test_auto_yes_cannot_override_decline_or_eof(self):
        for answer in ("n\n", "\n", ""):
            with self.subTest(answer=answer):
                result = self.run_confirmation(answer)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("NOT runtime-validated", result.stderr)
                self.assertIn("RESTORED:true:true", result.stdout)
                self.assertNotIn(
                    "Automatically confirmed", result.stdout + result.stderr
                )

    def test_explicit_yes_is_accepted_and_caller_flags_are_restored(self):
        for answer in ("y\n", "yes\n"):
            with self.subTest(answer=answer):
                result = self.run_confirmation(answer)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("RESULT:0", result.stdout)
                self.assertIn("RESTORED:true:true", result.stdout)


if __name__ == "__main__":
    unittest.main()
