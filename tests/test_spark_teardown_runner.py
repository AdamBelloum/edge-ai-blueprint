"""Runner wiring tests; Docker and filesystem access are mocked."""
from contextlib import contextmanager, nullcontext
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import test_spark_teardown_assets as assets_tests
import test_spark_teardown_seed as seed_tests
import test_spark_teardown_images as image_tests
import test_spark_teardown_directory as directory_tests
import test_spark_teardown_docker as docker_tests
import test_spark_teardown_sequence as sequence_tests
from test_spark_teardown_evidence import evidence

dependencies = {
    "teardown_assets": assets_tests.module,
    "teardown_seed": seed_tests.module,
    "teardown_images": image_tests.module,
    "teardown_directory": directory_tests.directory,
    "teardown_docker": docker_tests.adapter,
    "teardown_evidence": evidence,
    "teardown_sequence": sequence_tests.sequence,
}
path = Path(__file__).resolve().parents[1] / (
    "scripts/workshops/big-data/spark/teardown_runner.py"
)
spec = importlib.util.spec_from_file_location("teardown_runner", path)
runner = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, dependencies):
    spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        # Existing wiring tests must not access the production submission lock.
        mock = patch.object(runner, "locked_submission_runtime",
                            side_effect=lambda: nullcontext())
        mock.start()
        self.addCleanup(mock.stop)
        self.assets = Mock()
        self.assets.remove.return_value = []
        mock = patch.object(runner, "validated_runtime_assets",
                            side_effect=lambda: nullcontext(self.assets))
        mock.start()
        self.addCleanup(mock.stop)
        self.seed = Mock()
        self.seed.remove.return_value = []
        mock = patch.object(runner, "validated_seed_assets",
                            side_effect=lambda: nullcontext(self.seed))
        mock.start()
        self.addCleanup(mock.stop)
        self.images = Mock()
        self.images.remove.return_value = []
        mock = patch.object(runner, "ImageCleanup", return_value=self.images)
        mock.start()
        self.addCleanup(mock.stop)
        mock = patch.object(runner, "clear_evidence", return_value=False)
        self.clear = mock.start()
        self.addCleanup(mock.stop)

    def test_submission_lock_failure_prevents_docker_and_releases_evidence(self):
        events = []

        @contextmanager
        def evidence_lock():
            try:
                yield 42
            finally:
                events.append("evidence released")

        @contextmanager
        def submission_lock():
            raise RuntimeError("submission active")
            yield

        with patch.object(runner, "locked_evidence_directory", evidence_lock), \
             patch.object(runner, "locked_submission_runtime", submission_lock), \
             patch.object(runner, "Docker") as factory:
            with self.assertRaisesRegex(RuntimeError, "submission active"):
                runner.run_teardown()
            factory.assert_not_called()
        self.assertEqual(events, ["evidence released"])

    def test_both_locks_cover_docker_and_sequence_and_release_in_reverse(self):
        events = []

        @contextmanager
        def evidence_lock():
            events.append("evidence acquired")
            try:
                yield 42
            finally:
                events.append("evidence released")

        @contextmanager
        def submission_lock():
            events.append("submission acquired")
            try:
                yield 99
            finally:
                events.append("submission released")

        def factory():
            events.append("docker")
            return Mock()

        def sequence(**callbacks):
            events.append("sequence")
            return {"verified": True}

        with patch.object(runner, "locked_evidence_directory", evidence_lock), \
             patch.object(runner, "locked_submission_runtime", submission_lock), \
             patch.object(runner, "Docker", side_effect=factory), \
             patch.object(runner, "teardown", side_effect=sequence):
            self.assertEqual(runner.run_teardown(), {"verified": True,
                "removed_asset_paths": [], "retry_evidence_removed": False, "removed_image_references": []})
        self.assertEqual(events, [
            "evidence acquired", "submission acquired", "docker", "sequence",
            "submission released", "evidence released",
        ])

    def test_lock_precedes_docker_and_evidence_uses_daemon_identity(self):
        events = []
        docker = Mock()

        @contextmanager
        def locked():
            events.append("locked")
            try:
                yield 42
            finally:
                events.append("released")

        def factory():
            events.append("docker")
            return docker

        def identity():
            events.append("identity")
            return "local-daemon"

        docker.daemon_id.side_effect = identity

        def sequence(**callbacks):
            events.append("sequence")
            self.assertEqual(callbacks["snapshot"], docker.snapshot)
            self.assertEqual(callbacks["remove_container"],
                             docker.remove_container)
            self.assertEqual(callbacks["remove_network"],
                             docker.remove_network)
            self.assertEqual(callbacks["load_evidence"](), {"a" * 64})
            callbacks["save_evidence"]({"a" * 64})
            return {"verified": True}

        with patch.object(runner, "locked_evidence_directory", locked), \
             patch.object(runner, "Docker", side_effect=factory), \
             patch.object(runner, "teardown", side_effect=sequence), \
             patch.object(runner, "load_evidence",
                          return_value={"a" * 64}) as load, \
             patch.object(runner, "save_evidence") as save:
            self.assertEqual(runner.run_teardown(), {"verified": True,
                "removed_asset_paths": [], "retry_evidence_removed": False, "removed_image_references": []})
            load.assert_called_once_with(42, "local-daemon")
            save.assert_called_once_with(42, "local-daemon", {"a" * 64})
        self.assertEqual(events, [
            "locked", "docker", "identity", "sequence", "released",
        ])

    def test_lock_failure_prevents_docker_access(self):
        @contextmanager
        def refused():
            raise RuntimeError("lock unavailable")
            yield

        with patch.object(runner, "locked_evidence_directory", refused), \
             patch.object(runner, "Docker") as factory:
            with self.assertRaisesRegex(RuntimeError, "lock unavailable"):
                runner.run_teardown()
            factory.assert_not_called()

    def test_sequence_failure_releases_lock_and_propagates(self):
        events = []

        @contextmanager
        def locked():
            try:
                yield 42
            finally:
                events.append("released")

        with patch.object(runner, "locked_evidence_directory", locked), \
             patch.object(runner, "Docker"), \
             patch.object(runner, "teardown",
                          side_effect=RuntimeError("cleanup failed")):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                runner.run_teardown()
        self.assertEqual(events, ["released"])


    def test_asset_preflight_failure_prevents_docker(self):
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "validated_runtime_assets", side_effect=ValueError("unsafe files")), \
             patch.object(runner, "Docker") as factory:
            with self.assertRaisesRegex(ValueError, "unsafe files"):
                runner.run_teardown()
            factory.assert_not_called()
        self.assets.remove.assert_not_called()
        self.clear.assert_not_called()

    def test_files_and_record_are_removed_after_sequence_under_both_locks(self):
        events = []

        @contextmanager
        def lock(label, value):
            events.append(label + " acquired")
            try:
                yield value
            finally:
                events.append(label + " released")

        self.assets.remove.side_effect = lambda: events.append("files") or ["/generated"]
        self.clear.side_effect = lambda *args: events.append("record") or True
        with patch.object(runner, "locked_evidence_directory", side_effect=lambda: lock("evidence", 42)), \
             patch.object(runner, "locked_submission_runtime", side_effect=lambda: lock("submission", 99)), \
             patch.object(runner, "Docker"), \
             patch.object(runner, "teardown", side_effect=lambda **kw: events.append("sequence") or {}):
            result = runner.run_teardown()
        self.assertEqual(events, ["evidence acquired", "submission acquired", "sequence",
                                 "files", "record", "submission released", "evidence released"])
        self.assertEqual(result["removed_asset_paths"], ["/generated"])
        self.assertTrue(result["retry_evidence_removed"])

    def test_file_failure_prevents_record_clearing(self):
        self.assets.remove.side_effect = OSError("file deletion failed")
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "Docker"), patch.object(runner, "teardown", return_value={}):
            with self.assertRaisesRegex(OSError, "file deletion failed"):
                runner.run_teardown()
        self.clear.assert_not_called()

    def test_sequence_failure_prevents_file_deletion(self):
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "Docker"), \
             patch.object(runner, "teardown", side_effect=RuntimeError("resource failure")):
            with self.assertRaisesRegex(RuntimeError, "resource failure"):
                runner.run_teardown()
        self.assets.remove.assert_not_called()
        self.clear.assert_not_called()


    def test_seed_preflight_failure_prevents_docker_and_deletion(self):
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "validated_seed_assets", side_effect=ValueError("unsafe seed")), \
             patch.object(runner, "Docker") as factory:
            with self.assertRaisesRegex(ValueError, "unsafe seed"):
                runner.run_teardown()
            factory.assert_not_called()
        self.assets.remove.assert_not_called()
        self.seed.remove.assert_not_called()
        self.clear.assert_not_called()

    def test_seed_failure_prevents_record_clear(self):
        self.seed.remove.side_effect = OSError("seed deletion failed")
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "Docker"), patch.object(runner, "teardown", return_value={}):
            with self.assertRaisesRegex(OSError, "seed deletion failed"):
                runner.run_teardown()
        self.clear.assert_not_called()

    def test_seed_deletion_follows_docker_and_runtime_files(self):
        events = []
        self.assets.remove.side_effect = lambda: events.append("runtime files") or []
        self.seed.remove.side_effect = lambda: events.append("seed") or ["/seed"]
        self.clear.side_effect = lambda *args: events.append("record") or False
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "Docker"), \
             patch.object(runner, "teardown", side_effect=lambda **kw: events.append("Docker") or {}):
            result = runner.run_teardown()
        self.assertEqual(events, ["Docker", "runtime files", "seed", "record"])
        self.assertEqual(result["removed_asset_paths"], ["/seed"])

    def test_sequence_failure_does_not_delete_seed(self):
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "Docker"), \
             patch.object(runner, "teardown", side_effect=RuntimeError("runtime failure")):
            with self.assertRaisesRegex(RuntimeError, "runtime failure"):
                runner.run_teardown()
        self.seed.remove.assert_not_called()


    def test_image_preflight_failure_blocks_resource_and_file_deletion(self):
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "Docker"), \
             patch.object(runner, "ImageCleanup", side_effect=ValueError("unsafe image")), \
             patch.object(runner, "teardown") as sequence:
            with self.assertRaisesRegex(ValueError, "unsafe image"):
                runner.run_teardown()
            sequence.assert_not_called()
        self.assets.remove.assert_not_called()
        self.seed.remove.assert_not_called()
        self.clear.assert_not_called()

    def test_image_removal_failure_blocks_file_removal_and_completion(self):
        self.images.remove.side_effect = RuntimeError("image busy")
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "Docker"), patch.object(runner, "teardown", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "image busy"):
                runner.run_teardown()
        self.assets.remove.assert_not_called()
        self.seed.remove.assert_not_called()
        self.clear.assert_not_called()

    def test_images_removed_after_resources_before_files_under_both_locks(self):
        events = []

        @contextmanager
        def lock(label, value):
            events.append(label + " acquired")
            try:
                yield value
            finally:
                events.append(label + " released")

        self.images.remove.side_effect = lambda: events.append("images") or ["image-ref"]
        self.assets.remove.side_effect = lambda: events.append("runtime files") or []
        self.seed.remove.side_effect = lambda: events.append("seed") or []
        self.clear.side_effect = lambda *args: events.append("record") or False
        with patch.object(runner, "locked_evidence_directory", side_effect=lambda: lock("evidence", 42)), \
             patch.object(runner, "locked_submission_runtime", side_effect=lambda: lock("submission", 99)), \
             patch.object(runner, "Docker"), \
             patch.object(runner, "teardown", side_effect=lambda **kw: events.append("resources") or {}):
            result = runner.run_teardown()
        self.assertEqual(events, ["evidence acquired", "submission acquired", "resources", "images",
                                 "runtime files", "seed", "record", "submission released", "evidence released"])
        self.assertEqual(result["removed_image_references"], ["image-ref"])

    def test_resource_failure_does_not_remove_images(self):
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "Docker"), \
             patch.object(runner, "teardown", side_effect=RuntimeError("resource failure")):
            with self.assertRaisesRegex(RuntimeError, "resource failure"):
                runner.run_teardown()
        self.images.remove.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
