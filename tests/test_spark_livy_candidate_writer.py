"""Disposable filesystem tests; no Docker, downloads or production paths."""
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

PATH = (Path(__file__).resolve().parents[1] /
        "scripts/workshops/big-data/spark/livy_candidate_assets.py")
spec = importlib.util.spec_from_file_location("candidate_assets_test", PATH)
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class CandidateWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, assets.FLAGS)
        self.addCleanup(os.close, self.fd)
        self.store = assets.CandidateAssets(
            self.fd, root=str(self.root), owner_uid=os.getuid())
        self.files = {name: ("trusted " + name).encode() for name in assets.FILES}
        self.mounts = lambda: {"docker_sources": [], "host_mounts": []}
        self.live = self.root / "compose.yaml"
        self.live.write_bytes(b"existing Step 1")
        self.live_inode = self.live.stat().st_ino

    def stage(self):
        return self.store.stage(self.files, self.mounts)

    def test_create_and_repeat_preserve_live_and_candidate_inodes(self):
        self.assertEqual(set(self.stage()), set(assets.FILES))
        inodes = {name: (self.root / name).stat().st_ino for name in assets.FILES}
        self.assertEqual(self.stage(), [])
        for name, mode in assets.FILES.items():
            path = self.root / name
            self.assertEqual(path.read_bytes(), self.files[name])
            self.assertEqual(path.stat().st_mode & 0o777, mode)
            self.assertEqual(path.stat().st_ino, inodes[name])
        self.assertEqual(self.live.read_bytes(), b"existing Step 1")
        self.assertEqual(self.live.stat().st_ino, self.live_inode)

    def test_missing_or_extra_input_refused_before_writes(self):
        for files in ({}, dict(self.files, unknown=b"data")):
            with self.subTest(files=list(files)), self.assertRaises(ValueError):
                self.store.stage(files, self.mounts)
            self.assertEqual(set(os.listdir(self.fd)), {"compose.yaml"})

    def test_changed_existing_content_is_never_overwritten(self):
        self.stage()
        path = self.root / "livy-transition/livy.conf"
        path.write_bytes(b"must survive")
        with self.assertRaisesRegex(ValueError, "content differs"):
            self.stage()
        self.assertEqual(path.read_bytes(), b"must survive")

    def test_symlink_directory_is_refused_without_touching_target(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "livy-transition").symlink_to(outside)
            with self.assertRaises(ValueError):
                self.stage()
            self.assertEqual(os.listdir(outside), [])

    def test_hardlink_file_is_refused(self):
        self.stage()
        path = self.root / "livy-transition/livy.conf"
        os.link(path, self.root / "held-config")
        with self.assertRaises(ValueError):
            self.stage()
        self.assertEqual(path.stat().st_nlink, 2)

    def test_unknown_and_writable_candidate_entries_are_refused(self):
        self.stage()
        unknown = self.root / "livy-transition/foreign"
        unknown.write_bytes(b"preserve")
        with self.assertRaisesRegex(ValueError, "Unknown"):
            self.stage()
        unknown.unlink()
        (self.root / "livy-transition").chmod(0o777)
        with self.assertRaisesRegex(ValueError, "protected"):
            self.stage()

    def test_docker_mounts_include_ancestors_descendants_and_stopped_sources(self):
        for source in (str(self.root), str(self.root / "livy-transition"),
                       str(self.root / "livy-transition/livy.conf"),
                       str(self.root / "compose.livy-transition.yaml")):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "Docker"):
                self.store.stage(self.files, lambda: {
                    "docker_sources": [source], "host_mounts": []})
        self.assertEqual(set(os.listdir(self.fd)), {"compose.yaml"})

    def test_host_candidate_mount_is_refused_but_root_filesystem_is_allowed(self):
        with self.assertRaisesRegex(ValueError, "host mount"):
            self.store.stage(self.files, lambda: {
                "docker_sources": [],
                "host_mounts": [str(self.root / "livy-transition")]})
        self.store.stage(self.files, lambda: {
            "docker_sources": [], "host_mounts": ["/"]})

    def test_unverifiable_or_changed_mount_observation_prevents_writes(self):
        with self.assertRaises(ValueError):
            self.store.stage(self.files, lambda: {})
        observations = iter([
            self.mounts(),
            {"docker_sources": [str(self.root)], "host_mounts": []}])
        with self.assertRaises(ValueError):
            self.store.stage(self.files, lambda: next(observations))
        self.assertEqual(set(os.listdir(self.fd)), {"compose.yaml"})

    def test_missing_runtime_lock_prevents_open_and_observation(self):
        @contextmanager
        def missing_lock():
            yield None
        def forbidden():
            self.fail("Adapter called without existing runtime lock")
        with self.assertRaisesRegex(ValueError, "Existing submission runtime"):
            assets.stage_candidate(
                self.files, submission_lock=missing_lock,
                open_runtime=forbidden, observe_mounts=forbidden)


class CandidatePublicationAndLockTests(unittest.TestCase):
    setUp = CandidateWriterTests.setUp
    stage = CandidateWriterTests.stage
    def test_candidate_definition_is_written_last(self):
        created = self.stage()
        self.assertEqual(created[-1], "compose.livy-transition.yaml")

    def test_failed_write_retains_partial_asset_without_publishing_compose(self):
        from unittest.mock import patch
        with patch.object(assets.os, "write", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.stage()
        self.assertFalse((self.root / "compose.livy-transition.yaml").exists())
        partial = self.root / "livy-transition/livy.conf"
        self.assertTrue(partial.exists())
        self.assertEqual(partial.read_bytes(), b"")
        self.assertEqual(self.live.read_bytes(), b"existing Step 1")
        with self.assertRaisesRegex(ValueError, "content differs"):
            self.stage()

    def test_adapter_lock_scope_covers_writer_and_releases_after_failure(self):
        from unittest.mock import patch
        for fail in (False, True):
            with self.subTest(fail=fail):
                active = {"lock": False, "runtime": False}
                events = []

                @contextmanager
                def lock():
                    active["lock"] = True
                    events.append("lock-enter")
                    try:
                        yield 7
                    finally:
                        active["lock"] = False
                        events.append("lock-exit")

                @contextmanager
                def runtime():
                    self.assertTrue(active["lock"])
                    active["runtime"] = True
                    events.append("runtime-enter")
                    try:
                        yield 8
                    finally:
                        active["runtime"] = False
                        events.append("runtime-exit")

                def write(files, observe):
                    self.assertEqual(active, {"lock": True, "runtime": True})
                    self.assertIs(files, self.files)
                    self.assertIs(observe, self.mounts)
                    events.append("write")
                    if fail:
                        raise OSError("writer failed")
                    return ["created"]

                with patch.object(assets, "CandidateAssets") as store:
                    store.return_value.stage.side_effect = write
                    if fail:
                        with self.assertRaisesRegex(OSError, "writer failed"):
                            assets.stage_candidate(
                                self.files, submission_lock=lock,
                                open_runtime=runtime, observe_mounts=self.mounts)
                    else:
                        self.assertEqual(assets.stage_candidate(
                            self.files, submission_lock=lock,
                            open_runtime=runtime, observe_mounts=self.mounts),
                            ["created"])
                    store.assert_called_once_with(8)
                self.assertEqual(events, [
                    "lock-enter", "runtime-enter", "write",
                    "runtime-exit", "lock-exit"])
                self.assertEqual(active, {"lock": False, "runtime": False})


if __name__ == "__main__":
    unittest.main()
