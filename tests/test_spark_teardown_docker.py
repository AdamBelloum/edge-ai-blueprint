"""Mocked Docker-command tests; never invokes Docker."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

path = Path(__file__).resolve().parents[1] / (
    "scripts/workshops/big-data/spark/teardown_docker.py"
)
spec = importlib.util.spec_from_file_location("teardown_docker", path)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class DockerAdapterTests(unittest.TestCase):
    def setUp(self):
        self.run = Mock(return_value=SimpleNamespace(stdout=""))
        self.docker = adapter.Docker(run=self.run)

    def test_empty_snapshot_uses_scoped_local_discovery(self):
        self.assertEqual(self.docker.snapshot(), ([], [], []))
        expected = [
            ["container", "ls", "--all", "--quiet", "--no-trunc",
             "--filter", adapter.FILTER],
            ["network", "ls", "--quiet", "--no-trunc",
             "--filter", adapter.FILTER],
            ["volume", "ls", "--quiet", "--filter", adapter.FILTER],
        ]
        self.assertEqual(self.run.call_count, 3)
        for call, arguments in zip(self.run.call_args_list, expected):
            self.assertEqual(call.args[0], adapter.PREFIX + arguments)
            self.assertEqual(call.kwargs, {
                "check": True, "text": True,
                "capture_output": True, "timeout": 120,
            })

    def test_removal_is_by_full_id_without_volume_removal(self):
        identifier = "a" * 64
        self.docker.remove_container(identifier)
        self.docker.remove_network(identifier)
        self.assertEqual(self.run.call_args_list[0].args[0],
                         adapter.PREFIX +
                         ["container", "rm", "--force", identifier])
        self.assertEqual(self.run.call_args_list[1].args[0],
                         adapter.PREFIX + ["network", "rm", identifier])

    def test_invalid_ids_never_reach_docker(self):
        for identifier in ("--force", "short", None):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    self.docker.remove_container(identifier)
                with self.assertRaises(ValueError):
                    self.docker.remove_network(identifier)
        self.run.assert_not_called()

    def test_inspection_must_match_discovered_ids(self):
        self.run.return_value.stdout = '[{"Id": "' + "b" * 64 + '"}]'
        with self.assertRaisesRegex(ValueError, "do not match"):
            self.docker.inspect("container", ["a" * 64])

    def test_command_failure_is_preserved(self):
        self.run.side_effect = subprocess.CalledProcessError(1, ["docker"])
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker.snapshot()

    def test_missing_daemon_identity_is_refused(self):
        with self.assertRaisesRegex(ValueError, "identity is missing"):
            self.docker.daemon_id()


if __name__ == "__main__":
    unittest.main(verbosity=2)
