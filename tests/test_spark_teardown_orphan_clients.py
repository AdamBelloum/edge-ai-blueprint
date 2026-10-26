"""Offline orphan-client tests: no Docker, Ansible or live filesystem."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_spark_teardown_validation import snapshot, validator
from test_spark_teardown_sequence import sequence
from test_spark_teardown_docker import adapter


def client(direct=True, attached=True):
    token = "b" * 32 if direct else "c" * 32
    key = ("org.digitafrica.direct-run-id" if direct
           else "org.digitafrica.livy-client-run-id")
    name_prefix, directory_prefix, _ = validator.CLIENT_LABELS[key]
    run_dir = validator.ROOT + "/" + directory_prefix + "abcd1234"
    mounts = [
        {"Type": "bind", "Source": run_dir, "Destination": "/work", "RW": False},
        {"Type": "bind", "Source": run_dir + "/outputs",
         "Destination": "/work/outputs", "RW": True},
        {"Type": "bind", "Source": validator.DATA_MOUNT[0],
         "Destination": "/work/data", "RW": False},
    ]
    if direct:
        mounts.append({"Type": "bind", "Source": validator.DATA_MOUNT[0],
                       "Destination": validator.DATA_MOUNT[1], "RW": False})
    return {
        "Id": ("e" if direct else "f") * 64,
        "Name": "/" + name_prefix + token,
        "Image": "sha256:" + "d" * 64,
        "Config": {
            "Image": validator.CLIENT_IMAGE, "User": "185:185",
            "Entrypoint": ["/opt/spark/bin/spark-submit"] if direct else ["python3"],
            "Labels": {**validator.OWNERSHIP, key: token},
        },
        "HostConfig": {
            "Privileged": False, "ReadonlyRootfs": True, "PortBindings": {},
            "CapAdd": None, "CapDrop": ["ALL"], "NetworkMode": validator.NETWORK,
            "PidMode": "", "IpcMode": "private", "Devices": [], "DeviceRequests": [],
            "SecurityOpt": ["no-new-privileges:true"], "RestartPolicy": {"Name": "no"},
        },
        "Mounts": mounts,
        "State": {"Running": False},
        "NetworkSettings": {"Networks": {
            validator.NETWORK: {"NetworkID": "a" * 64},
        } if attached else {}},
    }


def mixed_snapshot(legacy=False):
    containers, networks, volumes = snapshot(legacy=legacy)
    containers.extend([client(True), client(False)])
    networks[0]["Containers"] = {c["Id"]: {} for c in containers}
    return containers, networks, volumes


class ClientValidationTests(unittest.TestCase):
    def test_running_and_stopped_attached_and_detached_clients(self):
        for direct in (True, False):
            for attached in (True, False):
                for running in (True, False):
                    with self.subTest(direct=direct, attached=attached, running=running):
                        item = client(direct, attached)
                        item["State"]["Running"] = running
                        validator.validate_client(item)

    def test_mixed_clients_are_owned_endpoints_including_legacy_network(self):
        for legacy in (True, False):
            current = mixed_snapshot(legacy)
            plan = validator.validate_snapshot(*current)
            self.assertEqual(plan["client_container_ids"], ["e" * 64, "f" * 64])
            self.assertEqual(plan["container_ids"], sorted(c["Id"] for c in current[0]))

    def test_detached_orphan_can_be_removed_without_services_or_network(self):
        item = client(attached=False)
        plan = validator.validate_snapshot([item], [], [])
        self.assertEqual(plan["client_container_ids"], [item["Id"]])

    def test_bad_names_tokens_ownership_and_compose_labels_are_refused(self):
        for mutation in ("name", "token", "missing_owner", "conflicting_owner",
                         "two_run_labels", "compose"):
            with self.subTest(mutation=mutation):
                item = client()
                labels = item["Config"]["Labels"]
                if mutation == "name":
                    item["Name"] = "/unrelated"
                elif mutation == "token":
                    labels["org.digitafrica.direct-run-id"] = "../unsafe"
                elif mutation == "missing_owner":
                    del labels["org.digitafrica.managed-by"]
                elif mutation == "conflicting_owner":
                    labels["org.digitafrica.managed-by"] = "other"
                elif mutation == "two_run_labels":
                    labels["org.digitafrica.livy-client-run-id"] = "c" * 32
                else:
                    labels["com.docker.compose.project"] = validator.PROJECT
                with self.assertRaises(ValueError):
                    validator.validate_client(item)

    def test_bad_image_user_and_entrypoint_are_refused(self):
        for key, value in (("Image", "apache/spark:latest"), ("User", "0:0"),
                           ("Entrypoint", ["sh"])):
            item = client()
            item["Config"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validator.validate_client(item)

    def test_unsafe_host_configuration_is_refused(self):
        for key, value in (
            ("Privileged", True), ("ReadonlyRootfs", False),
            ("PortBindings", {"80/tcp": [{}]}), ("CapAdd", ["SYS_ADMIN"]),
            ("CapDrop", []), ("NetworkMode", "host"), ("PidMode", "host"),
            ("IpcMode", "host"), ("Devices", [{}]), ("DeviceRequests", [{}]),
            ("SecurityOpt", []), ("RestartPolicy", {"Name": "always"}),
        ):
            item = client()
            item["HostConfig"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validator.validate_client(item)

    def test_missing_extra_writable_and_out_of_scope_mounts_are_refused(self):
        for mutation in ("missing", "extra", "writable", "traversal", "wrong_outputs"):
            item = client()
            mounts = item["Mounts"]
            if mutation == "missing":
                mounts.pop()
            elif mutation == "extra":
                mounts.append({"Type": "bind", "Source": "/var/run/docker.sock",
                               "Destination": "/var/run/docker.sock", "RW": True})
            elif mutation == "writable":
                mounts[0]["RW"] = True
            elif mutation == "traversal":
                mounts[0]["Source"] = validator.ROOT + "/direct-run-../unrelated"
            else:
                mounts[1]["Source"] = "/unrelated/outputs"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validator.validate_client(item)

    def test_foreign_network_and_mismatched_network_id_are_refused(self):
        item = client()
        item["NetworkSettings"]["Networks"]["unrelated"] = {}
        with self.assertRaises(ValueError):
            validator.validate_client(item)
        current = mixed_snapshot()
        current[0][-1]["NetworkSettings"]["Networks"][validator.NETWORK]["NetworkID"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            validator.validate_snapshot(*current)


class OrphanDiscoveryTests(unittest.TestCase):
    def test_discovery_unions_all_labels_and_deduplicates_full_ids(self):
        a, b, c = "a" * 64, "b" * 64, "c" * 64
        outputs = [a, b + "\n" + a, c, "", "",
                   json.dumps([{"Id": identifier} for identifier in (a, b, c)])]
        run = Mock(side_effect=[SimpleNamespace(stdout=value) for value in outputs])
        docker = adapter.Docker(run=run)
        records, networks, volumes = docker.snapshot()
        self.assertEqual([r["Id"] for r in records], [a, b, c])
        self.assertEqual((networks, volumes), ([], []))
        self.assertEqual(run.call_args_list[-1].args[0],
                         adapter.PREFIX + ["container", "inspect", a, b, c])
        for call, resource_filter in zip(run.call_args_list, adapter.CONTAINER_FILTERS):
            self.assertEqual(call.args[0], adapter.PREFIX + [
                "container", "ls", "--all", "--quiet", "--no-trunc",
                "--filter", resource_filter])

    def test_bad_discovered_client_id_never_reaches_inspection(self):
        run = Mock(side_effect=[SimpleNamespace(stdout=""), SimpleNamespace(stdout="--force")])
        with self.assertRaises(ValueError):
            adapter.Docker(run=run).snapshot()
        self.assertEqual(run.call_count, 2)


class OrphanSequenceTests(unittest.TestCase):
    def execute(self, states, fail_id=None):
        iterator = iter(states)
        self.events = []

        def remove(identifier):
            self.events.append(("container", identifier))
            if identifier == fail_id:
                raise RuntimeError("client removal failed")

        return sequence.teardown(
            snapshot=lambda: next(iterator), load_evidence=lambda: set(),
            save_evidence=lambda ids: self.events.append(("evidence", set(ids))),
            remove_container=remove,
            remove_network=lambda identifier: self.events.append(("network", identifier)),
        )

    def test_clients_are_removed_before_compose_services_and_network(self):
        initial = mixed_snapshot(legacy=True)
        network = deepcopy(initial[1])
        network[0]["Containers"] = {}
        result = self.execute([initial, ([], network, []), ([], [], [])])
        self.assertEqual(self.events[0], ("evidence", {"a" * 64}))
        self.assertEqual(self.events[1:3], [("container", "e" * 64), ("container", "f" * 64)])
        self.assertEqual(self.events[-2:], [("network", "a" * 64), ("evidence", set())])
        self.assertEqual(result["container_ids"], sorted(c["Id"] for c in initial[0]))

    def test_client_failure_stops_before_compose_and_preserves_evidence(self):
        with self.assertRaisesRegex(RuntimeError, "client removal failed"):
            self.execute([mixed_snapshot(legacy=True)], fail_id="e" * 64)
        self.assertEqual(self.events, [("evidence", {"a" * 64}), ("container", "e" * 64)])

    def test_bad_client_or_foreign_endpoint_prevents_every_removal(self):
        for mutation in ("client", "endpoint"):
            initial = mixed_snapshot()
            if mutation == "client":
                initial[0][-1]["Name"] = "/unrelated"
            else:
                initial[1][0]["Containers"]["9" * 64] = {}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.execute([initial])
            self.assertEqual(self.events, [])

    def test_detached_orphan_cleanup_is_idempotent(self):
        item = client(attached=False)
        result = self.execute([([item], [], []), ([], [], []), ([], [], [])])
        self.assertEqual(result["container_ids"], [item["Id"]])
        result = self.execute([([], [], [])] * 3)
        self.assertEqual(result, {"container_ids": [], "network_ids": []})

    def test_remaining_client_prevents_network_removal_and_completion(self):
        initial = mixed_snapshot()
        leftover = client(attached=False)
        with self.assertRaisesRegex(ValueError, "remain or appeared"):
            self.execute([initial, ([leftover], [], [])])
        self.assertFalse(any(kind == "network" for kind, _ in self.events))
        self.assertEqual(sum(kind == "evidence" for kind, _ in self.events), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
