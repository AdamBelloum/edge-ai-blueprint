"""Static recovery-message checks; no reset, credentials or Kubernetes access."""
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/workshops/big-data/reset-workshop.sh'


class SparkResetDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.text = SOURCE.read_text()

    def test_crashloop_is_not_reported_as_unique_credential_diagnosis(self):
        self.assertIn('not a unique credential diagnosis', self.text)
        self.assertIn('missing staged resources, group/node binding mismatch, filesystem errors or conflicting credentials', self.text)
        self.assertNotIn('means that home holds credentials the organiser did not write', self.text)

    def test_recovery_requires_inspection_without_blind_workspace_deletion(self):
        self.assertIn('Inspect the sanitised init-container status/reason and group/node binding first', self.text)
        self.assertIn('never log credential payloads', self.text)
        self.assertIn('Do not automatically delete ~/.ssh/spark-direct or reset participant workspaces', self.text)
        self.assertNotIn('Remove ~/.ssh/spark-direct for that participant', self.text)

    def test_rotation_claim_states_marker_and_conflict_conditions(self):
        self.assertIn('Unmodified credentials with a valid organiser marker can rotate', self.text)
        self.assertIn('conflicts block startup', self.text)


if __name__ == '__main__':
    unittest.main()
