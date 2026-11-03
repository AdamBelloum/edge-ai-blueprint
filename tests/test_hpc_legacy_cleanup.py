"""Offline tests for reviewed legacy HPC cleanup; no remote operations."""
import copy
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from test_hpc_cleanup_orchestration import ROOT, builder, inventory


class LegacyManifestTests(unittest.TestCase):
    def test_exact_reviewed_cleanup_only_entries_and_worker_scope(self):
        expected = [
            {"path": "openmp-01-basics/01-beginner/hello.c",
             "sha256": "b8f984c4119afc76f8cc30dd9e25df4f32446e31454f9485c4d7930276c4cb5c",
             "mode": 0o644},
            {"path": "openmp-01-basics/02-intermediate/pi_serial.c",
             "sha256": "d59fd3cdbaba2e5a65f85894930c64fe0a1bae8b478b70f2d7949a0cc6ecf654",
             "mode": 0o644},
        ]
        self.assertEqual(list(builder.LEGACY_WORKSPACE_FILES), expected)
        installed = builder.read_yaml(ROOT / "roles/hpc_workspace/defaults/main.yml")["hpc_workspace_files"]
        self.assertTrue(all(e["path"] not in installed for e in expected))
        plan = builder.build(ROOT, inventory(), "workers", "central")
        workspace, runtime = plan["hpc_cleanup_jobs"]
        self.assertEqual(workspace["hosts"], ["worker-1", "worker-2"])
        self.assertEqual(workspace["manifest"]["files"][-2:], expected)
        self.assertTrue(all(e["path"] not in {i["path"] for i in runtime["manifest"]["files"]}
                            for e in expected))

    def fixture(self, root):
        for relative in ("roles/hpc_workspace", "roles/hpc_runtime", "workshop_assets/hpc"):
            shutil.copytree(ROOT / relative, root / relative)

    def test_modified_or_symlinked_local_legacy_source_is_refused(self):
        for conflict in ("modified", "symlink"):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                source = root / "workshop_assets/hpc" / builder.LEGACY_WORKSPACE_FILES[0]["path"]
                if conflict == "modified":
                    source.write_bytes(source.read_bytes() + b"\nmodified\n")
                else:
                    target = source.with_name("unrelated-source.c")
                    source.rename(target)
                    source.symlink_to(target.name)
                with self.assertRaises(ValueError):
                    builder.build(root, inventory(), "workers", "central")

    def test_duplicate_current_and_legacy_paths_are_refused(self):
        entry = copy.deepcopy(builder.LEGACY_WORKSPACE_FILES[0])
        entry["path"] = "README.md"
        entry["sha256"] = builder.digest(ROOT / "workshop_assets/hpc/README.md")
        with patch.object(builder, "LEGACY_WORKSPACE_FILES", (entry,)):
            with self.assertRaises(builder.engine.CleanupError):
                builder.build(ROOT, inventory(), "workers", "central")


class LegacyDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "hpc"
        self.root.mkdir(mode=0o755)
        self.root.chmod(0o755)
        self.entries = builder.reviewed_legacy_entries(ROOT)
        self.paths = []
        for entry in self.entries:
            destination = self.root / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            for parent in destination.parents:
                if parent == self.root.parent:
                    break
                parent.chmod(0o755)
            destination.write_bytes((ROOT / "workshop_assets/hpc" / entry["path"]).read_bytes())
            destination.chmod(entry["mode"])
            self.paths.append(destination)
        self.uid, self.gid = os.getuid(), os.getgid()

    def test_check_execute_repeat_and_unrelated_preservation(self):
        unrelated = self.paths[0].parent / "participant-notes.txt"
        unrelated.write_text("keep this unrelated file")
        before = [p.read_bytes() for p in self.paths]
        present = builder.engine.preflight(self.root, self.entries, self.uid, self.gid)
        self.assertEqual(len(present), 2)
        self.assertEqual([p.read_bytes() for p in self.paths], before)
        self.assertEqual(builder.engine.execute(self.root, self.entries, self.uid, self.gid), 2)
        self.assertTrue(all(not p.exists() for p in self.paths))
        self.assertTrue(all(p.parent.is_dir() for p in self.paths))
        self.assertEqual(unrelated.read_text(), "keep this unrelated file")
        self.assertEqual(builder.engine.execute(self.root, self.entries, self.uid, self.gid), 0)

    def assert_refused_without_deleting_first(self):
        with self.assertRaises(builder.engine.CleanupError):
            builder.engine.execute(self.root, self.entries, self.uid, self.gid)
        self.assertTrue(self.paths[0].is_file())

    def test_modified_remote_legacy_file_blocks_deletion(self):
        self.paths[1].write_bytes(self.paths[1].read_bytes() + b"\nmodified\n")
        self.assert_refused_without_deleting_first()

    def test_symlink_blocks_deletion(self):
        target = self.paths[1].with_name("unrelated.c")
        self.paths[1].rename(target)
        self.paths[1].symlink_to(target.name)
        self.assert_refused_without_deleting_first()
        self.assertTrue(target.is_file())

    def test_hard_link_blocks_deletion(self):
        os.link(self.paths[1], self.paths[1].with_name("unrelated-hard-link.c"))
        self.assert_refused_without_deleting_first()

    def test_file_mode_conflict_blocks_deletion(self):
        self.paths[1].chmod(0o600)
        self.assert_refused_without_deleting_first()

    def test_directory_mode_conflict_blocks_deletion(self):
        self.paths[1].parent.chmod(0o700)
        self.assert_refused_without_deleting_first()

    def test_owner_expectation_conflict_blocks_deletion(self):
        with self.assertRaises(builder.engine.CleanupError):
            builder.engine.execute(self.root, self.entries, self.uid + 1, self.gid)
        self.assertTrue(all(p.is_file() for p in self.paths))


if __name__ == "__main__":
    unittest.main(verbosity=2)
