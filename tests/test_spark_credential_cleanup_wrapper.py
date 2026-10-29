"""Offline credential-cleanup wrapper tests: fake context and fake Ansible."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/workshops/big-data/spark/cleanup-credentials.sh'


class CredentialCleanupWrapperTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.script = root / 'scripts/workshops/big-data/spark/cleanup-credentials.sh'
        self.script.parent.mkdir(parents=True)
        self.script.write_text(SOURCE.read_text())
        context = root / 'scripts/workshops/lib/workshop-context.sh'
        context.parent.mkdir(parents=True)
        context.write_text('load_workshop_context() { return 0; }\n')
        binaries = root / 'bin'
        binaries.mkdir()
        fake = binaries / 'ansible'
        fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CALLS"\nexit "${FAKE_STATUS:-0}"\n')
        fake.chmod(0o755)
        self.calls = root / 'calls'
        self.env = dict(os.environ,
            PATH=str(binaries) + os.pathsep + os.environ.get('PATH', ''),
            CALLS=str(self.calls), FAKE_STATUS='0',
            DIGITAFRICA_INVENTORY=str(root / 'fixture-inventory'),
            DIGITAFRICA_DEPLOYMENT_GROUP='fixture_control',
            DIGITAFRICA_NAMESPACE='fixture-namespace')

    def run_wrapper(self, *args, env=None):
        return subprocess.run(['bash', str(self.script), *args],
            env=self.env if env is None else env, text=True, capture_output=True)

    def test_help_and_invalid_arguments_do_not_call_ansible(self):
        for args, status in ((('--help',), 0), ((), 2), (('--check',), 2),
                             (('--execute', 'extra'), 2)):
            with self.subTest(args=args):
                self.assertEqual(self.run_wrapper(*args).returncode, status)
                self.assertFalse(self.calls.exists())

    def test_missing_required_context_blocks_before_ansible(self):
        for name in ('DIGITAFRICA_INVENTORY', 'DIGITAFRICA_DEPLOYMENT_GROUP',
                     'DIGITAFRICA_NAMESPACE'):
            with self.subTest(name=name):
                env = dict(self.env)
                env.pop(name)
                self.assertNotEqual(self.run_wrapper('--execute', env=env).returncode, 0)
                self.assertFalse(self.calls.exists())

    def test_invalid_namespace_blocks_before_ansible(self):
        for value in ('', 'Wrong_NS', 'a' * 64, 'namespace;echo bad'):
            with self.subTest(value=value):
                env = dict(self.env, DIGITAFRICA_NAMESPACE=value)
                self.assertNotEqual(self.run_wrapper('--execute', env=env).returncode, 0)
                self.assertFalse(self.calls.exists())

    def test_control_group_patterns_are_rejected(self):
        for value in ('', 'control:workers', 'control,*', '--all'):
            with self.subTest(value=value):
                env = dict(self.env, DIGITAFRICA_DEPLOYMENT_GROUP=value)
                self.assertNotEqual(self.run_wrapper('--execute', env=env).returncode, 0)
                self.assertFalse(self.calls.exists())

    def test_explicit_context_targets_only_labelled_credentials(self):
        result = self.run_wrapper('--execute')
        self.assertEqual(result.returncode, 0, result.stderr)
        command = self.calls.read_text()
        self.assertIn('fixture_control', command)
        self.assertIn("-n 'fixture-namespace' delete secret,configmap -l", command)
        self.assertIn('get secret,configmap -l', command)
        for label in ('digitafrica.eu/managed-by=organiser',
                      'digitafrica.eu/module=spark', 'digitafrica.eu/workshop=big-data'):
            self.assertIn(label, command)
        self.assertNotIn('secret,configmap,networkpolicy', command)
        self.assertNotIn('delete networkpolicy', command)

    def test_ansible_failure_propagates(self):
        env = dict(self.env, FAKE_STATUS='7')
        self.assertEqual(self.run_wrapper('--execute', env=env).returncode, 7)
        self.assertTrue(self.calls.exists())

    def test_shell_syntax_and_separate_policy_boundary(self):
        self.assertEqual(subprocess.run(['bash', '-n', str(self.script)]).returncode, 0)
        self.assertIn('NetworkPolicies are handled separately',
                      self.run_wrapper('--help').stdout)


if __name__ == '__main__':
    unittest.main()
