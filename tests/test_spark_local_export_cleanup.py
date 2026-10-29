"""Offline cleanup tests: every deletion is inside a fresh temporary repository."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'cleanup_local_exports',
    ROOT / 'scripts/workshops/big-data/spark/cleanup_local_exports.py')
cleanup_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup_module)


class LocalExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.root = self.repo / 'secrets/big-data-spark-direct'
        self.root.mkdir(parents=True, mode=0o700)
        self.root.parent.chmod(0o700)

    def worker(self, name):
        directory = self.root / name
        directory.mkdir(mode=0o700)
        for filename in cleanup_module.FILES:
            path = directory / filename
            path.write_text('offline synthetic fixture\n')
            path.chmod(0o644 if filename == 'host_key.pub' else 0o600)
        return directory

    def run_cleanup(self, names, execute=True):
        return cleanup_module.cleanup(self.repo, names, execute=execute)

    def test_selected_workers_only_and_idempotence(self):
        first = self.worker('tier2-worker-1')
        other = self.worker('tier1-worker-1')
        config = self.root.parent / 'spark-bind-config.env'
        config.write_text('synthetic configuration\n')
        result = self.run_cleanup(['tier2-worker-1'])
        self.assertTrue(result['cleanup_verified'])
        self.assertEqual(len(result['removed_paths']), 3)
        self.assertFalse(first.exists())
        self.assertTrue(other.exists())
        self.assertTrue(config.exists())
        self.assertEqual(self.run_cleanup(['tier2-worker-1'])['removed_paths'], [])

    def test_check_is_non_destructive(self):
        directory = self.worker('worker-1')
        result = self.run_cleanup(['worker-1'], execute=False)
        self.assertEqual(len(result['candidate_paths']), 3)
        self.assertFalse(result['cleanup_verified'])
        self.assertEqual(len(list(directory.iterdir())), 3)

    def test_missing_export_root_is_success(self):
        self.root.rmdir()
        self.assertTrue(self.run_cleanup(['worker-1'])['cleanup_verified'])
        self.assertFalse(self.root.exists())

    def test_unknown_file_preflight_blocks_all_workers(self):
        first = self.worker('worker-1')
        second = self.worker('worker-2')
        (second / 'bind-config.env').write_text('must remain\n')
        with self.assertRaises(ValueError):
            self.run_cleanup(['worker-1', 'worker-2'])
        self.assertTrue((first / 'login_key').exists())
        self.assertTrue((second / 'bind-config.env').exists())

    def test_symlinked_worker_refused(self):
        outside = self.repo / 'outside'
        outside.mkdir()
        (self.root / 'worker-1').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_cleanup(['worker-1'])
        self.assertTrue(outside.exists())

    def test_symlinked_export_root_refused(self):
        self.root.rmdir()
        outside = self.repo / 'outside'
        outside.mkdir()
        self.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            self.run_cleanup(['worker-1'])
        self.assertTrue(outside.exists())

    def test_symlink_and_hardlink_files_refused(self):
        directory = self.worker('worker-1')
        key = directory / 'login_key'
        key.unlink()
        outside = self.repo / 'outside-key'
        outside.write_text('synthetic fixture\n')
        outside.chmod(0o600)
        key.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.run_cleanup(['worker-1'])
        key.unlink()
        os.link(outside, key)
        with self.assertRaises(ValueError):
            self.run_cleanup(['worker-1'])
        self.assertTrue(outside.exists())

    def test_unsafe_private_permissions_refused(self):
        directory = self.worker('worker-1')
        (directory / 'login_key').chmod(0o644)
        with self.assertRaises(ValueError):
            self.run_cleanup(['worker-1'])
        self.assertTrue((directory / 'known_hosts').exists())

    def test_historical_public_mode_allowed_in_protected_directory(self):
        directory = self.worker('worker-1')
        public = directory / 'host_key.pub'
        public.chmod(0o664)
        result = self.run_cleanup(['worker-1'], execute=False)
        self.assertEqual(len(result['candidate_paths']), 3)
        self.assertEqual(public.stat().st_mode & 0o777, 0o664)
        self.assertTrue((directory / 'login_key').exists())
        result = self.run_cleanup(['worker-1'])
        self.assertTrue(result['cleanup_verified'])
        self.assertFalse(directory.exists())

    def test_world_writable_public_file_refused(self):
        directory = self.worker('worker-1')
        (directory / 'host_key.pub').chmod(0o666)
        with self.assertRaises(ValueError):
            self.run_cleanup(['worker-1'])
        self.assertTrue((directory / 'login_key').exists())

    def test_public_exception_requires_private_worker_directory(self):
        directory = self.worker('worker-1')
        (directory / 'host_key.pub').chmod(0o664)
        for mode in (0o750, 0o770, 0o755):
            directory.chmod(mode)
            with self.subTest(mode=oct(mode)), self.assertRaises(ValueError):
                self.run_cleanup(['worker-1'])
            self.assertTrue((directory / 'login_key').exists())
        directory.chmod(0o700)

    def test_invalid_worker_names_and_empty_selection_refused(self):
        for names in ([], ['../outside'], ['/absolute'], ['.'], ['..']):
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.run_cleanup(names)

    def test_nested_inventory_selection(self):
        inventory = {'workers': {'children': ['silo']},
                     'silo': {'hosts': ['worker-2', 'worker-1']},
                     '_meta': {'hostvars': {'worker-1': {'password': 'fixture'}}}}
        self.assertEqual(cleanup_module.inventory_workers(inventory, 'workers'),
                         ['worker-1', 'worker-2'])

    def test_missing_empty_and_cyclic_inventory_refused(self):
        for inventory in ({}, {'workers': {}},
                          {'workers': {'children': ['workers']}}):
            with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                cleanup_module.inventory_workers(inventory, 'workers')


if __name__ == '__main__':
    unittest.main(verbosity=2)
