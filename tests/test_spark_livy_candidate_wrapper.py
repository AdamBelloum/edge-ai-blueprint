"""Wrapper tests use a disposable context and fake Ansible; no VM contact."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CandidateStagingWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        relative = Path("scripts/workshops/big-data/spark/stage-livy-candidate.sh")
        self.wrapper = self.root / relative
        self.wrapper.parent.mkdir(parents=True)
        shutil.copy2(ROOT / relative, self.wrapper)
        library = self.root / "scripts/workshops/lib/workshop-context.sh"
        library.parent.mkdir(parents=True)
        library.write_text(
            'load_workshop_context() {\n'
            '  DIGITAFRICA_INVENTORY="$FAKE_INVENTORY"\n'
            '  DIGITAFRICA_DEPLOYMENT_WORKER_GROUP="$FAKE_GROUP"\n'
            '  WORKSHOP_CONTEXT_REPOSITORY_ROOT="$FAKE_ROOT"\n'
            '}\n')
        playbook = self.root / "playbooks/stage-big-data-spark-livy-candidate.yml"
        playbook.parent.mkdir()
        playbook.write_text("---\n[]\n")
        self.capture = self.root / "captured.json"
        binary = self.root / "bin/ansible-playbook"
        binary.parent.mkdir()
        binary.write_text(
            '#!/usr/bin/env python3\n'
            'import json, os, pathlib, sys\n'
            'pathlib.Path(os.environ["FAKE_CAPTURE"]).write_text(json.dumps(sys.argv[1:]))\n')
        binary.chmod(0o755)
        self.env = dict(os.environ, FAKE_INVENTORY=str(self.root / "inventory.ini"),
                        FAKE_GROUP="workers", FAKE_ROOT=str(self.root),
                        FAKE_CAPTURE=str(self.capture),
                        PATH=str(binary.parent) + os.pathsep + os.environ["PATH"])

    def run_wrapper(self, *args, answer=""):
        return subprocess.run(
            ["bash", str(self.wrapper), *args], input=answer,
            text=True, capture_output=True, env=self.env, timeout=10)

    def captured(self):
        return json.loads(self.capture.read_text())

    def test_help_does_not_invoke_ansible(self):
        result = self.run_wrapper("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage:", result.stdout)
        self.assertFalse(self.capture.exists())

    def test_syntax_check_uses_context_without_confirmation(self):
        result = self.run_wrapper("--syntax-check")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.captured()
        self.assertIn("--syntax-check", args)
        self.assertIn("big_data_worker_group=workers", args)
        self.assertIn("big_data_livy_stage_maintenance_confirmed=false", args)
        self.assertEqual(args[args.index("-i") + 1], self.env["FAKE_INVENTORY"])

    def test_confirmed_staging_passes_maintenance_attestation(self):
        for answer in ("y\n", "Y\n"):
            with self.subTest(answer=answer):
                self.capture.unlink(missing_ok=True)
                result = self.run_wrapper(answer=answer)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = self.captured()
                self.assertIn("big_data_livy_stage_maintenance_confirmed=true", args)
                self.assertNotIn("--syntax-check", args)

    def test_refusal_or_eof_does_not_invoke_ansible(self):
        for answer in ("", "\n", "n\n", "N\n", "no\n", "yes\n", "stage-candidate\n", " y\n", "y \n"):
            with self.subTest(answer=answer):
                result = self.run_wrapper(answer=answer)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(self.capture.exists())

    def test_unknown_and_duplicate_options_are_refused(self):
        for args in (("--check",), ("--extra-vars", "unsafe=true"),
                     ("--syntax-check", "--syntax-check")):
            with self.subTest(args=args):
                result = self.run_wrapper(*args)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.capture.exists())

    def test_invalid_worker_group_is_refused(self):
        self.env["FAKE_GROUP"] = "workers:all"
        result = self.run_wrapper("--syntax-check")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.capture.exists())

    def test_missing_playbook_is_refused(self):
        (self.root / "playbooks/stage-big-data-spark-livy-candidate.yml").unlink()
        result = self.run_wrapper("--syntax-check")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.capture.exists())


if __name__ == "__main__":
    unittest.main()
