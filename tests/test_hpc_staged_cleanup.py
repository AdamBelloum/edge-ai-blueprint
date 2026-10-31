"""Offline filesystem tests; only temporary directories are modified."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hpc_staged_cleanup", ROOT / "scripts/workshops/hpc/cleanup-staged-files.py")
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class HPCStagedCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "staging"
        self.root.mkdir(mode=0o755)
        self.root.chmod(0o755)
        self.uid, self.gid = os.getuid(), os.getgid()
        self.entries = [self.seed("README.md"), self.seed("OpenMP/helpers/openmp_start", mode=0o755)]

    def seed(self, name, mode=0o644):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        for parent in target.parents:
            if parent == self.base:
                break
            parent.chmod(0o755)
        content = ("installed payload: " + name).encode()
        target.write_bytes(content)
        target.chmod(mode)
        return {"path": name, "sha256": hashlib.sha256(content).hexdigest(), "mode": mode}

    def check(self):
        return cleanup.preflight(self.root, self.entries, self.uid, self.gid)

    def run_cleanup(self):
        return cleanup.execute(self.root, self.entries, self.uid, self.gid)

    def test_check_never_deletes(self):
        self.assertEqual(len(self.check()), 2)
        self.assertTrue((self.root / "README.md").exists())

    def test_execute_preserves_unrelated_files_and_directories_and_is_repeat_safe(self):
        unrelated = self.root / "personal-notes.txt"
        unrelated.write_text("preserve")
        self.assertEqual(self.run_cleanup(), 2)
        self.assertEqual(unrelated.read_text(), "preserve")
        self.assertTrue((self.root / "OpenMP/helpers").is_dir())
        self.assertEqual(self.run_cleanup(), 0)

    def test_modified_later_target_blocks_all_deletion(self):
        (self.root / self.entries[1]["path"]).write_text("modified")
        with self.assertRaises(cleanup.CleanupError):
            self.run_cleanup()
        self.assertTrue((self.root / "README.md").exists())

    def test_file_symlink_preserves_external_target_and_other_installed_files(self):
        outside = self.base / "outside"
        outside.write_text("preserve")
        target = self.root / self.entries[1]["path"]
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaises(cleanup.CleanupError):
            self.run_cleanup()
        self.assertEqual(outside.read_text(), "preserve")
        self.assertTrue((self.root / "README.md").exists())

    def test_symlinked_root_is_rejected(self):
        moved = self.base / "moved"
        self.root.rename(moved)
        self.root.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(cleanup.CleanupError):
            self.run_cleanup()
        self.assertTrue((moved / "README.md").exists())

    def test_symlinked_subdirectory_is_rejected_before_deletion(self):
        helpers = self.root / "OpenMP/helpers"
        moved = self.base / "moved-helpers"
        helpers.rename(moved)
        helpers.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(cleanup.CleanupError):
            self.run_cleanup()
        self.assertTrue((self.root / "README.md").exists())

    def test_hardlink_is_rejected(self):
        os.link(self.root / self.entries[1]["path"], self.base / "alias")
        with self.assertRaises(cleanup.CleanupError):
            self.run_cleanup()
        self.assertTrue((self.root / "README.md").exists())

    def test_wrong_file_mode_blocks_all_deletion(self):
        (self.root / self.entries[1]["path"]).chmod(0o600)
        with self.assertRaises(cleanup.CleanupError):
            self.run_cleanup()
        self.assertTrue((self.root / "README.md").exists())

    def test_wrong_directory_mode_is_rejected(self):
        (self.root / "OpenMP").chmod(0o777)
        with self.assertRaises(cleanup.CleanupError):
            self.run_cleanup()
        self.assertTrue((self.root / "README.md").exists())

    def test_wrong_expected_ownership_is_rejected(self):
        with self.assertRaises(cleanup.CleanupError):
            cleanup.execute(self.root, self.entries, self.uid + 1, self.gid)
        self.assertTrue((self.root / "README.md").exists())

    def test_absent_root_is_repeat_safe(self):
        self.assertEqual(cleanup.execute(self.base / "absent", self.entries, self.uid, self.gid), 0)

    def test_unsafe_or_duplicate_manifest_blocks_before_deletion(self):
        for name in ("../outside", "/outside", ".", "OpenMP/../README.md", "OpenMP//x"):
            with self.subTest(name=name):
                bad = dict(self.entries[0], path=name)
                with self.assertRaises(cleanup.CleanupError):
                    cleanup.execute(self.root, [self.entries[0], bad], self.uid, self.gid)
                self.assertTrue((self.root / "README.md").exists())
        with self.assertRaises(cleanup.CleanupError):
            cleanup.execute(self.root, [self.entries[0], self.entries[0]], self.uid, self.gid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
