"""Disposable end-to-end asset tests; no Docker, downloads or production paths.

A fake archive digest and YAML parsing stand in for the locked release and Docker
Compose normalization. All delivery reads, preservation checks and writes are real.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml
from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
old_path = list(sys.path)
try:
    sys.path.insert(0, str(ROOT / "scripts/workshops/big-data/spark"))
    import livy_candidate_assets as assets
    import livy_candidate_compose as compose
    import livy_candidate_deliver as deliver
    import livy_candidate_delivery as delivery
    import livy_candidate_stage as stage
    import livy_candidate_verify as verify
finally:
    sys.path[:] = old_path


class CandidateDeliveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.runtime = base / "runtime"
        self.bundle = base / "delivery"
        self.runtime.mkdir(mode=0o750)
        self.bundle.mkdir(mode=0o700)
        self.lock_path = base / "submission.lock"
        self.lock_path.write_bytes(b"")
        self.lock_path.chmod(0o600)
        self.active = False
        self.lock_entries = 0
        self.normalizations = 0
        self.observations = 0
        self.block_second_observation = False

        role = ROOT / "roles/big_data_spark_runtime"
        settings = yaml.safe_load((role / "defaults/main.yml").read_text())
        settings.update(big_data_spark_worker_count=1,
                        big_data_spark_client_enabled=True,
                        big_data_spark_client_bind_ip="192.0.2.10")
        self.env = Environment(loader=FileSystemLoader(str(role / "templates")),
                               undefined=StrictUndefined, trim_blocks=True,
                               lstrip_blocks=True, keep_trailing_newline=True)
        self.env.filters["bool"] = to_bool
        self.baseline_text = self.render("compose.yaml.j2", settings)
        self.write(self.runtime / "compose.yaml", self.baseline_text, 0o640)
        for name in ("livy.conf", "livy-spark-defaults.conf",
                     "livy-build/Dockerfile", "livy-build/livy.zip",
                     "client-access/host_key", "client-access/login_key.pub"):
            self.write(self.runtime / name, ("existing " + name).encode(), 0o600)
        self.live_paths = [path for path in self.runtime.rglob("*") if path.is_file()]
        self.live_before = self.snapshot(self.live_paths)

        settings.update(
            big_data_livy_enabled=True, big_data_livy_access_enabled=True,
            big_data_livy_assets_host_path=verify.ROOT + "/livy-transition")
        templates = {
            "compose.livy-transition.yaml": "compose.yaml.j2",
            "livy-transition/livy-build/Dockerfile": "livy.Dockerfile.j2",
            "livy-transition/livy.conf": "livy.conf.j2",
            "livy-transition/livy-spark-defaults.conf": "livy-spark-defaults.conf.j2",
        }
        self.files = {name: self.render(template, settings)
                      for name, template in templates.items()}
        self.reviewed = {name: self.render(template, settings).decode()
                         for name, template in templates.items()}
        ignore = "livy-transition/livy-build/.dockerignore"
        self.files[ignore] = b"*\n!Dockerfile\n!livy.zip\n"
        self.reviewed[ignore] = self.files[ignore].decode()
        self.files[verify.ARCHIVE] = b"offline archive fixture; not a verified release"
        for name, content in self.files.items():
            self.write(self.bundle / name, content, 0o600)
        for path in self.bundle.rglob("*"):
            if path.is_dir():
                path.chmod(0o700)
        self.save_manifest()

    def render(self, template, settings):
        return self.env.get_template(template).render(**settings).encode()

    def write(self, path, content, mode):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)

    def save_manifest(self):
        self.write(self.bundle / delivery.MANIFEST,
                   json.dumps(self.reviewed).encode(), 0o600)

    def snapshot(self, paths):
        return {str(path): (path.read_bytes(), path.stat().st_ino,
                            path.stat().st_mode & 0o777) for path in paths}

    def assert_live_unchanged(self):
        self.assertEqual(self.snapshot(self.live_paths), self.live_before)

    def assert_no_candidate(self):
        self.assertFalse((self.runtime / "compose.livy-transition.yaml").exists())
        self.assertFalse((self.runtime / "livy-transition").exists())
        self.assert_live_unchanged()

    def assert_locked(self):
        self.assertTrue(self.active)
        contender = os.open(self.lock_path, os.O_RDONLY)
        try:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(contender)

    @contextmanager
    def lock(self):
        fd = os.open(self.lock_path, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.active = True
            self.lock_entries += 1
            yield fd
        finally:
            self.active = False
            os.close(fd)

    @contextmanager
    def open_runtime(self):
        self.assert_locked()
        fd = os.open(self.runtime, assets.FLAGS)
        try:
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def open_bundle(self, path):
        self.assertEqual(path, str(self.bundle))
        fd = os.open(self.bundle, assets.FLAGS)
        try:
            yield fd
        finally:
            os.close(fd)

    def baseline_reader(self, fd):
        self.assert_locked()
        return compose.read_baseline(fd, owner_uid=os.getuid())

    def normalize(self, text):
        self.assert_locked()
        self.normalizations += 1
        return yaml.safe_load(text.decode())

    def observe(self):
        self.assert_locked()
        self.observations += 1
        blocked = self.block_second_observation and self.observations == 2
        return {"docker_sources": [str(self.runtime)] if blocked else [],
                "host_mounts": []}

    def factory(self, fd):
        self.assert_locked()
        return assets.CandidateAssets(
            fd, root=str(self.runtime), owner_uid=os.getuid())

    def invoke(self, *, matching_digest=True):
        def reader(fd):
            return delivery.read_delivery(fd, owner_uid=os.getuid())
        def verified_stage(files, *, reviewed_text_files):
            return stage.stage_verified_candidate(
                files, reviewed_text_files=reviewed_text_files,
                submission_lock=self.lock, runtime_context=self.open_runtime,
                baseline_reader=self.baseline_reader, normalize=self.normalize,
                mount_observer=self.observe, assets_factory=self.factory)
        digest = verify.ARCHIVE_SHA512 if matching_digest else "0" * 128
        with patch.object(verify.hashlib, "sha512", return_value=
                          SimpleNamespace(hexdigest=lambda: digest)):
            return deliver.deliver_candidate(
                str(self.bundle), bundle_context=self.open_bundle,
                reader=reader, stage=verified_stage)

    def test_create_repeat_and_permissions_preserve_all_live_assets(self):
        created = self.invoke()
        self.assertEqual(set(created), set(assets.FILES))
        self.assertEqual(created[-1], "compose.livy-transition.yaml")
        paths = [self.runtime / name for name in assets.FILES]
        before = self.snapshot(paths)
        self.assertEqual(self.invoke(), [])
        self.assertEqual(self.snapshot(paths), before)
        for name, mode in assets.FILES.items():
            path = self.runtime / name
            self.assertEqual(path.read_bytes(), self.files[name])
            self.assertEqual(path.stat().st_mode & 0o777, mode)
        self.assert_live_unchanged()

    def test_transfer_mismatch_prevents_lock_and_all_runtime_writes(self):
        (self.bundle / "livy-transition/livy.conf").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Transferred asset differs"):
            self.invoke()
        self.assertEqual(self.lock_entries, 0)
        self.assert_no_candidate()

    def test_archive_mismatch_prevents_normalization_and_writes(self):
        with self.assertRaisesRegex(ValueError, "release lock"):
            self.invoke(matching_digest=False)
        self.assertEqual(self.normalizations, 0)
        self.assert_no_candidate()

    def test_shared_definition_change_prevents_all_candidate_writes(self):
        name = "compose.livy-transition.yaml"
        changed = yaml.safe_load(self.files[name])
        changed["services"]["spark-client"]["cpus"] = 99
        text = yaml.safe_dump(changed, sort_keys=False)
        self.write(self.bundle / name, text.encode(), 0o600)
        self.reviewed[name] = text
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "service definition differs"):
            self.invoke()
        self.assert_no_candidate()

    def test_second_mount_observation_prevents_all_candidate_writes(self):
        self.block_second_observation = True
        with self.assertRaisesRegex(ValueError, "Docker bind source"):
            self.invoke()
        self.assertEqual(self.observations, 2)
        self.assert_no_candidate()

    def test_failed_write_retains_partial_asset_without_compose_publication(self):
        with patch.object(assets.os, "write", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.invoke()
        self.assertFalse((self.runtime / "compose.livy-transition.yaml").exists())
        partial = self.runtime / "livy-transition/livy.conf"
        self.assertTrue(partial.exists())
        self.assertEqual(partial.read_bytes(), b"")
        with self.assertRaisesRegex(ValueError, "content differs"):
            self.invoke()
        self.assertFalse((self.runtime / "compose.livy-transition.yaml").exists())
        self.assert_live_unchanged()

    def test_existing_candidate_conflict_is_not_overwritten(self):
        self.invoke()
        path = self.runtime / "livy-transition/livy.conf"
        path.write_bytes(b"retain conflicting candidate evidence")
        before = self.snapshot([path])
        with self.assertRaisesRegex(ValueError, "content differs"):
            self.invoke()
        self.assertEqual(self.snapshot([path]), before)
        self.assert_live_unchanged()

    def test_every_real_content_write_occurs_under_the_lock(self):
        original = os.write
        calls = []
        def locked_write(fd, data):
            self.assert_locked()
            calls.append(fd)
            return original(fd, data)
        with patch.object(assets.os, "write", side_effect=locked_write):
            self.invoke()
        self.assertGreaterEqual(len(calls), len(assets.FILES))
        self.assertFalse(self.active)
        self.assert_live_unchanged()


if __name__ == "__main__":
    unittest.main()
