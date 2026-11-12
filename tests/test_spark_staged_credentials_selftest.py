import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark/stage_credential_secrets.py"


class StageCredentialSecretsSelfTest(unittest.TestCase):
    def test_script_self_test_passes(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--self-test"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stderr, r"Ran \d+ tests")


if __name__ == "__main__":
    unittest.main()
