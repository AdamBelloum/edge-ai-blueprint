"""Offline all-worker wrapper checks; no real Ansible commands or VM access."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / 'scripts/workshops/big-data/spark'

class AllWorkersWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root / 'scripts/workshops/big-data/spark'
        self.scripts.mkdir(parents=True)
        shutil.copyfile(HELPERS / 'warm-transition.sh', self.scripts / 'warm-transition.sh')
        # Real canonical inventory resolution has its own offline test suite.
        (self.scripts / 'livy_cohort_scope.py').write_text(
            'import json, os, sys\n'
            'if os.environ.get("RESOLVER_FAIL"): sys.exit(2)\n'
            'print(json.dumps({"groups": ['
            '{"group_id":"group_01","worker":"vm-z"},'
            '{"group_id":"group_02","worker":"vm-a"}]}))\n')
        library = self.root / 'scripts/workshops/lib'
        library.mkdir()
        (library / 'workshop-context.sh').write_text(
            'load_workshop_context() {\n'
            'DIGITAFRICA_INVENTORY="$TEST_ROOT/inventory.ini"\n'
            'DIGITAFRICA_DEPLOYMENT_WORKER_GROUP=workers\n'
            'WORKSHOP_CONTEXT_REPOSITORY_ROOT="${TEST_CONTEXT_ROOT:-$TEST_ROOT}"\n}\n')
        binary = self.root / 'bin'
        binary.mkdir()
        fake = binary / 'ansible-playbook'
        fake.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
            'args = sys.argv[1:]\n'
            'vararg = args[args.index("--extra-vars") + 1]\n'
            'variables = json.load(open(vararg[1:]))\n'
            'with open(os.environ["CALL_LOG"], "a") as out:\n'
            ' out.write(json.dumps({"args":args,"vars":variables}) + "\\n")\n'
            'sys.exit(int(os.environ.get("PLAYBOOK_RC", "0")))\n')
        fake.chmod(0o700)
        self.log = self.root / 'calls'
        self.env = dict(os.environ, TEST_ROOT=str(self.root), CALL_LOG=str(self.log),
            PATH=str(binary) + os.pathsep + os.environ['PATH'])
        for key in ('TEST_CONTEXT_ROOT', 'RESOLVER_FAIL', 'PLAYBOOK_RC'):
            self.env.pop(key, None)

    def invoke(self, flags=('--all-workers',), answer='', **environment):
        return subprocess.run(['bash', str(self.scripts / 'warm-transition.sh'), *flags],
            input=answer, text=True, capture_output=True, timeout=15,
            env=dict(self.env, **environment))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_syntax_uses_complete_ordered_worker_scope_without_confirmation(self):
        result = self.invoke(('--all-workers', '--syntax-check'))
        self.assertEqual(result.returncode, 0, result.stderr)
        call, = self.calls()
        self.assertEqual(call['args'][call['args'].index('--limit') + 1], 'workers')
        self.assertEqual(call['vars']['big_data_livy_cohort_workers'], ['vm-z', 'vm-a'])
        self.assertNotIn('big_data_livy_pilot_host', call['vars'])
        self.assertFalse(call['vars']['big_data_livy_transition_submissions_paused'])
        self.assertIn('--syntax-check', call['args'])
        self.assertNotIn('NOTE ===', result.stdout)
        self.assertFalse(Path(call['args'][call['args'].index('--extra-vars') + 1][1:]).exists())

    def test_one_cohort_confirmation_dispatches_once(self):
        result = self.invoke(answer='y\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        call, = self.calls()
        self.assertEqual(result.stdout.count('NOTE ==='), 1)
        self.assertIn('group_01 -> vm-z', result.stdout)
        self.assertIn('group_02 -> vm-a', result.stdout)
        self.assertNotIn('--syntax-check', call['args'])
        for key in ('big_data_livy_stage_maintenance_confirmed',
                    'big_data_livy_build_candidate',
                    'big_data_livy_transition_maintenance_confirmed',
                    'big_data_livy_transition_submissions_paused'):
            self.assertIs(call['vars'][key], True)

    def test_cancel_eof_and_invalid_answers_never_dispatch(self):
        for answer in ('', '\n', 'n\n', 'yes\n', ' y\n', 'y \n'):
            self.assertEqual(self.invoke(answer=answer).returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_mixed_duplicate_and_unknown_flags_never_dispatch(self):
        for flags in (('--all-workers', '--limit', 'vm-z'),
                      ('--all-workers', '--all-workers'),
                      ('--all-workers', '--syntax-check', '--syntax-check'),
                      ('--all-workers', '--yes')):
            self.assertEqual(self.invoke(flags, answer='y\n').returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_resolver_failure_and_wrong_checkout_never_dispatch(self):
        self.assertNotEqual(self.invoke(answer='y\n', RESOLVER_FAIL='1').returncode, 0)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        self.assertNotEqual(self.invoke(answer='y\n', TEST_CONTEXT_ROOT=str(elsewhere)).returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_failure_propagates_without_retry(self):
        result = self.invoke(answer='y\n', PLAYBOOK_RC='7')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(len(self.calls()), 1)

    def test_playbook_requires_inventory_complete_scope_and_serial_failstop(self):
        plays = yaml.safe_load((ROOT / 'playbooks/transition-big-data-spark-livy.yml').read_text())
        predicates = plays[0]['tasks'][0]['ansible.builtin.assert']['that']
        self.assertTrue(any('ansible_play_hosts_all ==' in p and 'big_data_livy_cohort_workers' in p for p in predicates))
        self.assertTrue(any('big_data_livy_cohort_workers == groups[big_data_worker_group]' in p for p in predicates))
        for play in (plays[0], plays[-1]):
            self.assertTrue(play['any_errors_fatal'])
            self.assertEqual(play['serial'], 1)

if __name__ == '__main__':
    unittest.main()
