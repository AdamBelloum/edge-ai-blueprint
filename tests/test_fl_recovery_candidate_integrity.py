"""Negative tests for candidate integrity before FL recovery staging."""
import contextlib
import csv
import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts/workshops/federated-learning"
GENERATOR = SCRIPTS / "prepare_fl_partitions.py"

spec = importlib.util.spec_from_file_location(
    "fl_recovery_verifier", SCRIPTS / "verify_fl_partition_recovery.py"
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class CandidateIntegrityTests(unittest.TestCase):
    def test_corrupt_and_missing_candidates_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "data"
            source = data_root / "source/train.csv"
            source.parent.mkdir(parents=True)
            with source.open("w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("image", "label"))
                for label in ("class_a", "class_b"):
                    for index in range(12):
                        writer.writerow((f"{label}_{index}.png", label))

            result = subprocess.run(
                [
                    sys.executable, str(GENERATOR),
                    "--data-root", str(data_root),
                    "--groups", "2", "--seed", "42",
                ],
                text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            manifest = data_root / "partitions/partition-manifest.json"
            expected = hashlib.sha256(manifest.read_bytes()).hexdigest()
            original = {
                str(path.relative_to(data_root)): path.read_bytes()
                for path in data_root.rglob("*") if path.is_file()
            }
            real_run = subprocess.run

            for fault, message in (
                ("corrupt", "candidate partition checksum mismatch"),
                ("missing", "Missing candidate partition"),
            ):
                with self.subTest(fault=fault):
                    def generate_then_damage(command, **kwargs):
                        kwargs.setdefault("timeout", 30)
                        result = real_run(command, **kwargs)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        output = Path(
                            command[command.index("--partition-root") + 1]
                        )
                        partition = output / "group_01/train.csv"
                        if fault == "corrupt":
                            with partition.open("ab") as handle:
                                handle.write(b"tampered.png,class_a\n")
                        else:
                            partition.unlink()
                        # Leave the checksum-pinned candidate manifest intact.
                        return result

                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    arguments = [
                        str(SCRIPTS / "verify_fl_partition_recovery.py"),
                        "--data-root", str(data_root),
                        "--groups", "2", "--seed", "42",
                        "--expected-manifest-sha256", expected,
                    ]
                    with (
                        mock.patch.object(sys, "argv", arguments),
                        mock.patch.object(
                            verifier.subprocess, "run",
                            side_effect=generate_then_damage,
                        ),
                        contextlib.redirect_stdout(stdout),
                        contextlib.redirect_stderr(stderr),
                    ):
                        status = verifier.main()

                    self.assertEqual(status, 3)
                    self.assertIn(message, stderr.getvalue())
                    self.assertEqual(stdout.getvalue(), "")
                    current = {
                        str(path.relative_to(data_root)): path.read_bytes()
                        for path in data_root.rglob("*") if path.is_file()
                    }
                    self.assertEqual(current, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
