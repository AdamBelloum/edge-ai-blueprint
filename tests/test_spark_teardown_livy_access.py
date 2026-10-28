"""Offline ownership, resource and sequencing tests for Livy access teardown."""
from copy import deepcopy
import unittest

from test_spark_teardown_participant_runtime import participant, Resources, CID, AID
from test_spark_teardown_validation import validator as v
import test_spark_livy_access_template as templates


def livy_access(legacy=False):
    containers, networks, volumes = participant(legacy)
    gateway = containers[-1]
    gateway["Name"] = "/" + v.PROJECT + "-spark-livy-access-1"
    gateway["Config"]["Labels"]["com.docker.compose.service"] = "spark-livy-access"
    gateway["Config"]["Cmd"] = list(v.LIVY_ACCESS_CMD)
    gateway["HostConfig"].update(Memory=134217728, NanoCpus=250000000)
    gateway["Mounts"] = [
        dict(Type="bind", RW=False, Source=source, Destination=destination)
        for source, destination in sorted(v.PARTICIPANT_MOUNTS)
    ]
    return containers, networks, volumes


class LivyAccessValidationTests(unittest.TestCase):
    def test_assessed_gateway_is_a_client_removed_before_networks(self):
        for prefix in ("", "CAP_"):
            state = livy_access()
            state[0][-1]["HostConfig"]["CapAdd"] = [
                prefix + cap for cap in ["SETUID", "SETGID", "SYS_CHROOT"]
            ]
            plan = v.validate_snapshot(*state)
            self.assertEqual(plan["client_container_ids"], [CID])
            self.assertEqual(plan["network_ids"], [AID, "a" * 64])

    def test_validation_command_matches_rendered_gateway(self):
        templates.LivyAccessTemplateTests.setUpClass()
        fixture = templates.LivyAccessTemplateTests()
        self.assertEqual(fixture.gateway()["command"], v.LIVY_ACCESS_CMD)

    def test_weakened_forwarding_or_session_options_are_refused(self):
        changes = {
            "AllowTcpForwarding=local": "AllowTcpForwarding=yes",
            "AllowStreamLocalForwarding=no": "AllowStreamLocalForwarding=yes",
            "PermitOpen=spark-livy:8998": "PermitOpen=any",
            "PermitListen=none": "PermitListen=any",
            "MaxSessions=0": "MaxSessions=1",
            "AllowAgentForwarding=no": "AllowAgentForwarding=yes",
        }
        for old, new in changes.items():
            with self.subTest(option=old):
                state = livy_access()
                command = state[0][-1]["Config"]["Cmd"]
                command[command.index(old)] = new
                with self.assertRaises(ValueError):
                    v.validate_snapshot(*state)
        state = livy_access()
        state[0][-1]["Config"]["Cmd"].extend(["-o", "PermitOpen=any"])
        with self.assertRaises(ValueError):
            v.validate_snapshot(*state)

    def test_wrong_image_user_limits_and_unsafe_host_configuration_are_refused(self):
        changes = [
            lambda c: c["Config"].update(Image="other/image:latest"),
            lambda c: c["Config"].update(User="185:0"),
            lambda c: c["HostConfig"].update(Memory=1073741824),
            lambda c: c["HostConfig"].update(NanoCpus=1000000000),
            lambda c: c["HostConfig"].update(Privileged=True),
            lambda c: c["HostConfig"]["CapAdd"].append("SYS_ADMIN"),
            lambda c: c["HostConfig"].update(NetworkMode="host"),
            lambda c: c["HostConfig"]["PortBindings"]["2222/tcp"][0].update(HostIp="0.0.0.0"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                state = livy_access()
                change(state[0][-1])
                with self.assertRaises(ValueError):
                    v.validate_snapshot(*state)

    def test_dataset_extra_private_key_socket_and_writable_mounts_are_refused(self):
        extras = [v.DATA_MOUNT,
                  (v.ROOT + "/client-access/login_key", "/private-key"),
                  ("/var/run/docker.sock", "/socket")]
        for source, destination in extras:
            with self.subTest(source=source):
                state = livy_access()
                state[0][-1]["Mounts"].append(dict(
                    Type="bind", RW=False, Source=source, Destination=destination))
                with self.assertRaises(ValueError):
                    v.validate_snapshot(*state)
        state = livy_access()
        state[0][-1]["Mounts"][0]["RW"] = True
        with self.assertRaises(ValueError):
            v.validate_snapshot(*state)

    def test_gateway_provenance_and_duplicates_are_not_bypassed(self):
        for kind in ("owner", "name", "compose-path", "duplicate"):
            with self.subTest(kind=kind):
                state = livy_access()
                gateway = state[0][-1]
                if kind == "owner":
                    gateway["Config"]["Labels"]["org.digitafrica.managed-by"] = "other"
                elif kind == "name":
                    gateway["Name"] = "/other"
                elif kind == "compose-path":
                    gateway["Config"]["Labels"]["com.docker.compose.project.config_files"] = "/tmp/compose.yaml"
                else:
                    duplicate = deepcopy(gateway)
                    duplicate["Id"] = "5" * 64
                    state[0].append(duplicate)
                with self.assertRaises(ValueError):
                    v.validate_snapshot(*state)

    def test_foreign_access_endpoints_and_shared_service_access_are_refused(self):
        state = livy_access()
        state[1][-1]["Containers"]["f" * 64] = {}
        with self.assertRaises(ValueError):
            v.validate_snapshot(*state, verified_legacy_network_ids=[AID])
        state = livy_access()
        shared = state[0][0]
        shared["NetworkSettings"]["Networks"][v.ACCESS_NETWORK] = {"NetworkID": AID}
        state[1][-1]["Containers"][shared["Id"]] = {}
        with self.assertRaises(ValueError):
            v.validate_snapshot(*state)


class LivyAccessSequenceTests(unittest.TestCase):
    def resources(self, legacy=False):
        state = Resources(legacy)
        state.c, state.n, state.volumes = livy_access(legacy)
        return state

    def test_gateway_first_access_before_private_and_idempotent_retry(self):
        for legacy in (False, True):
            state = self.resources(legacy)
            state.reset()
            containers = [event[1] for event in state.events if event[0] == "container"]
            networks = [event[1] for event in state.events if event[0] == "network"]
            self.assertEqual(containers[0], CID)
            self.assertEqual(networks, [AID, "a" * 64])
            self.assertEqual(state.snapshot(), ([], [], []))
            self.assertEqual(state.reset(), {"container_ids": [], "network_ids": []})

    def test_partial_failure_preserves_legacy_evidence_and_can_resume(self):
        state = self.resources(True)
        state.fail = "a" * 64
        with self.assertRaises(RuntimeError):
            state.reset()
        self.assertEqual(state.c, [])
        self.assertEqual(state.evidence, {"a" * 64})
        state.fail = None
        state.reset()
        self.assertEqual(state.snapshot(), ([], [], []))
        self.assertEqual(state.evidence, set())


if __name__ == "__main__":
    unittest.main()
