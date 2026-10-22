"""Offline FL partition recovery tests using temporary synthetic data."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / (
    "scripts/workshops/federated-learning/prepare_fl_partitions.py"
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PartitionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "data"
        self.source = self.root / "source/train.csv"
        self.source.parent.mkdir(parents=True)
        with self.source.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("image", "label"))
            for label in ("class_a", "class_b"):
                for index in range(12):
                    writer.writerow((f"{label}_{index}.png", label))
        self.original_source = self.source.read_bytes()

    def generate(self, groups=2):
        result = subprocess.run(
            [
                sys.executable, str(GENERATOR),
                "--groups", str(groups),
                "--seed", "42",
                "--data-root", str(self.root),
            ],
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.root / "partitions/partition-manifest.json"

    def snapshot(self):
        partition_root = self.root / "partitions"
        return {
            str(path.relative_to(partition_root)): digest(path)
            for path in partition_root.rglob("*") if path.is_file()
        }

    def test_deleted_partitions_reproduce_pinned_manifest(self):
        manifest = self.generate()
        pinned_digest = digest(manifest)
        original = self.snapshot()

        # Delete only this test's generated temporary directory.
        shutil.rmtree(self.root / "partitions")
        recovered_manifest = self.generate()

        self.assertEqual(digest(recovered_manifest), pinned_digest)
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(self.source.read_bytes(), self.original_source)

    def test_same_configuration_is_repeatable(self):
        self.generate()
        original = self.snapshot()
        self.generate()
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(self.source.read_bytes(), self.original_source)

    def test_changed_worker_count_requires_new_manifest_reference(self):
        old_digest = digest(self.generate(groups=2))
        manifest_path = self.generate(groups=3)
        self.assertNotEqual(digest(manifest_path), old_digest)

        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["groups"], 3)
        self.assertEqual(
            set(manifest["partitions"]),
            {"group_01", "group_02", "group_03"},
        )
        self.assertEqual(self.source.read_bytes(), self.original_source)


    def test_temporary_output_preserves_pinned_manifest_and_existing_data(self):
        original_manifest = self.generate()
        pinned_digest = digest(original_manifest)
        original_partitions = self.snapshot()
        temporary_output = Path(self.temporary.name) / "candidate-partitions"

        result = subprocess.run(
            [
                sys.executable, str(GENERATOR),
                "--groups", "2",
                "--seed", "42",
                "--data-root", str(self.root),
                "--partition-root", str(temporary_output),
            ],
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        candidate_manifest = temporary_output / "partition-manifest.json"
        self.assertEqual(digest(candidate_manifest), pinned_digest)
        candidate_files = {
            str(path.relative_to(temporary_output)): digest(path)
            for path in temporary_output.rglob("*") if path.is_file()
        }
        self.assertEqual(candidate_files, original_partitions)
        self.assertEqual(self.snapshot(), original_partitions)
        self.assertEqual(self.source.read_bytes(), self.original_source)

    def test_output_containing_source_is_rejected_without_changes(self):
        self.generate()
        original_partitions = self.snapshot()
        for output in (self.root, self.source.parent):
            with self.subTest(output=output):
                result = subprocess.run(
                    [
                        sys.executable, str(GENERATOR),
                        "--groups", "2",
                        "--data-root", str(self.root),
                        "--partition-root", str(output),
                    ],
                    text=True, capture_output=True, timeout=30,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "must not contain the canonical source", result.stderr
                )
                self.assertEqual(self.snapshot(), original_partitions)
                self.assertEqual(self.source.read_bytes(), self.original_source)


    def test_unsafe_explicit_output_is_rejected_without_changes(self):
        self.generate()
        original_partitions = self.snapshot()

        populated = Path(self.temporary.name) / "populated-output"
        retained = populated / "group_01" / "train.csv"
        retained.parent.mkdir(parents=True)
        retained.write_bytes(b"existing data must survive\\n")

        target = Path(self.temporary.name) / "symlink-target"
        target.mkdir()
        linked = Path(self.temporary.name) / "linked-output"
        linked.symlink_to(target, target_is_directory=True)

        for output, message in (
            (populated, "new or empty directory"),
            (linked, "must not be a symlink"),
        ):
            with self.subTest(output=output):
                result = subprocess.run(
                    [
                        sys.executable, str(GENERATOR),
                        "--groups", "2",
                        "--seed", "42",
                        "--data-root", str(self.root),
                        "--partition-root", str(output),
                    ],
                    text=True, capture_output=True, timeout=30,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.snapshot(), original_partitions)
                self.assertEqual(self.source.read_bytes(), self.original_source)
                self.assertEqual(
                    retained.read_bytes(), b"existing data must survive\\n"
                )
                self.assertTrue(linked.is_symlink())
                self.assertEqual(list(target.iterdir()), [])

    def test_checksum_gated_recovery_verifier(self):
        pinned_digest = digest(self.generate())
        original = self.snapshot()
        verifier = GENERATOR.with_name("verify_fl_partition_recovery.py")

        cases = (
            ("matching", pinned_digest, "42", 0),
            ("wrong checksum", "0" * 64, "42", 3),
            ("changed seed", pinned_digest, "43", 3),
        )
        for name, expected, seed, status in cases:
            with self.subTest(case=name):
                result = subprocess.run(
                    [
                        sys.executable, str(verifier),
                        "--data-root", str(self.root),
                        "--groups", "2",
                        "--seed", seed,
                        "--expected-manifest-sha256", expected,
                    ],
                    text=True, capture_output=True, timeout=30,
                )
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(self.snapshot(), original)
                self.assertEqual(self.source.read_bytes(), self.original_source)
                if status == 0:
                    evidence = json.loads(result.stdout)
                    self.assertTrue(evidence["recovery_verified"])
                    self.assertFalse(evidence["published"])
                    self.assertFalse(evidence["workers_staged"])
                else:
                    self.assertIn("differs from the recorded checksum", result.stderr)


    def test_retained_evidence_recovers_without_partition_directory(self):
        manifest = self.generate()
        raw = manifest.read_bytes()
        expected = digest(manifest)
        evidence = Path(self.temporary.name) / "retained-manifest.json"
        evidence.write_bytes(raw)
        shutil.rmtree(self.root / "partitions")

        verifier = GENERATOR.with_name("verify_fl_partition_recovery.py")
        command = [
            sys.executable, str(verifier),
            "--recovery-manifest", str(evidence),
            "--expected-manifest-sha256", expected,
        ]
        result = subprocess.run(
            command, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["recovery_verified"])
        self.assertFalse((self.root / "partitions").exists())
        self.assertEqual(self.source.read_bytes(), self.original_source)
        self.assertEqual(evidence.read_bytes(), raw)

        # A changed source must be rejected before candidate generation.
        self.source.write_bytes(self.original_source + b"changed.png,class_a\n")
        result = subprocess.run(
            command, text=True, capture_output=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical source checksum differs", result.stderr)
        self.assertFalse((self.root / "partitions").exists())

        # Altered retained evidence must also be rejected.
        self.source.write_bytes(self.original_source)
        evidence.write_bytes(raw + b"\n")
        result = subprocess.run(
            command, text=True, capture_output=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recovery manifest checksum mismatch", result.stderr)
        self.assertFalse((self.root / "partitions").exists())

    def test_recovery_preserves_partition_integrity(self):
        manifest = json.loads(self.generate().read_text())
        seen = set()
        for group, entry in manifest["partitions"].items():
            path = self.root / "partitions" / group / "train.csv"
            self.assertEqual(digest(path), entry["sha256"])
            with path.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            images = {row["image"] for row in rows}
            self.assertTrue(seen.isdisjoint(images))
            seen.update(images)
            self.assertEqual(len(rows), entry["rows"])
            self.assertEqual(
                {row["label"] for row in rows}, {"class_a", "class_b"}
            )
        self.assertEqual(len(seen), manifest["source_rows"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
