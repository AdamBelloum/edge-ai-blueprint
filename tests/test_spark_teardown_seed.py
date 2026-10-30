"""Offline seed/data cleanup tests; no Docker or production paths."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import test_spark_teardown_assets as assets_tests
import test_spark_teardown_directory as directory_tests

path = Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark/teardown_seed.py"
spec = importlib.util.spec_from_file_location("teardown_seed", path)
module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"teardown_assets": assets_tests.module,
                             "teardown_directory": directory_tests.directory}):
    spec.loader.exec_module(module)


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "spark"
        self.root.mkdir(mode=0o755)
        self.fd = os.open(self.root, module.FLAGS)
        self.parent_fd = os.open(self.parent, module.FLAGS)
        self.addCleanup(os.close, self.fd)
        self.addCleanup(os.close, self.parent_fd)
        self.other = self.parent / "other-workshop"
        self.other.mkdir()
        (self.other / "source.csv").write_text("preserve")
        (self.other / "source.csv").chmod(0o644)
        for name in module.DIRECTORIES:
            (self.root / name).mkdir(mode=0o755)
        for name in module.FILES:
            (self.root / name).write_text("staged")
            (self.root / name).chmod(0o644)

    def plan(self, mounts=()):
        return module.SeedAssets(self.fd, str(self.root), os.getuid(), lambda: set(mounts), self.parent_fd)

    def test_delete_bundle_and_seed_root_preserve_other_workshop(self):
        self.assertIn(str(self.root), self.plan().remove())
        self.assertFalse(self.root.exists())
        self.assertEqual((self.other / "source.csv").read_text(), "preserve")

    def test_missing_seed_is_clean(self):
        self.assertEqual(module.SeedAssets(None).remove(), [])

    def test_partial_or_empty_staging_is_supported(self):
        for name in module.FILES:
            (self.root / name).unlink()
        self.assertIn(str(self.root), self.plan().remove())
        self.assertFalse(self.root.exists())

    def test_unknown_entries_prevent_all_deletion(self):
        for name in ("unrelated.txt", "data/foreign.csv", "docs/foreign.pdf"):
            bad = self.root / name
            bad.write_text("unknown")
            bad.chmod(0o644)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.plan()
            self.assertTrue((self.root / "README.md").exists())
            bad.unlink()

    def test_symlink_and_hardlink_do_not_touch_external_source(self):
        target = self.other / "source.csv"
        path = self.root / "data/Bank_Personal_Loan_Modelling.csv"
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.plan()
        path.unlink()
        os.link(target, path)
        with self.assertRaises(ValueError):
            self.plan()
        self.assertEqual(target.read_text(), "preserve")

    def test_group_writable_seed_file_is_refused(self):
        (self.root / "README.md").chmod(0o666)
        with self.assertRaisesRegex(ValueError, "protected"):
            self.plan()

    def test_mounts_including_root_and_same_device_bind_paths_are_refused(self):
        for point in (str(self.root), str(self.root / "data")):
            with self.subTest(point=point), self.assertRaises(ValueError):
                self.plan([point])

    def test_directory_instead_of_file_is_refused(self):
        path = self.root / "README.md"
        path.unlink()
        path.mkdir(mode=0o755)
        with self.assertRaises(ValueError):
            self.plan()

    def test_late_unknown_entry_blocks_deletion(self):
        plan = self.plan()
        bad = self.root / "data/unexpected.csv"
        bad.write_text("unknown")
        bad.chmod(0o644)
        with self.assertRaises(ValueError):
            plan.remove()
        self.assertTrue((self.root / "README.md").exists())

    def test_deletion_failure_propagates_and_retry_succeeds(self):
        plan = self.plan()
        with patch.object(module.os, "unlink", side_effect=OSError("seed failure")):
            with self.assertRaisesRegex(OSError, "seed failure"):
                plan.remove()
        self.assertIn(str(self.root), self.plan().remove())

    def test_non_root_context_does_not_open_production_paths(self):
        with patch.object(module.os, "geteuid", return_value=123), patch.object(module.os, "open") as opened:
            with self.assertRaises(PermissionError):
                with module.validated_seed_assets():
                    pass
            opened.assert_not_called()


    def test_observed_extra_seed_paths_are_removed_with_current_bundle(self):
        self.assertEqual(module.LEGACY_FILES, {"01-spark-beginner.ipynb", "data-analytics.py"})
        # setUp stages all allowed files, including the two observed extras.
        removed = self.plan().remove()
        for name in module.LEGACY_FILES:
            self.assertIn(str(self.root / name), removed)
        self.assertFalse(self.root.exists())
        self.assertEqual((self.other / "source.csv").read_text(), "preserve")

    def test_cleanup_current_files_match_authoritative_publication_manifest(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "roles/big_data_workspace/tasks/main.yml").read_text()
        # Parse the reviewed literal copy-loop list without a YAML dependency.
        # Structural or manifest changes must cause a test failure/review.
        section = text.split("    - name: Copy the Spark participant asset bundle\n", 1)[1]
        lines = section.split("      loop:\n", 1)[1].splitlines()
        published = set()
        for line in lines:
            if not line.startswith("        - "):
                break
            published.add(line[len("        - "):].strip())
        self.assertEqual(len(published), 10)
        self.assertEqual(module.FILES - module.LEGACY_FILES, published)
        self.assertTrue(module.LEGACY_FILES.isdisjoint(published))
        self.assertTrue({"spark_remote.py", "STEP1-REMOTE.md"}.issubset(published))

        template = (root / "roles/k8s_apps/templates/jhub-values.yaml.j2").read_text()
        spark_section = template.split("big_data_source=/seed/big-data/spark\n", 1)[1]
        delivered = spark_section.split("for filename in ", 1)[1]
        delivered = delivered.split("; do", 1)[0].split()
        self.assertEqual(set(delivered), published)
        self.assertIn(
            'copy_seed_file "$big_data_source/$filename" "$big_data_workspace/$filename" false',
            spark_section,
        )
        for filename in published:
            source = root / "workshop_assets/big-data/spark/beginner" / filename
            self.assertTrue(source.is_file(), str(source))

    def test_extra_seed_symlink_cannot_touch_an_external_file(self):
        target = self.other / "source.csv"
        name = self.root / "data-analytics.py"
        name.unlink()
        name.symlink_to(target)
        with self.assertRaises(ValueError):
            self.plan()
        self.assertEqual(target.read_text(), "preserve")
        self.assertTrue((self.root / "README.md").exists())

    def test_other_extra_looking_paths_still_block_all_deletion(self):
        path = self.root / "01-spark-beginner-backup.ipynb"
        path.write_text("not authorised")
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "Unknown staged Spark seed entry"):
            self.plan()
        self.assertTrue((self.root / "data-analytics.py").exists())
        self.assertTrue((self.root / "README.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
