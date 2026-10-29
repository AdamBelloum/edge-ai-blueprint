"""Isolated Spark wrapper tests: fake context and Ansible; no live resources."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/workshops/big-data/spark/participant-credentials.sh"


class ParticipantCredentialsWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        module = self.root / "scripts/workshops/big-data/spark"
        module.mkdir(parents=True)
        self.wrapper = module / SOURCE.name
        shutil.copyfile(SOURCE, self.wrapper)

        lib = self.root / "scripts/workshops/lib"
        lib.mkdir(parents=True)
        (lib / "workshop-context.sh").write_text(r'''load_workshop_context() {
  printf 'context\n' >> "$TEST_CONTEXT_RECORD"
  DIGITAFRICA_INVENTORY="$TEST_ROOT/inventory.ini"
  DIGITAFRICA_DEPLOYMENT_GROUP="${MOCK_CONTROL_GROUP-tier2_server}"
  DIGITAFRICA_DEPLOYMENT_WORKER_GROUP="${MOCK_WORKER_GROUP-tier2_agents}"
  DIGITAFRICA_NAMESPACE="${MOCK_NAMESPACE-digitafrica}"
  WORKSHOP_CONTEXT_REPOSITORY_ROOT="$TEST_ROOT"
  return "${MOCK_CONTEXT_RC:-0}"
}
''')
        self.playbook = self.root / "playbooks/reconcile-big-data-spark-credentials.yml"
        self.playbook.parent.mkdir()
        self.playbook.write_text("# Fixture only; fake Ansible never reads this.\n")
        (self.root / "inventory.ini").write_text("# Fixture inventory.\n")

        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "ansible-playbook"
        fake.write_text(r'''#!/usr/bin/env bash
printf '%s\n' "$@" > "$TEST_ARGUMENT_RECORD"
exit "${MOCK_ANSIBLE_RC:-0}"
''')
        fake.chmod(0o755)
        self.arguments = self.root / "arguments.txt"
        self.context_record = self.root / "context.txt"

    def invoke(self, *arguments, input_text="", **settings):
        for record in (self.arguments, self.context_record):
            if record.exists():
                record.unlink()
        env = os.environ.copy()
        env.update(
            TEST_ROOT=str(self.root),
            TEST_ARGUMENT_RECORD=str(self.arguments),
            TEST_CONTEXT_RECORD=str(self.context_record),
            MOCK_CONTROL_GROUP="tier2_server",
            MOCK_WORKER_GROUP="tier2_agents",
            MOCK_NAMESPACE="digitafrica",
            MOCK_CONTEXT_RC="0",
            MOCK_ANSIBLE_RC="0",
            DIGITAFRICA_ASSUME_YES="true",
            ASSUME_YES="true",
        )
        env.update(settings)
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        result = subprocess.run(
            ["bash", str(self.wrapper), *arguments],
            env=env, input=input_text, text=True,
            capture_output=True, timeout=10,
        )
        calls = self.arguments.read_text().splitlines() if self.arguments.exists() else []
        return result, calls

    def expected_arguments(self, action):
        return [
            "-i", str(self.root / "inventory.ini"), str(self.playbook),
            "--extra-vars", "big_data_control_group=tier2_server",
            "--extra-vars", "big_data_worker_group=tier2_agents",
            "--extra-vars", "big_data_credentials_namespace=digitafrica",
            "--extra-vars", "big_data_credentials_action=" + action,
        ]

    def test_plan_delegates_exact_context_without_confirmation(self):
        result, calls = self.invoke("plan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, self.expected_arguments("plan"))
        self.assertNotIn("Type apply", result.stderr)
        self.assertEqual(self.context_record.read_text().splitlines(), ["context"])

    def test_verify_delegates_exact_context_without_confirmation(self):
        result, calls = self.invoke("verify")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, self.expected_arguments("verify"))
        self.assertNotIn("Type apply", result.stderr)

    def test_verify_failure_propagates_without_applying(self):
        result, calls = self.invoke("verify", MOCK_ANSIBLE_RC="2")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(calls, self.expected_arguments("verify"))
        self.assertNotIn("big_data_credentials_action=apply", calls)

    def test_playbook_accepts_verify_without_marking_it_changed(self):
        path = ROOT / "playbooks/reconcile-big-data-spark-credentials.yml"
        play = yaml.safe_load(path.read_text())[0]
        assertions = play["tasks"][0]["ansible.builtin.assert"]["that"]
        self.assertIn("big_data_credentials_action in ['plan', 'apply', 'verify']", assertions)
        task = next(item for item in play["tasks"] if item.get("register") == "spark_staging_summary")
        self.assertTrue(task["no_log"])
        self.assertTrue(task["changed_when"].startswith("big_data_credentials_action == 'apply' and"))
        self.assertIn("'operation': big_data_credentials_action", task["ansible.builtin.command"]["stdin"])

    def test_apply_requires_exact_confirmation_even_with_auto_yes(self):
        for response in ("", "\n", "y\n", "n\n", "APPLY\n"):
            with self.subTest(response=response):
                result, calls = self.invoke("apply", input_text=response)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(calls, [])
                self.assertIn("No credential staging was performed", result.stderr)

    def test_confirmed_apply_delegates_existing_playbook(self):
        result, calls = self.invoke("apply", input_text="apply\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, self.expected_arguments("apply"))

    def test_invalid_actions_and_extra_options_do_not_load_context(self):
        for arguments in ((), ("unexpected",), ("plan", "--extra-vars", "override=1")):
            with self.subTest(arguments=arguments):
                result, calls = self.invoke(*arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(calls, [])
                self.assertFalse(self.context_record.exists())

    def test_help_does_not_load_context_or_run_ansible(self):
        result, calls = self.invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("plan|apply", result.stdout)
        self.assertEqual(calls, [])
        self.assertFalse(self.context_record.exists())

    def test_invalid_context_blocks_ansible(self):
        for settings in (
            {"MOCK_CONTROL_GROUP": "all:*"},
            {"MOCK_WORKER_GROUP": "tier2_agents,outsiders"},
            {"MOCK_CONTROL_GROUP": ""},
            {"MOCK_WORKER_GROUP": ""},
            {"MOCK_NAMESPACE": ""},
            {"MOCK_NAMESPACE": "Bad_Namespace"},
            {"MOCK_NAMESPACE": "a" * 64},
        ):
            with self.subTest(settings=settings):
                result, calls = self.invoke("plan", **settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_context_failure_propagates_without_ansible(self):
        result, calls = self.invoke("plan", MOCK_CONTEXT_RC="29")
        self.assertEqual(result.returncode, 29, result.stderr)
        self.assertEqual(calls, [])

    def test_missing_playbook_blocks_ansible(self):
        self.playbook.unlink()
        result, calls = self.invoke("plan")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(calls, [])
        self.assertIn("playbook is missing", result.stderr)

    def test_ansible_failure_propagates_without_success_claim(self):
        result, calls = self.invoke("apply", input_text="apply\n", MOCK_ANSIBLE_RC="19")
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertEqual(calls, self.expected_arguments("apply"))
        self.assertNotIn("completed successfully", result.stdout)


if __name__ == "__main__":
    unittest.main()
