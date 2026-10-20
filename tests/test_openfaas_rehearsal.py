"""Mocked offline-rehearsal preparation; no deployment or network access."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = Path("scripts/workshops/cloud-computing-soa/openfaas/module-main.sh")


class RehearsalPreparationTests(unittest.TestCase):
    def run_preparation(self, cohort=0, activation=0, confirmation=0, reconcile=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / MODULE
            module.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / MODULE, module)

            script = root / "scripts/workshops/reconcile-workshop-applications.sh"
            script.write_text(
                'printf "RECONCILE:%s\\n" "$*"\n'
                f"exit {reconcile}\n"
            )

            mocks = f"""
cloud_module5_check() {{ echo CHECK; }}
cloud_module1_require_complete_participant_cohort() {{
  echo COHORT; return {cohort};
}}
ensure_workshop_activation_allowed() {{
  echo "GUARD:$1"; return {activation};
}}
confirm() {{ echo CONFIRM; return {confirmation}; }}
"""
            return subprocess.run(
                ["bash", "-c",
                 'source "$1"\n' + mocks + "\ncloud_module5_prepare_rehearsal",
                 "_", str(module)],
                capture_output=True, text=True, timeout=15,
            )

    def test_failed_cohort_stops_before_guard_and_reconciliation(self):
        result = self.run_preparation(cohort=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("GUARD:", result.stdout)
        self.assertNotIn("RECONCILE:", result.stdout)

    def test_failed_switch_guard_stops_before_confirmation(self):
        result = self.run_preparation(activation=2)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("CONFIRM", result.stdout)
        self.assertNotIn("RECONCILE:", result.stdout)

    def test_declined_confirmation_does_not_reconcile(self):
        result = self.run_preparation(confirmation=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RECONCILE:", result.stdout)
        self.assertIn("No rehearsal preparation", result.stdout)

    def test_success_calls_only_scoped_reconciliation(self):
        result = self.run_preparation()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = [
            "CHECK", "COHORT", "GUARD:cloud-computing-soa", "CONFIRM",
            "RECONCILE:--enable-openfaas-offline-rehearsal",
        ]
        positions = [result.stdout.index(marker) for marker in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Module 5 is not yet active", result.stdout)

    def test_reconciliation_failure_is_propagated(self):
        result = self.run_preparation(reconcile=7)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertNotIn("Offline rehearsal assets reconciled", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
