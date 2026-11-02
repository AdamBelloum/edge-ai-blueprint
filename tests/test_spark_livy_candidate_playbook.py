"""Structural checks for isolated candidate delivery; no Ansible execution."""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class CandidateDeliveryPlaybookTests(unittest.TestCase):
    def setUp(self):
        self.play = yaml.safe_load(
            (ROOT / "playbooks/stage-big-data-spark-livy-candidate.yml").read_text())[0]
        self.tasks = self.play["tasks"]

    def test_serial_target_and_no_preparation_role(self):
        self.assertEqual(self.play["hosts"], "{{ big_data_worker_group }}")
        self.assertEqual(self.play["serial"], 1)
        self.assertTrue(self.play["any_errors_fatal"])
        self.assertNotIn("roles", self.play)
        for task in self.tasks:
            self.assertFalse(any(key.endswith((
                "include_role", "import_role", "include_tasks", "import_tasks"))
                for key in task))

    def test_only_command_is_verified_delivery_entry_point(self):
        commands = [task["ansible.builtin.command"]["argv"] for task in self.tasks
                    if "ansible.builtin.command" in task]
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0][1].endswith("/helpers/livy_candidate_deliver.py"))
        self.assertEqual(commands[0][-1], "--maintenance-window-confirmed")

    def test_all_file_destinations_are_temporary(self):
        for task in self.tasks:
            for kind in ("copy", "template", "file", "get_url"):
                module = task.get("ansible.builtin." + kind)
                if module:
                    path = module.get("dest", module.get("path"))
                    self.assertNotIn("/opt/", path)
                    self.assertIn("{{", path)
                    self.assertNotEqual(module.get("state"), "absent")

    def test_maintenance_and_check_mode_gate_precede_all_writes(self):
        gate = next(i for i, task in enumerate(self.tasks)
                    if "Require explicit maintenance" in task["name"])
        allocation = next(i for i, task in enumerate(self.tasks)
                          if "ansible.builtin.tempfile" in task)
        self.assertLess(gate, allocation)
        checks = self.tasks[gate]["ansible.builtin.assert"]["that"]
        self.assertIn("not ansible_check_mode", checks)
        self.assertIn("big_data_livy_stage_maintenance_confirmed | default(false) | bool",
                      checks)

    def test_archive_download_is_checksum_locked_with_tls(self):
        download = next(task["ansible.builtin.get_url"] for task in self.tasks
                        if "ansible.builtin.get_url" in task)
        self.assertEqual(download["checksum"], "sha512:{{ big_data_livy_archive_sha512 }}")
        self.assertTrue(download["validate_certs"])
        self.assertEqual(download["mode"], "0600")

    def test_delivered_helpers_exist_and_include_staging_chain(self):
        task = next(task for task in self.tasks
                    if "local import closure" in task["name"])
        required = {"livy_candidate_deliver.py", "livy_candidate_delivery.py",
                    "livy_candidate_stage.py", "livy_candidate_verify.py",
                    "livy_candidate_compose.py", "livy_candidate_observe.py",
                    "livy_candidate_assets.py"}
        self.assertTrue(required <= set(task["loop"]))
        for name in task["loop"]:
            self.assertTrue((ROOT / "scripts/workshops/big-data/spark" / name).is_file())


if __name__ == "__main__":
    unittest.main()
