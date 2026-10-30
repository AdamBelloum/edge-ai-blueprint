"""Offline tests for participant-direct reset assets; no real credentials."""
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile
import unittest

old_path = list(sys.path)
try:
    sys.path.insert(0, str(
        Path(__file__).resolve().parents[1]
        / "scripts/workshops/big-data/spark"
    ))
    import teardown_assets as core
finally:
    sys.path[:] = old_path

class ParticipantAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "runtime"
        self.root.mkdir(mode=0o700)
        self.lock = self.root / core.LOCK
        self.lock.write_bytes(b"")
        self.lock.chmod(0o600)
        self.lock_inode = self.lock.stat().st_ino
        for folder, files in core.CLIENT_FILES.items():
            directory = self.root / folder
            directory.mkdir(mode=0o700)
            for name, mode in files.items():
                path = directory / name
                path.write_bytes(b"offline fixture, not a credential\n")
                path.chmod(mode)
        self.external = self.parent / "external"
        self.external.write_bytes(b"preserve external evidence\n")
        self.external.chmod(0o600)

    @contextmanager
    def assets(self, mounts=()):
        fd = os.open(self.root, core.FLAGS)
        try:
            yield core.Assets(
                fd, root=str(self.root), owner_uid=os.getuid(),
                mounts=lambda: set(mounts),
            )
        finally:
            os.close(fd)

    def assert_preserved(self):
        self.assertEqual(self.lock.stat().st_ino, self.lock_inode)
        self.assertEqual(
            self.external.read_bytes(), b"preserve external evidence\n"
        )

    def test_reviewed_assets_removed_and_shared_lock_preserved(self):
        with self.assets() as assets:
            assets.remove()
        self.assertEqual(list(self.root.iterdir()), [self.lock])
        self.assert_preserved()

    def test_partial_preparation_supported(self):
        for folder in core.CLIENT_FILES:
            for path in (self.root / folder).iterdir():
                path.unlink()
        with self.assets() as assets:
            assets.remove()
        self.assertEqual(list(self.root.iterdir()), [self.lock])
        self.assert_preserved()

    def test_unknown_entries_block_all_removal(self):
        for folder in core.CLIENT_FILES:
            path = self.root / folder / "unknown"
            path.write_bytes(b"not approved")
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                with self.assets():
                    pass
            self.assertTrue(
                (self.root / "client-access/login_key").exists()
            )
            self.assert_preserved()
            path.unlink()

    def test_private_mode_and_directory_instead_of_key_refused(self):
        key = self.root / "client-access/login_key"
        key.chmod(0o640)
        with self.assertRaises(ValueError):
            with self.assets():
                pass
        key.chmod(0o600)
        key.unlink()
        key.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            with self.assets():
                pass
        self.assert_preserved()

    def test_symlink_and_hardlink_preserve_external_target(self):
        key = self.root / "client-access/login_key"
        key.unlink()
        key.symlink_to(self.external)
        with self.assertRaises(ValueError):
            with self.assets():
                pass
        self.assert_preserved()
        key.unlink()
        os.link(self.external, key)
        with self.assertRaises(ValueError):
            with self.assets():
                pass
        self.assert_preserved()

    def test_mounted_client_directories_refused(self):
        for folder in core.CLIENT_FILES:
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                with self.assets([str(self.root / folder)]):
                    pass
        self.assert_preserved()

    def test_replaced_key_identity_blocks_removal(self):
        key = self.root / "client-access/login_key"
        with self.assets() as assets:
            replacement = self.parent / "replacement"
            replacement.write_bytes(b"replacement fixture")
            replacement.chmod(0o600)
            os.replace(replacement, key)
            with self.assertRaises(ValueError):
                assets.remove()
        self.assertTrue(key.exists())
        self.assert_preserved()

if __name__ == "__main__":
    unittest.main(verbosity=2)
