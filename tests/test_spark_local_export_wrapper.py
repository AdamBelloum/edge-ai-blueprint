"""Wrapper tests use copied code, fake context/inventory, and temporary exports."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/workshops/big-data/spark'


class LocalExportWrapperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        directory = self.repo / 'scripts/workshops/big-data/spark'
        directory.mkdir(parents=True)
        for name in ('cleanup-local-exports.sh', 'cleanup_local_exports.py'):
            shutil.copy2(SOURCE / name, directory / name)
        self.wrapper = directory / 'cleanup-local-exports.sh'
        library = self.repo / 'scripts/workshops/lib'
        library.mkdir()
        (library / 'workshop-context.sh').write_text(
            'load_workshop_context() { return 0; }\n')
        self.log = self.repo / 'inventory-called'
        binary = self.repo / 'bin'
        binary.mkdir()
        inventory = binary / 'ansible-inventory'
        inventory.write_text(
            '#!' + sys.executable + '\n'
            'import os, sys\n'
            'from pathlib import Path\n'
            'Path(os.environ["MOCK_LOG"]).write_text("called\\n")\n'
            'print(os.environ["MOCK_INVENTORY"])\n'
            'sys.exit(int(os.environ.get("MOCK_STATUS", "0")))\n')
        inventory.chmod(0o700)
        self.env = os.environ.copy()
        for key in ('BASH_ENV', 'ENV', 'SHELLOPTS', 'BASHOPTS', 'PYTHONPATH',
                    'PYTHONHOME'):
            self.env.pop(key, None)
        self.env.update(
            PATH=str(binary) + os.pathsep + os.environ['PATH'],
            DIGITAFRICA_INVENTORY=str(self.repo / 'inventory.ini'),
            DIGITAFRICA_DEPLOYMENT_WORKER_GROUP='selected_workers',
            MOCK_LOG=str(self.log), MOCK_STATUS='0',
            MOCK_INVENTORY=json.dumps({'selected_workers': {'hosts': ['worker-1']}}),
        )
        self.exports = self.repo / 'secrets/big-data-spark-direct'
        self.exports.mkdir(parents=True, mode=0o700)
        self.exports.parent.chmod(0o700)

    def worker(self, name):
        directory = self.exports / name
        directory.mkdir(mode=0o700)
        for filename in ('login_key', 'host_key.pub', 'known_hosts'):
            path = directory / filename
            path.write_text('synthetic offline fixture\n')
            path.chmod(0o664 if filename == 'host_key.pub' else 0o600)
        return directory

    def invoke(self, *args):
        return subprocess.run(['bash', str(self.wrapper), *args], env=self.env,
                              capture_output=True, text=True, timeout=15)

    def test_check_leaves_exports_untouched(self):
        selected = self.worker('worker-1')
        result = self.invoke('--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['cleanup_verified'])
        self.assertEqual(len(report['candidate_paths']), 3)
        self.assertTrue((selected / 'login_key').exists())

    def test_execute_targets_selected_worker_only(self):
        selected = self.worker('worker-1')
        other = self.worker('tier1-worker-1')
        result = self.invoke('--execute')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['cleanup_verified'])
        self.assertFalse(selected.exists())
        self.assertTrue((other / 'login_key').exists())

    def test_inventory_failure_even_with_valid_json_never_deletes(self):
        selected = self.worker('worker-1')
        self.env['MOCK_STATUS'] = '7'
        result = self.invoke('--execute')
        self.assertEqual(result.returncode, 7)
        self.assertTrue((selected / 'login_key').exists())
        self.assertIn('not touched', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_missing_group_and_malformed_json_never_delete(self):
        selected = self.worker('worker-1')
        for value in ('{}', 'not JSON'):
            self.env['MOCK_INVENTORY'] = value
            result = self.invoke('--execute')
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((selected / 'login_key').exists())

    def test_invalid_worker_group_never_calls_inventory(self):
        self.env['DIGITAFRICA_DEPLOYMENT_WORKER_GROUP'] = 'workers:all'
        result = self.invoke('--execute')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

    def test_missing_module_never_calls_inventory(self):
        (self.wrapper.parent / 'cleanup_local_exports.py').unlink()
        result = self.invoke('--execute')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

    def test_help_and_invalid_arguments_never_call_inventory(self):
        for args, code in ((('--help',), 0), (('-h',), 0), ((), 2),
                           (('--unknown',), 2), (('--check', '--execute'), 2)):
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
