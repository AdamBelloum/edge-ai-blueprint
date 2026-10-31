"""Offline manifest/orchestration tests. All Ansible commands are replaced."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hpc_manifest_builder", ROOT / "scripts/workshops/hpc/build-cleanup-manifests.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def inventory():
    return {
        "workers": {"hosts": ["worker-1", "worker-2"]},
        "central": {"hosts": ["central-1"]},
        "_meta": {"hostvars": {}},
    }


class ManifestTests(unittest.TestCase):
    def build(self, data):
        return builder.build(ROOT, data, "workers", "central")

    def test_installation_allowlists_content_and_host_scopes(self):
        plan = self.build(inventory())
        self.assertEqual(plan["hpc_cleanup_hosts"], ["worker-1", "worker-2", "central-1"])
        workspace, runtime = plan["hpc_cleanup_jobs"]
        self.assertEqual(workspace["hosts"], ["worker-1", "worker-2"])
        self.assertEqual(runtime["hosts"], ["central-1"])
        expected = builder.read_yaml(ROOT / "roles/hpc_workspace/defaults/main.yml")["hpc_workspace_files"]
        self.assertEqual([e["path"] for e in workspace["manifest"]["files"]], expected)
        for entry in workspace["manifest"]["files"]:
            source = ROOT / "workshop_assets/hpc" / entry["path"]
            self.assertEqual(entry["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        sources = {
            "environment.yml": ROOT / "workshop_assets/hpc/runtime/environment.yml",
            "prepare-hpc-environment.sh": ROOT / "roles/hpc_runtime/files/prepare-hpc-environment.sh",
            "hpc-notebook-launch.sh": ROOT / "roles/hpc_runtime/files/hpc-notebook-launch.sh",
        }
        self.assertEqual({e["path"] for e in runtime["manifest"]["files"]}, set(sources))
        for entry in runtime["manifest"]["files"]:
            self.assertEqual(entry["sha256"], hashlib.sha256(sources[entry["path"]].read_bytes()).hexdigest())

    def test_nested_groups_and_overlap_are_deduplicated(self):
        data = inventory()
        data["workers"] = {"hosts": ["worker-1"], "children": ["remote"]}
        data["remote"] = {"hosts": ["worker-1", "worker-3"]}
        data["central"] = {"hosts": ["worker-1"]}
        plan = self.build(data)
        self.assertEqual(plan["hpc_cleanup_hosts"], ["worker-1", "worker-3"])
        self.assertEqual(plan["hpc_cleanup_jobs"][1]["hosts"], ["worker-1"])

    def test_missing_empty_or_cyclic_groups_are_refused(self):
        for group in ("workers", "central"):
            for value in (None, {"hosts": []}):
                with self.subTest(group=group, value=value):
                    data = inventory()
                    if value is None:
                        del data[group]
                    else:
                        data[group] = value
                    with self.assertRaises(ValueError):
                        self.build(data)
        data = inventory()
        data["workers"]["children"] = ["workers"]
        with self.assertRaises(ValueError):
            self.build(data)

    def test_overrides_are_refused_only_on_selected_hosts(self):
        for key, value in (
            ("hpc_workspace_host_path", "/home/adam"),
            ("hpc_runtime_host_path", "/opt/other"),
            ("hpc_workspace_source", "/other/source"),
            ("hpc_runtime_environment_source", "/other/environment.yml"),
            ("hpc_workspace_files", ["personal.txt"]),
        ):
            with self.subTest(key=key):
                data = inventory()
                data["_meta"]["hostvars"] = {"worker-1": {key: value}}
                with self.assertRaises(ValueError):
                    self.build(data)
                data["_meta"]["hostvars"] = {"unrelated": {key: value}}
                self.assertEqual(len(self.build(data)["hpc_cleanup_hosts"]), 3)

    def test_broad_groups_and_host_patterns_are_refused(self):
        for name in ("all", "ungrouped", "workers:all"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    builder.ordered_hosts(inventory(), name)
        data = inventory()
        data["workers"] = {"hosts": ["worker-1:all"]}
        with self.assertRaises(ValueError):
            self.build(data)

    def test_playbook_requires_fleet_preflight_before_execution(self):
        play, = yaml.safe_load((ROOT / "playbooks/reset-hpc-staging.yml").read_text())
        self.assertEqual(play["strategy"], "linear")
        self.assertIs(play["any_errors_fatal"], True)
        self.assertIs(play["vars"]["hpc_cleanup_execute"], False)
        commands = [task for task in play["tasks"] if "ansible.builtin.script" in task]
        self.assertEqual(len(commands), 2)
        self.assertIn("--check", commands[0]["ansible.builtin.script"]["cmd"])
        self.assertIn("--execute", commands[1]["ansible.builtin.script"]["cmd"])
        self.assertIn("hpc_cleanup_execute | bool", commands[1]["when"])


def invoke(arguments, data=None, inventory_status=0, playbook_status=0):
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        hpc = base / "scripts/workshops/hpc"
        library = base / "scripts/workshops/lib"
        hpc.mkdir(parents=True)
        library.mkdir(parents=True)
        for name in ("cleanup-staging.sh", "build-cleanup-manifests.py", "cleanup-staged-files.py"):
            shutil.copy2(ROOT / "scripts/workshops/hpc" / name, hpc / name)
        (library / "workshop-context.sh").write_text(
            'load_workshop_context() {\n'
            '  WORKSHOP_CONTEXT_REPOSITORY_ROOT="$MOCK_ROOT"\n'
            '  DIGITAFRICA_INVENTORY="$MOCK_INVENTORY"\n'
            '  DIGITAFRICA_DEPLOYMENT_WORKER_GROUP=workers\n'
            '  DIGITAFRICA_DEPLOYMENT_GROUP=central\n'
            '}\n'
        )
        fakebin = base / "bin"
        fakebin.mkdir()
        log = base / "calls.jsonl"
        fixture = base / "inventory.json"
        fixture.write_text(json.dumps(data if data is not None else inventory()))
        tmp = base / "tmp"
        tmp.mkdir()
        common = (
            f'#!{sys.executable}\n'
            'import json, os, pathlib, sys\n'
            'def record(event):\n'
            '    with open(os.environ["MOCK_LOG"], "a") as stream:\n'
            '        stream.write(json.dumps(event) + "\\n")\n'
        )
        (fakebin / "ansible-inventory").write_text(common +
            'record({"command": "inventory", "args": sys.argv[1:]})\n'
            'status = int(os.environ["MOCK_INVENTORY_STATUS"])\n'
            'if status == 0: print(pathlib.Path(os.environ["MOCK_INVENTORY"]).read_text())\n'
            'sys.exit(status)\n'
        )
        (fakebin / "ansible-playbook").write_text(common +
            'args = sys.argv[1:]\n'
            'manifest_path = next(arg[1:] for arg in args if arg.startswith("@"))\n'
            'manifest = json.loads(pathlib.Path(manifest_path).read_text())\n'
            'record({"command": "playbook", "args": args, "manifest": manifest, "manifest_path": manifest_path})\n'
            'sys.exit(int(os.environ["MOCK_PLAYBOOK_STATUS"]))\n'
        )
        for command in fakebin.iterdir():
            command.chmod(0o700)
        environment = os.environ.copy()
        for key in ("BASH_ENV", "ENV"):
            environment.pop(key, None)
        environment.update(
            PATH=str(fakebin) + os.pathsep + environment.get("PATH", ""),
            TMPDIR=str(tmp), MOCK_ROOT=str(ROOT), MOCK_INVENTORY=str(fixture),
            MOCK_LOG=str(log), MOCK_INVENTORY_STATUS=str(inventory_status),
            MOCK_PLAYBOOK_STATUS=str(playbook_status), PYTHONDONTWRITEBYTECODE="1",
        )
        result = subprocess.run(
            ["bash", str(hpc / "cleanup-staging.sh"), *arguments],
            env=environment, capture_output=True, text=True, timeout=20,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        remaining = list(tmp.iterdir())
        return result, calls, remaining


class OrchestrationTests(unittest.TestCase):
    def test_modes_forward_correct_scope_and_remove_temporary_exports(self):
        for mode, value in (("--check", "false"), ("--execute", "true")):
            with self.subTest(mode=mode):
                data = inventory()
                data["_meta"]["hostvars"]["worker-1"] = {"ansible_password": "DO_NOT_LOG_TEST_PASSWORD"}
                result, calls, remaining = invoke([mode], data=data)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([c["command"] for c in calls], ["inventory", "playbook"])
                self.assertIn("hpc_cleanup_execute=" + value, calls[-1]["args"])
                self.assertEqual(calls[-1]["manifest"]["hpc_cleanup_hosts"], ["worker-1", "worker-2", "central-1"])
                self.assertNotIn("DO_NOT_LOG_TEST_PASSWORD", result.stdout + result.stderr + json.dumps(calls))
                self.assertEqual(remaining, [])

    def test_inventory_failure_blocks_playbook_and_preserves_status(self):
        result, calls, remaining = invoke(["--execute"], inventory_status=17)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual([c["command"] for c in calls], ["inventory"])
        self.assertEqual(remaining, [])

    def test_manifest_failure_blocks_playbook(self):
        data = inventory()
        data["workers"] = {"hosts": []}
        result, calls, remaining = invoke(["--execute"], data=data)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual([c["command"] for c in calls], ["inventory"])
        self.assertEqual(remaining, [])

    def test_playbook_failure_propagates(self):
        result, calls, remaining = invoke(["--execute"], playbook_status=23)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual([c["command"] for c in calls], ["inventory", "playbook"])
        self.assertEqual(remaining, [])

    def test_help_and_invalid_options_do_not_load_context_or_run_commands(self):
        for args in (["--help"], ["-h"], [], ["--unknown"], ["--execute", "--check"]):
            with self.subTest(args=args):
                result, calls, remaining = invoke(args)
                self.assertEqual(result.returncode, 0 if args in (["--help"], ["-h"]) else 2)
                self.assertEqual(calls, [])
                self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
