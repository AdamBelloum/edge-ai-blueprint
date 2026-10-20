"""Mocked rehearsal activation; no deployment or network access."""
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/workshops/cloud-computing-soa/openfaas/module-main.sh"


class RehearsalActivationTests(unittest.TestCase):
    def run_activation(self, cohort=0, guard=0, readiness=0,
                       confirmation=0, second_guard=0, remote=0):
        mocks = f"""
DIGITAFRICA_NAMESPACE=test-namespace
guard_calls=0
cloud_module1_require_complete_participant_cohort() {{
  echo COHORT; return {cohort};
}}
ensure_workshop_activation_allowed() {{
  guard_calls=$((guard_calls + 1))
  echo "GUARD:$guard_calls:$1"
  if [[ "$guard_calls" -eq 1 ]]; then
    return {guard}
  fi
  return {second_guard}
}}
cloud_module5_check_rehearsal_readiness() {{
  echo READINESS; return {readiness};
}}
confirm() {{ echo CONFIRM; return {confirmation}; }}
run_deployment_remote() {{
  printf 'REMOTE-BEGIN\\n%s\\nREMOTE-END\\n' "$1"
  return {remote}
}}
"""
        return subprocess.run(
            ["bash", "-c",
             'source "$1"\n' + mocks + "\ncloud_module5_activate_rehearsal",
             "_", str(MODULE)],
            capture_output=True, text=True, timeout=10,
        )

    def test_incomplete_cohort_prevents_activation(self):
        result = self.run_activation(cohort=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("GUARD:", result.stdout)
        self.assertNotIn("REMOTE-BEGIN", result.stdout)

    def test_switch_guard_prevents_readiness_and_activation(self):
        result = self.run_activation(guard=2)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("READINESS", result.stdout)
        self.assertNotIn("REMOTE-BEGIN", result.stdout)

    def test_failed_readiness_prevents_confirmation_and_activation(self):
        result = self.run_activation(readiness=3)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertNotIn("CONFIRM", result.stdout)
        self.assertNotIn("REMOTE-BEGIN", result.stdout)

    def test_declined_confirmation_preserves_state(self):
        result = self.run_activation(confirmation=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No rehearsal activation", result.stdout)
        self.assertNotIn("REMOTE-BEGIN", result.stdout)

    def test_second_guard_failure_preserves_state(self):
        result = self.run_activation(second_guard=4)
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("GUARD:2:cloud-computing-soa", result.stdout)
        self.assertNotIn("REMOTE-BEGIN", result.stdout)

    def test_success_patches_only_expected_rehearsal_state(self):
        result = self.run_activation()
        self.assertEqual(result.returncode, 0, result.stderr)
        markers = [
            "COHORT", "GUARD:1:cloud-computing-soa", "READINESS",
            "CONFIRM", "GUARD:2:cloud-computing-soa", "REMOTE-BEGIN",
        ]
        positions = [result.stdout.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

        script = result.stdout.split("REMOTE-BEGIN\n", 1)[1].split(
            "\nREMOTE-END", 1)[0]
        syntax = subprocess.run(["bash", "-n"], input=script,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        self.assertIn("namespace=test-namespace", script)
        self.assertIn("patch configmap digitafrica-workshop-state", script)
        patches = re.findall(r"-p '([^']+)'", script)
        self.assertEqual(len(patches), 1)
        self.assertEqual(json.loads(patches[0]), {"data": {
            "workshop_type": "cloud-computing-soa",
            "workshop_module": "module5",
            "mode": "beginner",
            "solutions_released": "false",
        }})
        self.assertIn("offline rehearsal is active", result.stdout)

    def test_remote_failure_does_not_report_success(self):
        result = self.run_activation(remote=7)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertNotIn("offline rehearsal is active", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
