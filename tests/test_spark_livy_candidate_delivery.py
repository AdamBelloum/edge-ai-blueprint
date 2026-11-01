"""Disposable delivery-bundle tests; no archive verification or VM access."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

old_path = list(sys.path)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                         "scripts/workshops/big-data/spark"))
    import livy_candidate_delivery as delivery
finally:
    sys.path[:] = old_path


class CandidateDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.files = {name: ("rendered " + name).encode()
                      for name in delivery.FILES}
        for name, content in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(0o600)
        for name in ("livy-transition", "livy-transition/livy-build"):
            (self.root / name).chmod(0o700)
        self.reviewed = {name: content.decode()
                         for name, content in self.files.items()
                         if name != delivery.ARCHIVE}
        self.manifest = self.root / delivery.MANIFEST
        self.save_manifest()

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.reviewed), encoding="utf-8")
        self.manifest.chmod(0o600)

    def read(self):
        return delivery.read_delivery(self.fd, owner_uid=os.getuid())

    def test_consistent_bundle_is_read_without_mutation(self):
        inodes = {name: (self.root / name).stat().st_ino for name in self.files}
        files, reviewed = self.read()
        self.assertEqual(files, self.files)
        self.assertEqual(reviewed, {
            name: value.encode() for name, value in self.reviewed.items()})
        self.assertEqual(inodes, {
            name: (self.root / name).stat().st_ino for name in self.files})

    def test_text_mismatch_is_refused_before_archive_read(self):
        (self.root / "livy-transition/livy.conf").write_bytes(b"changed")
        original = delivery.read_delivery_file
        calls = []
        def read_file(fd, relative, **kwargs):
            calls.append(relative)
            return original(fd, relative, **kwargs)
        with patch.object(delivery, "read_delivery_file", side_effect=read_file):
            with self.assertRaisesRegex(ValueError, "Transferred asset differs"):
                self.read()
        self.assertNotIn(delivery.ARCHIVE, calls)

    def test_reference_manifest_missing_or_extra_keys_is_refused(self):
        for reviewed in ({}, dict(self.reviewed, unknown="text")):
            with self.subTest(keys=list(reviewed)):
                self.reviewed = reviewed
                self.save_manifest()
                with self.assertRaises(ValueError):
                    self.read()

    def test_symlink_file_is_refused(self):
        path = self.root / "livy-transition/livy.conf"
        target = self.root / "held"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.read()
        self.assertEqual(target.read_bytes(), self.files["livy-transition/livy.conf"])

    def test_symlink_directory_is_refused(self):
        path = self.root / "livy-transition"
        target = self.root / "held-directory"
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.read()

    def test_hardlink_file_is_refused(self):
        os.link(self.manifest, self.root / "held-manifest")
        with self.assertRaises(ValueError):
            self.read()

    def test_unprotected_file_or_directory_is_refused(self):
        self.manifest.chmod(0o644)
        with self.assertRaises(ValueError):
            self.read()
        self.manifest.chmod(0o600)
        (self.root / "livy-transition").chmod(0o777)
        with self.assertRaises(ValueError):
            self.read()

    def test_unknown_path_and_size_bound_are_enforced(self):
        with self.assertRaises(ValueError):
            delivery.read_delivery_file(
                self.fd, "../outside", owner_uid=os.getuid(), limit=100)
        with self.assertRaises(ValueError):
            delivery.read_delivery_file(
                self.fd, delivery.MANIFEST, owner_uid=os.getuid(), limit=1)


if __name__ == "__main__":
    unittest.main()
