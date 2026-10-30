"""Offline tests: disposable local trees only, no Docker or live runtime."""
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import test_spark_teardown_directory as directory_tests
from test_spark_teardown_evidence import evidence

path = Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark/teardown_assets.py"
spec = importlib.util.spec_from_file_location("teardown_assets", path)
module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"teardown_directory": directory_tests.directory}):
    spec.loader.exec_module(module)


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, module.FLAGS)
        self.addCleanup(os.close, self.fd)
        self.outside = self.root.parent / (self.root.name + "-outside")
        self.outside.write_text("must survive")
        self.addCleanup(lambda: self.outside.unlink(missing_ok=True))
        (self.root / module.LOCK).write_text("")
        (self.root / module.LOCK).chmod(0o600)

    def plan(self, mounts=()):
        return module.Assets(self.fd, str(self.root), os.getuid(), lambda: set(mounts))

    def generated(self, name="direct-run-abcd1234"):
        run = self.root / name
        run.mkdir(mode=0o755)
        (run / "data").mkdir()
        (run / "outputs").mkdir(mode=0o700)
        (run / "outputs" / "nested").mkdir()
        (run / "outputs" / "nested" / "part.csv").write_text("generated")
        (run / "run.json").write_text("{}")
        (run / "driver.log").write_text("log")
        return run

    def test_remove_all_reviewed_assets_preserves_only_lock_and_external_source(self):
        self.generated()
        self.generated("livy-client-run-xyza1234")
        for name in module.FILES:
            (self.root / name).write_text("generated")
            (self.root / name).chmod(0o640)
        build = self.root / "livy-build"
        build.mkdir(mode=0o750)
        for name in ("Dockerfile", ".dockerignore", "livy.zip"):
            (build / name).write_text("generated")
        inode = (self.root / module.LOCK).stat().st_ino
        self.assertEqual(len(self.plan().remove()), 6)
        self.assertEqual(list(self.root.iterdir()), [self.root / module.LOCK])
        self.assertEqual((self.root / module.LOCK).stat().st_ino, inode)
        self.assertEqual(self.outside.read_text(), "must survive")
        self.assertEqual(self.plan().remove(), [])

    def test_missing_runtime_is_clean(self):
        self.assertEqual(module.Assets(None).remove(), [])

    def test_unknown_and_malformed_top_level_entries_are_refused(self):
        for name in ("unrelated.txt", "direct-run-invalid"):
            path = self.root / name
            path.write_text("unrelated")
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.plan()
            self.assertTrue(path.exists())
            path.unlink()

    def test_symlinks_and_hardlinks_do_not_touch_external_target(self):
        run = self.generated()
        bad = run / "outputs" / "outside"
        bad.symlink_to(self.outside)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            self.plan()
        bad.unlink()
        os.link(self.outside, bad)
        with self.assertRaisesRegex(ValueError, "Hard-linked"):
            self.plan()
        self.assertEqual(self.outside.read_text(), "must survive")
        self.assertTrue((run / "driver.log").exists())

    def test_symlinked_top_level_file_is_refused(self):
        (self.root / "compose.yaml").symlink_to(self.outside)
        with self.assertRaises(ValueError):
            self.plan()
        self.assertEqual(self.outside.read_text(), "must survive")

    def test_special_files_are_refused(self):
        run = self.generated()
        os.mkfifo(run / "outputs" / "pipe")
        with self.assertRaisesRegex(ValueError, "special"):
            self.plan()

    def test_writable_or_wrong_owner_asset_is_refused(self):
        run = self.generated()
        run.chmod(0o777)
        with self.assertRaisesRegex(ValueError, "protected"):
            self.plan()
        run.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "organiser-owned"):
            module.Assets(self.fd, str(self.root), os.getuid() + 1, lambda: set())

    def test_mounts_including_same_device_bind_paths_are_refused(self):
        run = self.generated()
        for point in (str(run), str(run / "outputs" / "nested")):
            with self.subTest(point=point), self.assertRaisesRegex(ValueError, "mounted"):
                self.plan([point])
        self.assertTrue((run / "driver.log").exists())

    def test_mountinfo_escaped_path_is_decoded(self):
        text = "1 2 0:3 / /path\\040with\\134slash rw - tmpfs tmpfs rw\n"
        with patch("builtins.open", return_value=io.StringIO(text)):
            self.assertEqual(module.mount_paths(), {"/path with\\slash"})

    def test_replaced_top_level_inode_is_not_removed(self):
        run = self.generated()
        plan = self.plan()
        run.rename(self.root / "original-held")
        self.generated()
        with self.assertRaises(ValueError):
            plan.remove()
        self.assertTrue((self.root / "direct-run-abcd1234" / "run.json").exists())

    def test_unsafe_late_output_prevents_all_file_removal(self):
        run = self.generated()
        plan = self.plan()
        (run / "outputs" / "outside").symlink_to(self.outside)
        with self.assertRaises(ValueError):
            plan.remove()
        self.assertTrue((run / "run.json").exists())
        self.assertEqual(self.outside.read_text(), "must survive")

    def test_normal_output_changes_until_container_shutdown_are_supported(self):
        run = self.generated()
        plan = self.plan()
        (run / "outputs" / "new.csv").write_text("final output")
        self.assertEqual(plan.remove(), [str(run)])
        self.assertFalse(run.exists())

    def test_removal_failure_propagates_and_is_retryable(self):
        self.generated()
        plan = self.plan()
        with patch.object(module.os, "unlink", side_effect=OSError("simulated failure")):
            with self.assertRaisesRegex(OSError, "simulated failure"):
                plan.remove()
        self.assertTrue(self.plan().remove())

    def test_non_root_context_does_not_open_production_paths(self):
        with patch.object(module.os, "geteuid", return_value=123), patch.object(module.os, "open") as opened:
            with self.assertRaises(PermissionError):
                with module.validated_runtime_assets():
                    pass
            opened.assert_not_called()


class ClearEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.fd = os.open(self.root, module.FLAGS)
        self.addCleanup(os.close, self.fd)

    def test_clean_reset_does_not_create_an_empty_record(self):
        with patch.object(evidence, "check_directory"):
            evidence.save_evidence(self.fd, "daemon", [])
        self.assertFalse((self.root / evidence.NAME).exists())

    def test_success_removes_empty_record_and_preserves_lock_directory(self):
        with patch.object(evidence, "check_directory"), patch.object(evidence, "load_evidence", return_value=set()):
            evidence.save_evidence(self.fd, "daemon", ["a" * 64])
            evidence.save_evidence(self.fd, "daemon", [])
            inode = self.root.stat().st_ino
            self.assertTrue(evidence.clear_evidence(self.fd, "daemon"))
            self.assertFalse((self.root / evidence.NAME).exists())
            self.assertEqual(self.root.stat().st_ino, inode)
            self.assertFalse(evidence.clear_evidence(self.fd, "daemon"))

    def test_unresolved_or_unsafe_record_is_preserved(self):
        path = self.root / evidence.NAME
        path.write_text("keep on failure")
        for value in ({"a" * 64}, ValueError("unsafe record")):
            kwargs = {"side_effect": value} if isinstance(value, Exception) else {"return_value": value}
            with patch.object(evidence, "load_evidence", **kwargs), self.assertRaises(ValueError):
                evidence.clear_evidence(self.fd, "daemon")
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
