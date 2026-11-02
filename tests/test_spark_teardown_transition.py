# Offline transition-reset tests: temporary trees, fake Docker, no live access.

from contextlib import nullcontext
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import socket
import unittest
from unittest.mock import Mock, patch

import test_spark_teardown_assets as asset_fixture
import test_spark_teardown_docker as docker_fixture
import test_spark_teardown_livy_access as access_fixture
import test_spark_teardown_participant_runtime as participant_fixture
import test_spark_teardown_runner as runner_fixture
import test_spark_teardown_sequence as sequence_fixture

assets = asset_fixture.module
adapter = docker_fixture.adapter
sequence = sequence_fixture.sequence
validator = sequence_fixture.validator
runner = runner_fixture.runner
ROOT = Path(__file__).resolve().parents[1]


class OfflineTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(socket, "socket",
            side_effect=AssertionError("Network forbidden in offline reset tests"))
        guard.start()
        self.addCleanup(guard.stop)
        guard = patch.object(adapter.Docker, "command",
            side_effect=AssertionError("Live Docker forbidden in offline reset tests"))
        guard.start()
        self.addCleanup(guard.stop)


class CandidateAssetTests(OfflineTests):
    plan = asset_fixture.AssetTests.plan
    generated = asset_fixture.AssetTests.generated

    def setUp(self):
        super().setUp()
        asset_fixture.AssetTests.setUp(self)

    def candidate(self):
        for relative, mode in assets.TRANSITION_DIRECTORIES.items():
            path = self.root / relative
            path.mkdir()
            path.chmod(mode)
        for relative, mode in assets.TRANSITION_FILES.items():
            path = self.root / relative
            path.write_bytes(b"generated")
            path.chmod(mode)

    def test_allowlist_matches_candidate_generator(self):
        path = ROOT / "scripts/workshops/big-data/spark/livy_candidate_assets.py"
        spec = importlib.util.spec_from_file_location("_candidate_reset_layout", path)
        candidate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(candidate)
        self.assertEqual(assets.TRANSITION_FILES, candidate.FILES)
        self.assertEqual(set(assets.TRANSITION_DIRECTORIES), set(candidate.DIRECTORIES))

    def test_baseline_and_candidate_remove_preserving_lock_and_external_source(self):
        self.candidate()
        self.generated()
        for relative in assets.FILES:
            (self.root / relative).write_text("baseline")
            (self.root / relative).chmod(0o640)
        lock_inode = (self.root / assets.LOCK).stat().st_ino
        plan = self.plan()
        plan.check_remaining_docker_sources([])
        removed = plan.remove()
        self.assertIn(str(self.root / "livy-transition"), removed)
        self.assertIn(str(self.root / "compose.livy-transition.yaml"), removed)
        self.assertEqual(set(self.root.iterdir()), {self.root / assets.LOCK})
        self.assertEqual((self.root / assets.LOCK).stat().st_ino, lock_inode)
        self.assertEqual(self.outside.read_text(), "must survive")
        self.assertEqual(self.plan().remove(), [])

    def test_partial_candidate_layout_is_supported(self):
        (self.root / "livy-transition").mkdir()
        (self.root / "livy-transition").chmod(0o750)
        self.assertEqual(self.plan().remove(), [str(self.root / "livy-transition")])
        (self.root / "compose.livy-transition.yaml").write_text("partial")
        (self.root / "compose.livy-transition.yaml").chmod(0o640)
        self.assertEqual(self.plan().remove(),
                         [str(self.root / "compose.livy-transition.yaml")])

    def test_unknown_nested_private_key_prevents_all_asset_deletion(self):
        self.candidate()
        run = self.generated()
        unexpected = self.root / "livy-transition/livy-build/login_key"
        unexpected.write_bytes(b"offline-fixture")
        unexpected.chmod(0o600)
        with self.assertRaises(ValueError):
            self.plan()
        self.assertTrue((run / "driver.log").exists())
        self.assertTrue(unexpected.exists())

    def test_exact_candidate_modes_are_required(self):
        self.candidate()
        for relative in ("compose.livy-transition.yaml",
                         "livy-transition", "livy-transition/livy-build/livy.zip"):
            path = self.root / relative
            original = path.stat().st_mode & 0o777
            path.chmod(0o700 if path.is_dir() else 0o640)
            if (path.stat().st_mode & 0o777) == original:
                path.chmod(0o600)
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.plan()
            path.chmod(original)

    def test_candidate_symlink_hardlink_and_fifo_are_refused(self):
        self.candidate()
        target = self.root / "livy-transition/livy-build/livy.zip"
        target.unlink()
        target.symlink_to(self.outside)
        with self.assertRaises(ValueError):
            self.plan()
        target.unlink()
        self.outside.chmod(0o600)
        os.link(self.outside, target)
        with self.assertRaises(ValueError):
            self.plan()
        target.unlink()
        os.mkfifo(target, 0o600)
        with self.assertRaises(ValueError):
            self.plan()
        self.assertEqual(self.outside.read_text(), "must survive")

    def test_mounted_candidate_tree_is_refused(self):
        self.candidate()
        for relative in ("livy-transition", "livy-transition/livy-build/livy.zip"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                self.plan(mounts={str(self.root / relative)})

    def test_nested_replacement_and_in_place_change_block_removal(self):
        self.candidate()
        path = self.root / "livy-transition/livy.conf"
        plan = self.plan()
        path.write_bytes(b"changed-in-place")
        with self.assertRaises(ValueError):
            plan.remove()
        plan = self.plan()
        path.unlink()
        path.write_bytes(b"replacement-with-different-size")
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            plan.remove()
        self.assertTrue((self.root / "compose.livy-transition.yaml").exists())

    def test_file_contents_are_not_read_during_validation_or_removal(self):
        self.candidate()
        with patch.object(assets.os, "read",
                          side_effect=AssertionError("No credential/archive reads")):
            self.plan().remove()

    def test_partial_nested_removal_can_resume(self):
        self.candidate()
        plan = self.plan()
        original = plan._delete
        def failing(parent, name, device):
            if name == "Dockerfile":
                raise RuntimeError("simulated partial deletion")
            return original(parent, name, device)
        with patch.object(plan, "_delete", side_effect=failing):
            with self.assertRaises(RuntimeError):
                plan.remove()
        self.assertFalse((self.root / "compose.livy-transition.yaml").exists())
        self.assertTrue((self.root / "livy-transition/livy-build/livy.zip").exists())
        self.assertEqual(self.plan().remove(), [str(self.root / "livy-transition")])
        self.assertEqual(self.plan().remove(), [])

    def test_remaining_bind_source_overlap_is_refused_without_deletion(self):
        self.candidate()
        plan = self.plan()
        for source in (str(self.root), str(self.root.parent), "/",
                       str(self.root / "livy-transition"),
                       str(self.root / "livy-transition/livy.conf"),
                       str(self.root / "compose.livy-transition.yaml"),
                       "//" + str(self.root).lstrip("/")):
            with self.subTest(source=source), self.assertRaises(ValueError):
                plan.check_remaining_docker_sources([source])
        self.assertTrue((self.root / "livy-transition/livy.conf").exists())
        plan.check_remaining_docker_sources([
            str(self.root / "livy-transition-other"),
            str(self.root / assets.LOCK), str(self.outside)])

    def test_invalid_bind_observation_is_not_empty_success(self):
        self.candidate()
        for sources in (None, "not-a-list", ["relative"], ["/a/../b"], ["/bad\x00"]):
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                self.plan().check_remaining_docker_sources(sources)


def transition_state():
    containers, networks, volumes = deepcopy(access_fixture.livy_access())
    used = {container["Id"] for container in containers}
    livy = next((container for container in containers
                 if container["Config"]["Labels"].get("com.docker.compose.service")
                 == "spark-livy"), None)
    if livy is None:
        livy = deepcopy(next(container for container in containers
            if container["Config"]["Labels"].get("com.docker.compose.service")
            == "spark-master"))
        livy["Id"] = next(char * 64 for char in "de9876543210" if char * 64 not in used)
        livy["Name"] = "/" + validator.PROJECT + "-spark-livy-1"
        livy["Config"]["Labels"]["com.docker.compose.service"] = "spark-livy"
        containers.append(livy)
    for container in containers:
        labels = container["Config"]["Labels"]
        if labels.get("com.docker.compose.service") in {"spark-livy", "spark-livy-access"}:
            labels["com.docker.compose.project.config_files"] = validator.TRANSITION_CONFIG
    livy["Mounts"] = [dict(Type="bind", RW=False, Source=source, Destination=destination)
        for source, destination in sorted({validator.DATA_MOUNT}
                                         | validator.TRANSITION_LIVY_MOUNTS)]
    # Include the retained stopped direct client alongside the new gateway.
    direct = deepcopy(participant_fixture.participant()[0][-1])
    used = {container["Id"] for container in containers}
    direct["Id"] = next(char * 64 for char in "ef9876543210" if char * 64 not in used)
    direct["State"] = {"Running": False}
    containers.append(direct)
    for network in networks:
        network["Containers"] = {
            container["Id"]: {"Name": container["Name"].lstrip("/")}
            for container in containers
            if network["Name"] in container["NetworkSettings"]["Networks"]
        }
    return containers, networks, volumes


class TransitionSequenceTests(OfflineTests):
    def execute(self, states, failure=None):
        events = []
        snapshots = iter(states)
        def remove(identifier):
            events.append(("container", identifier))
            if failure == "container":
                raise RuntimeError("simulated removal failure")
        result = sequence.teardown(
            snapshot=lambda: next(snapshots), load_evidence=lambda: set(),
            save_evidence=lambda ids: events.append(("evidence", set(ids))),
            remove_container=remove,
            remove_network=lambda identifier: events.append(("network", identifier)))
        return result, events

    def test_default_validator_remains_strict_but_teardown_opts_in_three_times(self):
        state = transition_state()
        with self.assertRaises(ValueError):
            validator.validate_snapshot(*state)
        empty_networks = deepcopy(state[1])
        for network in empty_networks:
            network["Containers"] = {}
        with patch.object(sequence, "validate_snapshot",
                          wraps=validator.validate_snapshot) as checked:
            result, events = self.execute([state, ([], empty_networks, []), ([], [], [])])
        self.assertEqual(checked.call_count, 3)
        self.assertTrue(all(call.kwargs["allow_livy_transition"] is True
                            for call in checked.call_args_list))
        removals = [value for kind, value in events if kind == "container"]
        clients = validator.validate_snapshot(*state, allow_livy_transition=True)[
            "client_container_ids"]
        self.assertEqual(removals[:len(clients)], clients)
        self.assertEqual(set(result["container_ids"]), {c["Id"] for c in state[0]})

    def test_candidate_provenance_on_master_is_not_authorised(self):
        state = transition_state()
        master = next(c for c in state[0]
            if c["Config"]["Labels"]["com.docker.compose.service"] == "spark-master")
        master["Config"]["Labels"]["com.docker.compose.project.config_files"] = (
            validator.TRANSITION_CONFIG)
        with patch.object(sequence, "validate_snapshot",
                          wraps=validator.validate_snapshot):
            with self.assertRaises(ValueError):
                self.execute([state])

    def test_candidate_livy_with_baseline_mounts_is_refused(self):
        state = transition_state()
        livy = next(c for c in state[0]
            if c["Config"]["Labels"]["com.docker.compose.service"] == "spark-livy")
        livy["Mounts"] = [dict(Type="bind", RW=False, Source=source, Destination=destination)
            for source, destination in sorted({validator.DATA_MOUNT} | validator.LIVY_MOUNTS)]
        with self.assertRaises(ValueError):
            self.execute([state])


class DockerBindInspectionTests(OfflineTests):
    def docker(self, records):
        docker = adapter.Docker()
        identifiers = [record["Id"] for record in records]
        def command(*arguments):
            if arguments == ("container", "ls", "--all", "--quiet", "--no-trunc"):
                return "\n".join(identifiers)
            if arguments == ("container", "inspect", *sorted(identifiers)):
                return json.dumps(records)
            raise AssertionError(arguments)
        docker.command = Mock(side_effect=command)
        return docker

    def test_foreign_stopped_container_is_inspected_without_removal(self):
        docker = self.docker([{"Id": "f" * 64, "State": {"Running": False},
            "Mounts": [{"Type": "bind", "Source": "//opt//runtime/"},
                       {"Type": "volume", "Source": "/unrelated-volume"}]}])
        self.assertEqual(docker.bind_sources(), ["/opt/runtime"])
        self.assertEqual(docker.command.call_count, 2)
        self.assertTrue(all("rm" not in call.args for call in docker.command.call_args_list))

    def test_empty_daemon_is_validated_without_inspect(self):
        docker = self.docker([])
        self.assertEqual(docker.bind_sources(), [])
        self.assertEqual(docker.command.call_count, 1)

    def test_invalid_mount_observations_fail_closed(self):
        for mounts in (None, [{"Type": "bind", "Source": "relative"}],
                       [{"Type": "bind", "Source": "/a/../b"}],
                       [{"Type": "unknown", "Source": "/a"}]):
            docker = self.docker([{"Id": "f" * 64, "Mounts": mounts}])
            with self.subTest(mounts=mounts), self.assertRaises(ValueError):
                docker.bind_sources()


class RunnerBindGuardTests(OfflineTests):
    def setUp(self):
        super().setUp()
        runner_fixture.RunnerTests.setUp(self)
        self.docker = Mock()
        self.sources = ["/unrelated"]
        self.docker.bind_sources.return_value = self.sources

    def invoke(self):
        with patch.object(runner, "locked_evidence_directory", return_value=nullcontext(42)), \
             patch.object(runner, "Docker", return_value=self.docker), \
             patch.object(runner, "teardown",
                          return_value={"container_ids": [], "network_ids": []}):
            return runner.run_teardown()

    def test_fresh_bind_guard_precedes_assets_and_final_evidence_clear(self):
        order = Mock()
        order.attach_mock(self.docker, "docker")
        order.attach_mock(self.images, "images")
        order.attach_mock(self.assets, "assets")
        order.attach_mock(self.seed, "seed")
        order.attach_mock(self.clear, "clear")
        self.invoke()
        names = [call[0] for call in order.mock_calls]
        self.assertLess(names.index("images.remove"), names.index("docker.bind_sources"))
        self.assertLess(names.index("docker.bind_sources"),
                        names.index("assets.check_remaining_docker_sources"))
        self.assertLess(names.index("assets.check_remaining_docker_sources"),
                        names.index("assets.remove"))
        self.assertLess(names.index("assets.remove"), names.index("clear"))
        self.assets.check_remaining_docker_sources.assert_called_once_with(self.sources)

    def test_overlap_refusal_preserves_assets_seed_and_retry_evidence(self):
        self.assets.check_remaining_docker_sources.side_effect = ValueError("remaining bind")
        with self.assertRaises(ValueError):
            self.invoke()
        self.assets.remove.assert_not_called()
        self.seed.remove.assert_not_called()
        self.clear.assert_not_called()

    def test_discovery_failure_is_not_reinterpreted_as_empty(self):
        self.docker.bind_sources.side_effect = OSError("inspection unavailable")
        with self.assertRaises(OSError):
            self.invoke()
        self.assets.remove.assert_not_called()
        self.seed.remove.assert_not_called()
        self.clear.assert_not_called()


if __name__ == "__main__":
    unittest.main()
