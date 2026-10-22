"""Offline local FL cleanup wiring and real-helper safety tests."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_workshop_reset_runtime_dispatch as dispatch

HELPER = dispatch.ROOT / (
    "scripts/workshops/federated-learning/reset_fl_partitions.py"
)
BOUNDARY = "workspace_args=(delete-workspaces --yes)"
if dispatch.SOURCE.count(BOUNDARY) != 1:
    raise RuntimeError("Expected unique workspace boundary")
# Execute the actual dispatch AND local cleanup, unlike the original fixture.
EXTENDED_BLOCK = dispatch.SOURCE.split(dispatch.START, 1)[1].split(BOUNDARY, 1)[0]


def context(workshop="federated-learning", module="none"):
    data = dispatch.spark_context()
    data.update(cleanup_workshop_type=workshop, cleanup_workshop_module=module)
    return data


def run_wiring(data, local_status=0, worker_status=0):
    with patch.object(dispatch, "BLOCK", EXTENDED_BLOCK):
        return dispatch.run_dispatch(
            data, fl_cleanup_status=worker_status,
            local_cleanup_status=local_status,
        )


class LocalCleanupWiringTests(unittest.TestCase):
    def test_fl_runs_worker_then_local_then_workspace_boundary(self):
        result, calls = run_wiring(context())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].startswith("FL_DATA "))
        self.assertTrue(calls[1].startswith("FL_LOCAL --repository-root "))
        self.assertLess(
            result.stdout.index("FL worker-data cleanup verified"),
            result.stdout.index("Local FL partition cleanup verified"),
        )
        self.assertLess(
            result.stdout.index("Local FL partition cleanup verified"),
            result.stdout.index("EVENT workspace-boundary"),
        )

    def test_local_failure_preserves_exit_status_and_blocks_workspace(self):
        result, calls = run_wiring(context(), local_status=17)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1].startswith("FL_LOCAL "))
        self.assertNotIn("EVENT workspace-boundary", result.stdout)
        self.assertIn("cleanup remains in_progress", result.stderr)

    def test_worker_failure_prevents_local_cleanup_and_workspace(self):
        result, calls = run_wiring(context(), worker_status=8)
        self.assertEqual(result.returncode, 8)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("FL_DATA "))
        self.assertNotIn("EVENT workspace-boundary", result.stdout)

    def test_missing_local_helper_blocks_workspace(self):
        result, calls = run_wiring(context(), local_status=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("Missing FL partition cleanup helper", result.stderr)
        self.assertNotIn("EVENT workspace-boundary", result.stdout)

    def test_neutral_and_non_fl_skip_local_helper(self):
        cases = [
            ("none", "none"), ("big-data", "spark"),
            ("hpc", "openmp-01-basics"),
            ("introduction-to-ai", "module1"),
            ("cloud-computing-soa", "module1"),
        ]
        for workshop, module in cases:
            with self.subTest(workshop=workshop):
                result, calls = run_wiring(context(workshop, module), local_status=17)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(call.startswith("FL_LOCAL ") for call in calls))
                self.assertIn("EVENT workspace-boundary", result.stdout)

    def test_saved_fl_context_overrides_current_neutral_or_spark_selection(self):
        for selected, module in [("none", "none"), ("big-data", "spark")]:
            with self.subTest(selected=selected):
                data = context()
                data.update(workshop_type=selected, workshop_module=module)
                result, calls = run_wiring(data)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(calls), 2)
                self.assertTrue(calls[1].startswith("FL_LOCAL "))


class LocalPartitionHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "data/source/train.csv"
        self.source.parent.mkdir(parents=True)
        self.original = b"image,label\na,0\nb,1\n"
        self.source.write_bytes(self.original)
        self.partitions = self.root / "data/partitions"
        self.partitions.mkdir()
        self.group = self.partitions / "group_01"
        self.group.mkdir()
        (self.group / "train.csv").write_bytes(self.original)
        (self.partitions / "partition-manifest.json").write_text("{}")

    def run_helper(self):
        return subprocess.run(
            [sys.executable, str(HELPER), "--repository-root", str(self.root)],
            capture_output=True, text=True, timeout=10,
        )

    def assert_refused_without_deletion(self):
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cleanup refused", result.stderr)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertTrue((self.group / "train.csv").exists())
        self.assertTrue((self.partitions / "partition-manifest.json").exists())

    def test_cleanup_preserves_source_and_unrelated_assets_and_is_idempotent(self):
        legacy = self.partitions / "Group_02"
        legacy.mkdir()
        (legacy / "train.csv").write_bytes(self.original)
        unrelated = self.root / "data/keep-me.txt"
        unrelated.write_text("preserve")
        app = self.root / "workshop_assets/federated_learning/client.py"
        app.parent.mkdir(parents=True)
        app.write_text("preserve application")
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                result = self.run_helper()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(list(self.partitions.iterdir()), [])
                self.assertEqual(self.source.read_bytes(), self.original)
                self.assertEqual(unrelated.read_text(), "preserve")
                self.assertEqual(app.read_text(), "preserve application")

    def test_absent_partition_directory_succeeds(self):
        import shutil
        shutil.rmtree(self.partitions)
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.partitions.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_unexpected_artifact_refused_before_any_deletion(self):
        unexpected = self.partitions / "keep-me.txt"
        unexpected.write_text("preserve")
        self.assert_refused_without_deletion()
        self.assertEqual(unexpected.read_text(), "preserve")

    def test_symlinked_group_refused_before_any_deletion(self):
        (self.partitions / "group_02").symlink_to(
            self.source.parent, target_is_directory=True
        )
        self.assert_refused_without_deletion()

    def test_symlinked_partition_root_refused(self):
        actual = self.root / "preserved-partitions"
        self.partitions.rename(actual)
        self.partitions.symlink_to(actual, target_is_directory=True)
        self.assert_refused_without_deletion()

    def test_non_directory_group_refused_before_any_deletion(self):
        (self.partitions / "group_02").write_text("preserve")
        self.assert_refused_without_deletion()

    def test_missing_source_refused_without_partition_deletion(self):
        self.source.unlink()
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical source is missing", result.stderr)
        self.assertTrue((self.group / "train.csv").exists())
        self.assertTrue((self.partitions / "partition-manifest.json").exists())

    def test_symlinked_source_refused_without_partition_deletion(self):
        actual = self.root / "preserved-source.csv"
        self.source.rename(actual)
        self.source.symlink_to(actual)
        self.assert_refused_without_deletion()
        self.assertEqual(actual.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
