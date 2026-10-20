"""Offline evidence tests; root ownership is simulated."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "teardown_evidence",
    ROOT / "scripts/workshops/big-data/spark/teardown_evidence.py",
)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)

DAEMON = "test-daemon"
NETWORK = "a" * 64


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.directory.chmod(0o700)
        self.fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.path = self.directory / evidence.NAME

        real_fstat = os.fstat

        def simulated_root(fd):
            values = list(real_fstat(fd))
            values[4] = 0
            return os.stat_result(values)

        owner_patch = patch.object(
            evidence.os, "fstat", side_effect=simulated_root
        )
        owner_patch.start()
        self.addCleanup(owner_patch.stop)

    def save(self):
        evidence.save_evidence(self.fd, DAEMON, [NETWORK])

    def test_absent_file_returns_empty_set(self):
        self.assertEqual(evidence.load_evidence(self.fd, DAEMON), set())

    def test_round_trip_and_replacement(self):
        self.save()
        self.assertEqual(evidence.load_evidence(self.fd, DAEMON), {NETWORK})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        evidence.save_evidence(self.fd, DAEMON, [])
        self.assertEqual(evidence.load_evidence(self.fd, DAEMON), set())
        self.assertEqual(list(self.directory.iterdir()), [self.path])

    def test_daemon_mismatch_is_refused(self):
        self.save()
        with self.assertRaisesRegex(ValueError, "different Docker daemon"):
            evidence.load_evidence(self.fd, "other-daemon")

    def test_unsafe_file_permissions_are_refused(self):
        self.save()
        self.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "Unsafe evidence"):
            evidence.load_evidence(self.fd, DAEMON)

    def test_unsafe_directory_permissions_are_refused(self):
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "directory"):
            evidence.load_evidence(self.fd, DAEMON)
        with self.assertRaisesRegex(ValueError, "directory"):
            self.save()

    def test_symlink_is_refused(self):
        destination = self.directory / "destination"
        destination.write_text("{}")
        self.path.symlink_to(destination)
        with self.assertRaises(OSError):
            evidence.load_evidence(self.fd, DAEMON)

    def test_hard_link_is_refused(self):
        self.save()
        os.link(self.path, self.directory / "second-link")
        with self.assertRaisesRegex(ValueError, "Unsafe evidence"):
            evidence.load_evidence(self.fd, DAEMON)

    def test_malformed_json_is_refused(self):
        self.save()
        self.path.write_text("{invalid")
        with self.assertRaises(json.JSONDecodeError):
            evidence.load_evidence(self.fd, DAEMON)

    def test_invalid_network_id_preserves_existing_record(self):
        self.save()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Invalid legacy"):
            evidence.save_evidence(self.fd, DAEMON, ["not-a-docker-id"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_daemon_id_is_refused(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            evidence.load_evidence(self.fd, "")
        with self.assertRaisesRegex(ValueError, "identity"):
            evidence.save_evidence(self.fd, "", [NETWORK])


if __name__ == "__main__":
    unittest.main(verbosity=2)
