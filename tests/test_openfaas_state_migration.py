"""Exercise the module-selector migration with fake k3s; no Kubernetes access."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
FAKE_K3S = r"""
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ['MIGRATION_CALLS'], 'a', encoding='utf-8') as handle:
    handle.write(json.dumps(args) + '\n')
prefix = ['kubectl', '-n', 'test-namespace']
if args[:3] != prefix:
    raise SystemExit('Unexpected command prefix')
operation = args[3:]
if operation[:3] == ['get', 'configmap', 'digitafrica-workshop-state']:
    expected = {
        'jsonpath={.data.workshop_type}': 'MIGRATION_TYPE',
        'jsonpath={.data.workshop_module}': 'MIGRATION_MODULE',
        'jsonpath={.data.introduction_to_ai_module}': 'MIGRATION_LEGACY',
    }
    if len(operation) != 5 or operation[3] != '-o' or operation[4] not in expected:
        raise SystemExit('Unexpected get arguments')
    sys.stdout.write(os.environ[expected[operation[4]]])
elif operation[:3] == ['patch', 'configmap', 'digitafrica-workshop-state']:
    if len(operation) != 7 or operation[3:6] != ['--type', 'merge', '-p']:
        raise SystemExit('Unexpected patch arguments')
    json.loads(operation[6])
    print('patched')
else:
    raise SystemExit('Unexpected operation')
"""


class WorkshopModuleMigrationTests(unittest.TestCase):
    def setUp(self):
        tasks = yaml.safe_load((ROOT / 'roles/k8s_apps/tasks/install.yml').read_text())
        matches = [task for task in tasks if task.get('name') ==
                   'Add generic workshop module selector when absent']
        self.assertEqual(len(matches), 1)
        self.shell = Environment(undefined=StrictUndefined).from_string(
            matches[0]['ansible.builtin.shell']).render(
                digitafrica_deployment={'digitafrica_namespace': 'test-namespace'})

    def run_migration(self, workshop_type, module='', legacy=''):
        with tempfile.TemporaryDirectory(prefix='module-migration-test-') as directory:
            root = Path(directory)
            executable = root / 'k3s'
            executable.write_text('#!' + sys.executable + '\n' + FAKE_K3S)
            executable.chmod(0o755)
            calls_file = root / 'calls.jsonl'
            environment = dict(os.environ)
            environment.update({
                'PATH': str(root) + os.pathsep + environment.get('PATH', ''),
                'MIGRATION_TYPE': workshop_type,
                'MIGRATION_MODULE': module,
                'MIGRATION_LEGACY': legacy,
                'MIGRATION_CALLS': str(calls_file),
                'PYTHONDONTWRITEBYTECODE': '1',
            })
            result = subprocess.run(['bash', '-c', self.shell], env=environment,
                                    cwd=root, capture_output=True, text=True, timeout=15)
            calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
            return result, calls

    def assert_read_only(self, calls):
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(call[3] == 'get' for call in calls))

    def test_existing_selectors_are_preserved_without_patch(self):
        # Selector migration preserves recognised values; pair validation is separate.
        for module in ('none', 'module1', 'module2', 'module3', 'module5',
                       'spark', 'openmp-01-basics'):
            with self.subTest(module=module):
                result, calls = self.run_migration('cloud-computing-soa', module)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'preserved')
                self.assert_read_only(calls)

    def test_absent_selector_keeps_existing_defaults(self):
        cases = [
            ('cloud-computing-soa', '', 'module1'),
            ('introduction-to-ai', '', 'module1'),
            ('introduction-to-ai', 'module2', 'module2'),
            ('introduction-to-ai', 'module3', 'module3'),
            ('big-data', '', 'spark'),
            ('hpc', '', 'openmp-01-basics'),
            ('none', '', 'none'),
            ('federated-learning', '', 'none'),
        ]
        for workshop_type, legacy, expected in cases:
            with self.subTest(workshop_type=workshop_type, legacy=legacy):
                result, calls = self.run_migration(workshop_type, legacy=legacy)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('initialised', result.stdout)
                self.assertEqual(len(calls), 4)
                self.assertTrue(all(call[3] == 'get' for call in calls[:3]))
                self.assertEqual(calls[-1][3:9], [
                    'patch', 'configmap', 'digitafrica-workshop-state',
                    '--type', 'merge', '-p'])
                self.assertEqual(json.loads(calls[-1][-1]),
                                 {'data': {'workshop_module': expected}})

    def test_unknown_selector_rejected_without_patch(self):
        result, calls = self.run_migration('cloud-computing-soa', 'module99')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('Unsupported workshop_module', result.stderr)
        self.assert_read_only(calls)

    def test_invalid_legacy_or_workshop_type_rejected_without_patch(self):
        for workshop_type, legacy in (('introduction-to-ai', 'module99'),
                                      ('unknown-workshop', '')):
            with self.subTest(workshop_type=workshop_type):
                result, calls = self.run_migration(workshop_type, legacy=legacy)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('Unsupported', result.stderr)
                self.assert_read_only(calls)


class WorkshopTypeMigrationTests(unittest.TestCase):
    # Reuse the fake-k3s harness, but execute the workshop-type task.
    run_migration = WorkshopModuleMigrationTests.run_migration

    def setUp(self):
        tasks = yaml.safe_load((ROOT / 'roles/k8s_apps/tasks/install.yml').read_text())
        matches = [task for task in tasks if task.get('name') ==
                   'Add neutral workshop type to existing workshop state when absent']
        self.assertEqual(len(matches), 1)
        self.shell = Environment(undefined=StrictUndefined).from_string(
            matches[0]['ansible.builtin.shell']).render(
                digitafrica_deployment={'digitafrica_namespace': 'test-namespace'})

    def test_supported_types_including_hpc_are_preserved_without_patch(self):
        for workshop in (
            'none', 'introduction-to-ai', 'federated-learning',
            'cloud-computing-soa', 'big-data', 'hpc',
        ):
            with self.subTest(workshop=workshop):
                result, calls = self.run_migration(workshop)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'preserved')
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][3], 'get')

    def test_absent_type_initialises_neutral_state(self):
        result, calls = self.run_migration('')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('initialised', result.stdout)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1][3], 'patch')
        self.assertEqual(
            json.loads(calls[-1][-1]), {'data': {'workshop_type': 'none'}}
        )

    def test_unknown_type_is_rejected_without_patch(self):
        result, calls = self.run_migration('unknown-workshop')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('Unsupported workshop_type', result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][3], 'get')


if __name__ == '__main__':
    unittest.main(verbosity=2)
