"""Offline reconciliation wrapper tests with fake Ansible."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/workshops/reconcile-workshop-applications.sh"
PLAYBOOK = ROOT / "playbooks/prepare-big-data-spark-runtime.yml"
OPT_INS = {
    "--enable-hpc-runtime": {"hpc_runtime_enabled": True},
    "--enable-cloud-module3-delivery": {"cloud_module3_delivery_enabled": True},
    "--enable-openfaas-offline-rehearsal": {"cloud_module5_delivery_enabled": True},
}


class ReconciliationWrapperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        self.log = directory / "arguments.json"
        self.record = directory / "release.env"
        inventory = directory / "inventory.ini"
        inventory.write_text("[selected_control]\n[selected_workers]\n")
        values = {
            "WORKSHOP_INVENTORY": str(inventory),
            "WORKSHOP_CONTROL_PLANE_GROUP": "selected_control",
            "WORKSHOP_WORKER_GROUP": "selected_workers",
            "WORKSHOP_DEPLOYMENT_PLAYBOOK": str(PLAYBOOK),
        }
        self.record.write_text("".join(
            f"{key}={shlex.quote(value)}\n" for key, value in values.items()
        ))
        executable = directory / "ansible-playbook"
        executable.write_text(
            "#!" + sys.executable + "\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['MOCK_LOG']).write_text(json.dumps(sys.argv[1:]))\n"
            "sys.exit(int(os.environ['MOCK_EXIT']))\n"
        )
        executable.chmod(0o700)
        self.env = os.environ.copy()
        self.env.pop("BASH_ENV", None)
        self.env.pop("ENV", None)
        self.env.update({
            "PATH": str(directory) + os.pathsep + os.environ["PATH"],
            "WORKSHOP_RELEASE_RECORD": str(self.record),
            "MOCK_LOG": str(self.log),
            "MOCK_EXIT": "0",
        })
        self.prefix = [
            "-i", str(inventory), str(PLAYBOOK),
            "--tags", "workshop_application_reconciliation",
        ]

    def invoke(self, *arguments):
        self.log.unlink(missing_ok=True)
        return subprocess.run(
            ["bash", str(WRAPPER), *arguments],
            env=self.env, capture_output=True, text=True, timeout=10,
        )

    def arguments(self):
        return json.loads(self.log.read_text())

    def test_ordinary_reconciliation_has_no_new_overrides(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.arguments(), self.prefix)

    def test_neutral_mode_explicitly_disables_optional_integrations(self):
        result = self.invoke("--neutral-for-reset")
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = self.arguments()
        self.assertEqual(arguments[:-2], self.prefix)
        self.assertEqual(arguments[-2], "-e")
        self.assertEqual(json.loads(arguments[-1]), {
            "workshop_reset_neutral": True,
            "hpc_runtime_enabled": False,
            "cloud_module3_delivery_enabled": False,
            "cloud_module5_delivery_enabled": False,
        })

    def test_existing_opt_ins_are_preserved(self):
        for option, expected in OPT_INS.items():
            with self.subTest(option=option):
                result = self.invoke(option)
                self.assertEqual(result.returncode, 0, result.stderr)
                arguments = self.arguments()
                self.assertEqual(arguments[:-2], self.prefix)
                self.assertEqual(arguments[-2], "-e")
                self.assertEqual(json.loads(arguments[-1]), expected)

    def test_conflicts_are_rejected_before_context_loading(self):
        self.record.unlink()
        for option in OPT_INS:
            for arguments in (
                ("--neutral-for-reset", option),
                (option, "--neutral-for-reset"),
            ):
                with self.subTest(arguments=arguments):
                    result = self.invoke(*arguments)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("cannot be combined", result.stderr)
                    self.assertFalse(self.log.exists())

    def test_help_and_unknown_options_do_not_load_context(self):
        self.record.unlink()
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())
        result = self.invoke("--unknown")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown reconciliation option", result.stderr)
        self.assertFalse(self.log.exists())

    def test_ansible_failure_propagates(self):
        self.env["MOCK_EXIT"] = "7"
        result = self.invoke("--neutral-for-reset")
        self.assertEqual(result.returncode, 7)
        self.assertTrue(self.log.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
