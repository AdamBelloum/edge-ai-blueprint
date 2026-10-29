"""Wrapper routing tests using a fake Ansible executable."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/workshops/big-data/spark/teardown-runtime.sh"
PLAYBOOK = ROOT / "playbooks/teardown-big-data-spark-runtime.yml"


class WrapperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.log = self.directory / "ansible-arguments.json"
        self.inventory = self.directory / "inventory.ini"
        self.inventory.write_text("[selected_workers]\n")
        self.record = self.directory / "workshop-release.env"
        self.write_record("selected_workers")

        executable = self.directory / "ansible-playbook"
        executable.write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with open(os.environ['MOCK_ANSIBLE_LOG'], 'a') as handle:\n"
            "    handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "sys.exit(int(os.environ.get('MOCK_ANSIBLE_EXIT', '0')))\n"
        )
        executable.chmod(0o755)

        self.bash = shutil.which("bash")
        if not self.bash:
            self.skipTest("Bash is required")
        self.env = os.environ.copy()
        self.env.pop("BASH_ENV", None)
        self.env.pop("ENV", None)
        self.env.update({
            "PATH": str(self.directory) + os.pathsep + os.environ["PATH"],
            "WORKSHOP_RELEASE_RECORD": str(self.record),
            "MOCK_ANSIBLE_LOG": str(self.log),
            "MOCK_ANSIBLE_EXIT": "0",
        })

    def write_record(self, worker_group):
        values = {
            "WORKSHOP_INVENTORY": str(self.inventory),
            "WORKSHOP_CONTROL_PLANE_GROUP": "selected_control",
            "WORKSHOP_WORKER_GROUP": worker_group,
            "WORKSHOP_DEPLOYMENT_PLAYBOOK": str(
                ROOT / "playbooks/prepare-big-data-spark-runtime.yml"
            ),
        }
        self.record.write_text("".join(
            f"{key}={shlex.quote(value)}\n"
            for key, value in values.items()
        ))

    def invoke(self, *arguments):
        return subprocess.run(
            [self.bash, str(WRAPPER), *arguments],
            env=self.env, capture_output=True, text=True, timeout=20,
        )

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def arguments(self):
        """Return the first recorded call: the teardown playbook."""
        return self.calls()[0]

    def expected_prefix(self):
        return [
            "-i", str(self.inventory), str(PLAYBOOK),
            "--extra-vars", "big_data_worker_group=selected_workers",
        ]

    def test_syntax_check_has_no_execution_authorization(self):
        result = self.invoke("--syntax-check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.arguments(), self.expected_prefix() + ["--syntax-check"]
        )
        self.assertEqual(len(self.calls()), 1)

    def test_execute_authorizes_only_selected_worker_group(self):
        result = self.invoke("--execute")
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = self.arguments()
        self.assertEqual(arguments[:-2], self.expected_prefix())
        self.assertEqual(arguments[-2], "--extra-vars")
        self.assertEqual(json.loads(arguments[-1]), {
            "big_data_spark_teardown_execute": True,
        })
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        policy = calls[1]
        self.assertEqual(policy[:2], ["-i", str(self.inventory)])
        self.assertTrue(policy[2].endswith(
            "playbooks/reconcile-big-data-spark-network-policy.yml"))
        self.assertIn("big_data_network_policy_action=remove", policy)
        self.assertIn("big_data_worker_group=selected_workers", policy)
        self.assertIn("big_data_control_group=selected_control", policy)

    def test_help_and_invalid_arguments_never_invoke_ansible(self):
        cases = [
            (("--help",), 0),
            ((), 2),
            (("--unknown",), 2),
            (("--execute", "--syntax-check"), 2),
        ]
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertFalse(self.log.exists())

    def test_invalid_worker_group_never_invokes_ansible(self):
        self.write_record("workers:all")
        result = self.invoke("--execute")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_ansible_failure_propagates(self):
        self.env["MOCK_ANSIBLE_EXIT"] = "7"
        result = self.invoke("--execute")
        self.assertEqual(result.returncode, 7)
        self.assertTrue(self.log.exists())
        self.assertEqual(len(self.calls()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
