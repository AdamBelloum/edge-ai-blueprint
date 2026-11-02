"""Offline prepare/start confirmation tests; context and external helpers are fake."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DirectRuntimeConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        module = self.root / "scripts/workshops/big-data/spark"
        module.mkdir(parents=True)
        self.wrapper = module / "participant-direct-runtime.sh"
        shutil.copyfile(ROOT / "scripts/workshops/big-data/spark" / self.wrapper.name,
                        self.wrapper)
        lib = self.root / "scripts/workshops/lib"
        lib.mkdir()
        (lib / "workshop-context.sh").write_text(
            'load_workshop_context() {\n'
            'DIGITAFRICA_INVENTORY="$TEST_ROOT/inventory.ini"\n'
            'DIGITAFRICA_DEPLOYMENT_WORKER_GROUP=workers\n'
            'WORKSHOP_CONTEXT_REPOSITORY_ROOT="$TEST_ROOT"\n}\n')
        (module / "reconcile-network-policy.sh").write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$POLICY_LOG"\n')
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake = self.bin / "ansible-playbook"
        fake.write_text(
            '#!/usr/bin/env python3\nimport json, os, pathlib, sys\n'
            'pathlib.Path(os.environ["ANSIBLE_LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
            'sys.exit(int(os.environ["ANSIBLE_RC"]))\n')
        fake.chmod(0o700)
        self.calls = self.root / "ansible.json"
        self.policy = self.root / "policy.txt"

    def invoke(self, action, answer="", *, rc=0, syntax=False):
        for path in (self.calls, self.policy):
            path.unlink(missing_ok=True)
        env = dict(os.environ, TEST_ROOT=str(self.root), ANSIBLE_LOG=str(self.calls),
                   POLICY_LOG=str(self.policy), ANSIBLE_RC=str(rc), ASSUME_YES="true",
                   DIGITAFRICA_ASSUME_YES="true",
                   PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        args = ["bash", str(self.wrapper), action]
        if syntax:
            args.append("--syntax-check")
        return subprocess.run(args, input=answer, env=env, text=True,
                              capture_output=True, timeout=10)

    def test_y_and_uppercase_y_confirm_prepare_and_start(self):
        for action in ("prepare", "start"):
            for answer in ("y\n", "Y\n"):
                with self.subTest(action=action, answer=answer):
                    result = self.invoke(action, answer)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    args = json.loads(self.calls.read_text())
                    self.assertIn("big_data_worker_group=workers", args)
                    self.assertIn("big_data_direct_action=" + action, args)
                    self.assertEqual(self.policy.exists(), action == "start")
                    if action == "start":
                        self.assertEqual(self.policy.read_text().splitlines(), ["apply"])

    def test_default_no_and_other_inputs_do_not_call_external_helpers(self):
        for action in ("prepare", "start"):
            for answer in ("", "\n", "n\n", "N\n", "yes\n", action + "\n", " y\n", "y \n"):
                with self.subTest(action=action, answer=answer):
                    result = self.invoke(action, answer)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertFalse(self.calls.exists())
                    self.assertFalse(self.policy.exists())

    def test_syntax_check_needs_no_confirmation_or_policy_write(self):
        for action in ("prepare", "start"):
            with self.subTest(action=action):
                result = self.invoke(action, syntax=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--syntax-check", json.loads(self.calls.read_text()))
                self.assertFalse(self.policy.exists())

    def test_ansible_failure_propagates_and_blocks_policy_reconciliation(self):
        for action in ("prepare", "start"):
            with self.subTest(action=action):
                result = self.invoke(action, "y\n", rc=19)
                self.assertEqual(result.returncode, 19, result.stderr)
                self.assertTrue(self.calls.exists())
                self.assertFalse(self.policy.exists())


if __name__ == "__main__":
    unittest.main()
