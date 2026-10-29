"""Offline checks for the Spark network-policy wrapper.

Run from the repository root:
    python3 tests/test_spark_network_policy_wrapper.py
"""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/workshops/big-data/spark/reconcile-network-policy.sh"


def run(*args):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)


class WrapperTests(unittest.TestCase):
    def test_script_is_syntactically_valid(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(SCRIPT)]).returncode, 0)

    def test_help_exits_cleanly(self):
        result = run("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("plan|apply|remove", result.stdout)

    def test_missing_or_unknown_action_is_refused_before_any_context_load(self):
        for args in ((), ("bogus",), ("apply", "extra")):
            result = run(*args)
            self.assertEqual(result.returncode, 2, args)
            self.assertIn("Usage:", result.stderr)

    def test_wrapper_targets_the_policy_playbook_only(self):
        text = SCRIPT.read_text()
        self.assertIn("reconcile-big-data-spark-network-policy.yml", text)
        self.assertNotIn("--limit", text)
        self.assertNotIn("rm -", text)


if __name__ == "__main__":
    unittest.main()
