"""Offline participant-direct service/network reset integration tests."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from test_spark_teardown_validation import validator as v, snapshot

old_path = list(sys.path)
try:
    sys.path.insert(0, str(
        Path(__file__).resolve().parents[1]
        / "scripts/workshops/big-data/spark"
    ))
    from teardown_sequence import teardown
finally:
    sys.path[:] = old_path

CID, AID = "4" * 64, "b" * 64

def participant(legacy=False):
    containers, networks, volumes = snapshot(legacy=legacy)
    client = deepcopy(containers[0])
    client.update(
        Id=CID, Name="/" + v.PROJECT + "-spark-client-1",
        Image="sha256:" + "f" * 64,
    )
    client["Config"].update(
        Image=v.PARTICIPANT_IMAGE, User="root",
        Cmd=list(v.PARTICIPANT_CMD),
    )
    client["Config"]["Labels"]["com.docker.compose.service"] = "spark-client"
    client["Mounts"] = [
        dict(Type="bind", RW=False, Source=s, Destination=d)
        for s, d in sorted({v.DATA_MOUNT} | v.PARTICIPANT_MOUNTS)
    ]
    client["HostConfig"] = {
        "Privileged": False, "ReadonlyRootfs": False,
        "CapDrop": ["ALL"], "CapAdd": ["SETUID", "SETGID", "SYS_CHROOT"],
        "NetworkMode": v.NETWORK, "PidMode": "", "IpcMode": "private",
        "Devices": [], "DeviceRequests": [],
        "SecurityOpt": ["no-new-privileges:true"], "Memory": 1073741824,
        "RestartPolicy": {"Name": "no"},
        "PortBindings": {
            "2222/tcp": [{"HostIp": "145.100.135.172", "HostPort": "2222"}]
        },
    }
    client["NetworkSettings"]["Networks"][v.ACCESS_NETWORK] = {
        "NetworkID": AID,
    }
    containers.append(client)
    networks[0]["Containers"][CID] = {}
    networks.append({
        "Id": AID, "Name": v.ACCESS_NETWORK, "Driver": "bridge",
        "Internal": False,
        "Labels": {
            **v.OWNERSHIP,
            "com.docker.compose.project": v.PROJECT,
            "com.docker.compose.network": "spark-access",
        },
        "Containers": {CID: {}},
    })
    return containers, networks, volumes

class Resources:
    def __init__(self, legacy=False):
        self.c, self.n, self.volumes = participant(legacy)
        self.evidence, self.events, self.fail = set(), [], None

    def snapshot(self):
        return deepcopy((self.c, self.n, self.volumes))

    def save(self, evidence):
        self.evidence = set(evidence)
        self.events.append(("evidence", set(evidence)))

    def remove_container(self, identifier):
        self.events.append(("container", identifier))
        self.c = [c for c in self.c if c["Id"] != identifier]
        for network in self.n:
            network["Containers"].pop(identifier, None)

    def remove_network(self, identifier):
        self.events.append(("network", identifier))
        if identifier == self.fail:
            raise RuntimeError("injected network failure")
        self.n = [n for n in self.n if n["Id"] != identifier]

    def reset(self):
        return teardown(
            snapshot=self.snapshot,
            load_evidence=lambda: set(self.evidence),
            save_evidence=self.save,
            remove_container=self.remove_container,
            remove_network=self.remove_network,
        )

class ParticipantValidationTests(unittest.TestCase):
    def test_assessed_client_and_two_networks(self):
        for prefix in ("", "CAP_"):
            state = participant()
            state[0][-1]["HostConfig"]["CapAdd"] = [
                prefix + cap for cap in ["SETUID", "SETGID", "SYS_CHROOT"]
            ]
            plan = v.validate_snapshot(*state)
            self.assertEqual(plan["client_container_ids"], [CID])
            self.assertEqual(plan["network_ids"], [AID, "a" * 64])

    def test_unsafe_service_and_mounts_refused(self):
        changes = [
            lambda c: c["Config"].update(Image="other/image:latest"),
            lambda c: c["Config"].update(Cmd=["sh"]),
            lambda c: c["HostConfig"].update(Privileged=True),
            lambda c: c["HostConfig"]["CapAdd"].append("SYS_ADMIN"),
            lambda c: c["HostConfig"]["PortBindings"]["2222/tcp"][0].update(HostIp="0.0.0.0"),
            lambda c: c["Mounts"][0].update(RW=True),
            lambda c: c["Mounts"].append(dict(Type="bind", RW=False, Source="/var/run/docker.sock", Destination="/socket")),
            lambda c: c["Config"]["Labels"].update({"org.digitafrica.managed-by": "other"}),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                state = participant()
                change(state[0][-1])
                with self.assertRaises(ValueError):
                    v.validate_snapshot(*state)

    def test_access_ownership_and_endpoints_not_bypassed_by_evidence(self):
        changes = [
            lambda n: n["Labels"].pop("org.digitafrica.workshop"),
            lambda n: n.update(Internal=True),
            lambda n: n["Labels"].update({"com.docker.compose.network": "other"}),
            lambda n: n["Containers"].update({"f" * 64: {}}),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                state = participant()
                change(state[1][-1])
                with self.assertRaises(ValueError):
                    v.validate_snapshot(
                        *state, verified_legacy_network_ids=[AID]
                    )

    def test_other_services_cannot_use_access(self):
        state = participant()
        state[0][0]["NetworkSettings"]["Networks"][v.ACCESS_NETWORK] = {
            "NetworkID": AID,
        }
        state[1][-1]["Containers"][state[0][0]["Id"]] = {}
        with self.assertRaises(ValueError):
            v.validate_snapshot(*state)

    def test_missing_and_duplicate_networks_refused(self):
        for kind in ("missing", "name", "id"):
            with self.subTest(kind=kind):
                containers, networks, volumes = participant()
                if kind == "missing":
                    networks.pop()
                elif kind == "name":
                    networks[0]["Name"] = networks[1]["Name"]
                else:
                    networks[1]["Id"] = networks[0]["Id"]
                with self.assertRaises(ValueError):
                    v.validate_snapshot(containers, networks, volumes)

    def test_empty_owned_access_network_retryable(self):
        _, networks, _ = participant()
        networks[-1]["Containers"] = {}
        plan = v.validate_snapshot([], [networks[-1]], [])
        self.assertEqual(plan["network_ids"], [AID])

class ParticipantSequenceTests(unittest.TestCase):
    def test_client_first_then_access_before_private_and_idempotence(self):
        for legacy in (False, True):
            state = Resources(legacy)
            state.reset()
            self.assertEqual(
                [e[1] for e in state.events if e[0] == "container"][0], CID
            )
            self.assertEqual(
                [e[1] for e in state.events if e[0] == "network"],
                [AID, "a" * 64],
            )
            self.assertEqual(state.snapshot(), ([], [], []))
            self.assertEqual(state.evidence, set())
            self.assertEqual(
                state.reset(), {"container_ids": [], "network_ids": []}
            )

    def test_partial_failure_preserves_evidence_and_retry_completes(self):
        state = Resources(True)
        state.fail = "a" * 64
        with self.assertRaises(RuntimeError):
            state.reset()
        self.assertEqual(state.c, [])
        self.assertEqual([n["Id"] for n in state.n], ["a" * 64])
        self.assertEqual(state.evidence, {"a" * 64})
        state.fail = None
        state.reset()
        self.assertEqual(state.snapshot(), ([], [], []))
        self.assertEqual(state.evidence, set())

    def test_foreign_access_endpoint_prevents_every_removal(self):
        state = Resources()
        state.n[-1]["Containers"]["f" * 64] = {}
        with self.assertRaises(ValueError):
            state.reset()
        self.assertEqual(state.events, [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
