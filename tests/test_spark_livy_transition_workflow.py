# Offline scope, wrapper, Ansible ordering and isolated import-closure checks.
import ast
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
HELPERS = ROOT / "scripts/workshops/big-data/spark"
sys.path.insert(0, str(HELPERS))
import livy_transition_scope as scope
import livy_transition_live as live
from teardown_directory import locked_submission_runtime


class WorkflowTests(unittest.TestCase):
    def test_exact_nested_inventory_membership_and_refusals(self):
        data = {"workers": {"children": ["leaf"]},
                "leaf": {"hosts": ["pilot"]},
                "foreign": {"hosts": ["other"]}, "_meta": {"hostvars": {}}}
        self.assertEqual(scope.validate_scope(data, "workers", "pilot"), "pilot")
        for host in ("other", "workers", "leaf", "pilot:other", "pilot*", "-pilot"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                scope.validate_scope(data, "workers", host)

    def test_real_shared_lock_is_the_default(self):
        self.assertIs(live.run_transition.__kwdefaults__["submission_lock"],
                      locked_submission_runtime)

    def test_wrapper_scope_syntax_acknowledgement_and_context_refusals(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / "scripts/workshops/big-data/spark"
            scripts.mkdir(parents=True)
            for name in ("warm-transition.sh", "livy_transition_scope.py"):
                shutil.copyfile(HELPERS / name, scripts / name)
            library = root / "scripts/workshops/lib"
            library.mkdir()
            (library / "workshop-context.sh").write_text(
                'load_workshop_context() {\n'
                'DIGITAFRICA_INVENTORY="$TEST_ROOT/inventory"\n'
                'DIGITAFRICA_DEPLOYMENT_WORKER_GROUP=workers\n'
                'WORKSHOP_CONTEXT_REPOSITORY_ROOT="${TEST_CONTEXT_ROOT:-$TEST_ROOT}"\n'
                '}\n')
            binary = root / "bin"
            binary.mkdir()
            inventory = binary / "ansible-inventory"
            inventory.write_text(
                '#!/usr/bin/env python3\nimport json\n'
                'print(json.dumps({"workers":{"hosts":["pilot"]},'
                '"_meta":{"hostvars":{}}}))\n')
            playbook = binary / "ansible-playbook"
            playbook.write_text(
                '#!/usr/bin/env python3\nimport json,os,sys\n'
                'open(os.environ["CALL_LOG"],"a").write(json.dumps(sys.argv[1:])+"\\n")\n')
            for file in (inventory, playbook):
                file.chmod(0o700)
            log = root / "calls"
            env = dict(os.environ, TEST_ROOT=str(root), CALL_LOG=str(log),
                       PATH=str(binary) + os.pathsep + os.environ["PATH"])
            env.pop("TEST_CONTEXT_ROOT", None)

            def invoke(flags, answer="", environment=None):
                return subprocess.run(
                    ["bash", str(scripts / "warm-transition.sh"), *flags],
                    env=env if environment is None else environment,
                    input=answer, text=True, capture_output=True)

            result = invoke(["--limit", "pilot", "--syntax-check"])
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(calls), 1)
            args = calls[0]
            self.assertEqual(args[args.index("--limit") + 1], "pilot")
            self.assertIn("--syntax-check", args)
            variables = json.loads(args[args.index("--extra-vars") + 1])
            self.assertFalse(variables["big_data_livy_transition_submissions_paused"])

            for flags in (
                ["--limit", "workers", "--syntax-check"],
                ["--limit", "pilot*", "--syntax-check"],
                ["--syntax-check"],
                ["--limit", "pilot", "--syntax-check", "--syntax-check"],
                ["--limit", "pilot", "--limit", "other"],
            ):
                with self.subTest(flags=flags):
                    self.assertNotEqual(invoke(flags).returncode, 0)
            self.assertNotEqual(invoke(["--limit", "pilot"], "wrong\n").returncode, 0)
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            wrong_context = dict(env, TEST_CONTEXT_ROOT=str(elsewhere))
            self.assertNotEqual(
                invoke(["--limit", "pilot", "--syntax-check"],
                       environment=wrong_context).returncode, 0)
            self.assertEqual(len(log.read_text().splitlines()), 1)

            result = invoke(["--limit", "pilot"],
                            "transition-pilot-submissions-paused\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            args = calls[-1]
            self.assertNotIn("--syntax-check", args)
            self.assertEqual(args[args.index("--limit") + 1], "pilot")
            variables = json.loads(args[args.index("--extra-vars") + 1])
            for key in (
                "big_data_livy_stage_maintenance_confirmed",
                "big_data_livy_build_candidate",
                "big_data_livy_transition_maintenance_confirmed",
                "big_data_livy_transition_submissions_paused",
            ):
                self.assertIs(variables[key], True)

    def test_order_failstop_handoff_and_isolated_import_closure(self):
        plays = yaml.safe_load(
            (ROOT / "playbooks/transition-big-data-spark-livy.yml").read_text())
        imports = [p["ansible.builtin.import_playbook"] for p in plays
                   if "ansible.builtin.import_playbook" in p]
        self.assertEqual(imports, [
            "stage-big-data-spark-livy-candidate.yml",
            "build-big-data-livy-image.yml"])
        self.assertTrue(plays[0]["any_errors_fatal"])
        self.assertIn("ansible_play_hosts_all == [big_data_livy_pilot_host]",
                      plays[0]["tasks"][0]["ansible.builtin.assert"]["that"])
        last = plays[-1]
        self.assertTrue(last["any_errors_fatal"])
        self.assertEqual(last["serial"], 1)
        tasks = last["tasks"]
        delivered = set(next(t for t in tasks
                             if "ansible.builtin.copy" in t)["loop"])
        pending, visited = ["livy_transition_live.py"], set()
        while pending:
            name = pending.pop()
            if name in visited:
                continue
            visited.add(name)
            self.assertIn(name, delivered)
            for node in ast.walk(ast.parse((HELPERS / name).read_text())):
                if isinstance(node, ast.ImportFrom):
                    modules = [node.module]
                elif isinstance(node, ast.Import):
                    modules = [item.name for item in node.names]
                else:
                    modules = []
                for module in modules:
                    local = module.split(".")[0] + ".py" if module else ""
                    if local and (HELPERS / local).is_file():
                        pending.append(local)
        command = next(t["ansible.builtin.command"]["argv"] for t in tasks
                       if "ansible.builtin.command" in t)
        self.assertIn("{{ livy_delivery.path }}", command)
        self.assertIn("--submissions-paused-confirmed", command)
        for name in imports:
            imported = yaml.safe_load((ROOT / "playbooks" / name).read_text())
            self.assertTrue(imported[0]["any_errors_fatal"])
            self.assertEqual(imported[0]["serial"], 1)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in delivered:
                shutil.copyfile(HELPERS / name, directory / name)
            env = dict(os.environ)
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)
            result = subprocess.run(
                [sys.executable, "-B", str(directory / "livy_transition_live.py"),
                 "--help"], cwd=directory, env=env,
                text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
