"""Runner wiring tests; Docker and filesystem access are mocked."""
from contextlib import contextmanager, nullcontext
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import test_spark_teardown_directory as directory_tests
import test_spark_teardown_docker as docker_tests
import test_spark_teardown_sequence as sequence_tests
from test_spark_teardown_evidence import evidence

dependencies = {
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
            self.assertEqual(runner.run_teardown(), {"verified": True})
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
            self.assertEqual(runner.run_teardown(), {"verified": True})
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
