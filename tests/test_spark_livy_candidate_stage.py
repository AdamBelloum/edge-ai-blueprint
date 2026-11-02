"""Injected orchestration tests; no production access, Docker or real archive."""
from contextlib import contextmanager
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_spark_livy_candidate_verify as verification_tests

old_path = list(sys.path)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                         "scripts/workshops/big-data/spark"))
    import livy_candidate_stage as stage
    import livy_candidate_verify as verify
finally:
    sys.path[:] = old_path


class VerifiedCandidateStageTests(unittest.TestCase):
    def setUp(self):
        verification_tests.CandidateVerificationTests.setUp(self)
        self.events = []
        self.active = {"lock": False, "runtime": False}
        self.fail_writer = False
        self.change_baseline = False
        self.fail_normalization = False
        self.reads = 0
        self.writes = 0

    def assert_locked(self):
        self.assertEqual(self.active, {"lock": True, "runtime": True})

    @contextmanager
    def lock(self):
        self.active["lock"] = True
        self.events.append("lock-enter")
        try:
            yield 7
        finally:
            self.events.append("lock-exit")
            self.active["lock"] = False

    @contextmanager
    def runtime(self):
        self.assertTrue(self.active["lock"])
        self.active["runtime"] = True
        self.events.append("runtime-enter")
        try:
            yield 8
        finally:
            self.events.append("runtime-exit")
            self.active["runtime"] = False

    def read(self, fd):
        self.assert_locked()
        self.assertEqual(fd, 8)
        self.reads += 1
        self.events.append("baseline-read")
        return b"changed" if self.change_baseline and self.reads > 1 else b"baseline"

    def normalize(self, text):
        self.assert_locked()
        self.events.append("normalize")
        if self.fail_normalization:
            raise ValueError("normalization failed")
        return self.baseline if text == b"baseline" else self.candidate

    def observe(self):
        self.assert_locked()
        self.events.append("observe")
        return {"docker_sources": [], "host_mounts": []}

    def factory(self, fd):
        self.assert_locked()
        self.assertEqual(fd, 8)
        self.events.append("factory")
        return SimpleNamespace(stage=self.write)

    def write(self, files, observer):
        self.assert_locked()
        self.assertEqual(files, self.files)
        self.writes += 1
        observer()
        self.events.append("write")
        if self.fail_writer:
            raise OSError("writer failure")
        return ["candidate-file"]

    def invoke(self, matching_digest=True):
        digest = verify.ARCHIVE_SHA512 if matching_digest else "0" * 128
        with patch.object(verify.hashlib, "sha512", return_value=
                          SimpleNamespace(hexdigest=lambda: digest)):
            return stage.stage_verified_candidate(
                self.files, reviewed_text_files=self.reviewed,
                submission_lock=self.lock, runtime_context=self.runtime,
                baseline_reader=self.read, normalize=self.normalize,
                mount_observer=self.observe, assets_factory=self.factory)

    def test_success_verifies_and_rechecks_before_locked_write(self):
        self.assertEqual(self.invoke(), ["candidate-file"])
        self.assertEqual(self.events, [
            "lock-enter", "runtime-enter", "baseline-read",
            "normalize", "normalize", "baseline-read",
            "factory", "observe", "write", "runtime-exit", "lock-exit"])
        self.assertEqual(self.active, {"lock": False, "runtime": False})

    def test_archive_failure_prevents_baseline_read_and_writer(self):
        with self.assertRaisesRegex(ValueError, "release lock"):
            self.invoke(matching_digest=False)
        self.assertEqual(self.reads, 0)
        self.assertEqual(self.writes, 0)
        self.assertEqual(self.events[-2:], ["runtime-exit", "lock-exit"])

    def test_shared_service_change_prevents_writer(self):
        self.candidate["services"]["spark-worker-1"]["mem_limit"] = "4096m"
        with self.assertRaisesRegex(ValueError, "service definition differs"):
            self.invoke()
        self.assertEqual(self.writes, 0)

    def test_baseline_change_before_write_is_refused(self):
        self.change_baseline = True
        with self.assertRaisesRegex(ValueError, "Compose content changed"):
            self.invoke()
        self.assertEqual(self.writes, 0)

    def test_normalization_failure_prevents_writer(self):
        self.fail_normalization = True
        with self.assertRaisesRegex(ValueError, "normalization failed"):
            self.invoke()
        self.assertEqual(self.writes, 0)

    def test_writer_failure_propagates_and_releases_contexts(self):
        self.fail_writer = True
        with self.assertRaisesRegex(OSError, "writer failure"):
            self.invoke()
        self.assertEqual(self.events[-2:], ["runtime-exit", "lock-exit"])
        self.assertEqual(self.active, {"lock": False, "runtime": False})

    def test_missing_runtime_lock_prevents_other_adapters(self):
        @contextmanager
        def missing():
            yield None
        def forbidden():
            self.fail("Runtime opened without an existing submission lock")
        with self.assertRaisesRegex(ValueError, "Existing submission runtime"):
            stage.stage_verified_candidate(
                self.files, reviewed_text_files=self.reviewed,
                submission_lock=missing, runtime_context=forbidden)
        self.assertEqual(self.writes, 0)


if __name__ == "__main__":
    unittest.main()
