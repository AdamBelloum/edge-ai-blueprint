"""Fake-command and mocked-FD tests; no live Docker or production access."""
from contextlib import ExitStack
import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

old_path = list(sys.path)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                         "scripts/workshops/big-data/spark"))
    import livy_candidate_observe as adapter
finally:
    sys.path[:] = old_path

CID = "a" * 64


class CandidateMountObservationTests(unittest.TestCase):
    def invoke(self, replies, hosts=lambda: {"/"}):
        calls = []
        responses = iter(replies)
        self.command_envs = []
        def run(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(
                argv[:3], ["docker", "--host", "unix:///var/run/docker.sock"])
            env = kwargs.get("env")
            self.assertIsInstance(env, dict)
            self.assertFalse(any(
                key.startswith(("DOCKER_", "COMPOSE_"))
                and key != "COMPOSE_DISABLE_ENV_FILE" for key in env))
            self.assertTrue(env.get("COMPOSE_DISABLE_ENV_FILE") == "1")
            self.command_envs.append(dict(env))
            self.assertEqual(kwargs["timeout"], 30)
            self.assertFalse(kwargs["check"])
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            if isinstance(response, tuple):
                code, text = response
            else:
                code, text = 0, response
            return SimpleNamespace(returncode=code, stdout=text)
        return adapter.observe_mounts(run=run, host_mounts=hosts), calls

    def inspected(self, mounts=None, cid=CID):
        return json.dumps([{"Id": cid, "Mounts": [] if mounts is None else mounts}])

    def test_stopped_and_unlabelled_containers_are_included(self):
        result, calls = self.invoke([
            "daemon", CID,
            self.inspected([{"Type": "bind", "Source": "/protected/config"}]),
            CID, "daemon"])
        self.assertEqual(result["docker_sources"], ["/protected/config"])
        lists = [call for call in calls if call[3:5] == ["container", "ls"]]
        self.assertEqual(len(lists), 2)
        for call in lists:
            self.assertIn("--all", call)
            self.assertIn("--no-trunc", call)
            self.assertNotIn("--filter", call)

    def test_empty_inventory_requires_no_inspect(self):
        result, calls = self.invoke(["daemon", "", "", "daemon"])
        self.assertEqual(result, {"docker_sources": [], "host_mounts": ["/"]})
        self.assertFalse(any("inspect" in call for call in calls))

    def test_changed_inventory_and_daemon_are_refused(self):
        for replies in (
            ["daemon", CID, self.inspected(), "", "daemon"],
            ["daemon", CID, self.inspected(), CID, "different-daemon"]):
            with self.subTest(replies=replies), self.assertRaises(ValueError):
                self.invoke(replies)

    def test_failed_commands_invalid_ids_and_incomplete_inspection_are_refused(self):
        for replies in (
            [(1, "")],
            ["daemon", "short-id"],
            ["daemon", CID + "\n" + CID],
            ["daemon", CID, "[]"],
            ["daemon", CID, self.inspected(cid="b" * 64)]):
            with self.subTest(replies=replies), self.assertRaises(ValueError):
                self.invoke(replies)

    def test_unverifiable_mounts_are_refused(self):
        for mounts in (
            [{"Type": "bind"}],
            [{"Type": "bind", "Source": "relative"}],
            [{"Type": "unknown", "Source": "/path"}]):
            with self.subTest(mounts=mounts), self.assertRaises(ValueError):
                self.invoke(["daemon", CID, self.inspected(mounts)])

    def test_changed_host_mounts_are_refused(self):
        hosts = iter([{"/"}, {"/", "/new-mount"}])
        with self.assertRaisesRegex(ValueError, "Host mount inventory changed"):
            self.invoke(["daemon", "", "", "daemon"], lambda: next(hosts))

    def test_timeout_propagates_without_inventing_empty_inventory(self):
        import subprocess
        with self.assertRaises(subprocess.TimeoutExpired):
            self.invoke([subprocess.TimeoutExpired(["docker"], 30)])


    def test_fixed_local_daemon_for_complete_discovery(self):
        _, calls = self.invoke([
            "daemon", CID, self.inspected(), CID, "daemon"])
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(
            call[:3] == ["docker", "--host", "unix:///var/run/docker.sock"]
            for call in calls))
        self.assertTrue(any(call[3:5] == ["container", "inspect"]
                            for call in calls))

    def test_inherited_daemon_and_compose_overrides_are_removed(self):
        overrides = {
            "DOCKER_HOST": "tcp://example.invalid:2376",
            "DOCKER_CONTEXT": "synthetic-remote",
            "DOCKER_CONFIG": "/synthetic/docker-config",
            "DOCKER_TLS_VERIFY": "1",
            "COMPOSE_FILE": "/synthetic/compose.yaml",
            "COMPOSE_PROFILES": "unreviewed",
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
        }
        with patch.dict(adapter.os.environ, overrides, clear=True):
            result, calls = self.invoke(["daemon", "", "", "daemon"])
        self.assertEqual(result["docker_sources"], [])
        self.assertEqual(len(calls), 4)
        expected = {
            "PATH": "/usr/bin:/bin", "LANG": "C",
            "COMPOSE_DISABLE_ENV_FILE": "1",
        }
        self.assertTrue(all(env == expected for env in self.command_envs))


class ProtectedRuntimeAdapterTests(unittest.TestCase):
    def test_non_root_is_refused_before_open(self):
        with patch.object(adapter.os, "geteuid", return_value=1000),              patch.object(adapter.os, "open") as opened:
            with self.assertRaises(PermissionError):
                with adapter.open_runtime():
                    self.fail("Unexpected runtime access")
            opened.assert_not_called()

    def test_existing_ancestors_open_nofollow_and_close_after_caller_failure(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(adapter.os, "geteuid", return_value=0))
            opened = stack.enter_context(patch.object(
                adapter.os, "open", side_effect=range(10, 16)))
            closed = stack.enter_context(patch.object(adapter.os, "close"))
            stack.enter_context(patch.object(adapter.os, "fstat", return_value=
                SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)))
            with self.assertRaisesRegex(RuntimeError, "caller failed"):
                with adapter.open_runtime() as fd:
                    self.assertEqual(fd, 15)
                    raise RuntimeError("caller failed")
            self.assertEqual([c.args[0] for c in opened.call_args_list],
                             ["/", *adapter.SUBMISSION_COMPONENTS])
            self.assertTrue(all(c.args[1] & adapter.os.O_NOFOLLOW
                                for c in opened.call_args_list))
            self.assertEqual([c.args[0] for c in closed.call_args_list],
                             list(range(15, 9, -1)))


if __name__ == "__main__":
    unittest.main()
