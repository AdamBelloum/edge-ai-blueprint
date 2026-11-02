"""Transition-only provenance opt-in; default teardown stays strict.

Synthetic snapshots only. No Docker operations or real files are used.
"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

HELPERS = Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark"
sys.path.insert(0, str(HELPERS))
from teardown_validation import (
    DATA_MOUNT, LIVY_ACCESS_CMD, LIVY_MOUNTS, NETWORK, OWNERSHIP,
    PARTICIPANT_IMAGE, PARTICIPANT_MOUNTS, PROJECT, ROOT,
    TRANSITION_CONFIG, TRANSITION_LIVY_MOUNTS, validate_snapshot,
)


def container(service="spark-livy", *, candidate=False):
    labels = {
        **OWNERSHIP,
        "com.docker.compose.service": service,
        "com.docker.compose.project": PROJECT,
        "com.docker.compose.project.config_files": (
            TRANSITION_CONFIG if candidate else ROOT + "/compose.yaml"),
        "com.docker.compose.project.working_dir": ROOT,
        "com.docker.compose.container-number": "1",
        "com.docker.compose.oneoff": "False",
    }
    mounts = {DATA_MOUNT}
    config = {"Labels": labels}
    host = {}
    if service == "spark-livy":
        mounts |= TRANSITION_LIVY_MOUNTS if candidate else LIVY_MOUNTS
    elif service == "spark-livy-access":
        mounts = set(PARTICIPANT_MOUNTS)
        config.update(Image=PARTICIPANT_IMAGE, User="root", Cmd=list(LIVY_ACCESS_CMD))
        host = {
            "Privileged": False, "ReadonlyRootfs": False,
            "CapDrop": ["ALL"], "CapAdd": ["SETUID", "SETGID", "SYS_CHROOT"],
            "NetworkMode": NETWORK, "IpcMode": "private",
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 134217728, "NanoCpus": 250000000,
            "RestartPolicy": {"Name": "no"},
            "PortBindings": {"2222/tcp": [{"HostIp": "10.0.0.20", "HostPort": "2222"}]},
        }
    return {
        "Id": "a" * 64, "Image": "sha256:" + "b" * 64,
        "Name": "/" + PROJECT + "-" + service + "-1",
        "Config": config, "HostConfig": host,
        "Mounts": [{"Type": "bind", "Source": source,
                    "Destination": dest, "RW": False}
                   for source, dest in sorted(mounts)],
        "NetworkSettings": {"Networks": {}},
    }


class TransitionProvenanceTests(unittest.TestCase):
    def validate(self, item, **kwargs):
        return validate_snapshot([item], [], [], **kwargs)

    def test_baseline_livy_remains_valid_by_default(self):
        self.validate(container())

    def test_candidate_livy_is_rejected_by_default(self):
        with self.assertRaises(ValueError):
            self.validate(container(candidate=True))

    def test_exact_candidate_livy_is_valid_with_transition_opt_in(self):
        self.validate(container(candidate=True), allow_livy_transition=True)

    def test_baseline_livy_remains_valid_in_transition_mode(self):
        self.validate(container(), allow_livy_transition=True)

    def test_arbitrary_candidate_filename_is_rejected(self):
        item = container(candidate=True)
        item["Config"]["Labels"]["com.docker.compose.project.config_files"] = ROOT + "/other.yaml"
        with self.assertRaises(ValueError):
            self.validate(item, allow_livy_transition=True)

    def test_candidate_livy_cannot_use_baseline_mounts(self):
        item = container(candidate=True)
        item["Mounts"] = deepcopy(container()["Mounts"])
        with self.assertRaises(ValueError):
            self.validate(item, allow_livy_transition=True)

    def test_baseline_livy_cannot_use_candidate_mounts(self):
        item = container()
        item["Mounts"] = deepcopy(container(candidate=True)["Mounts"])
        with self.assertRaises(ValueError):
            self.validate(item, allow_livy_transition=True)

    def test_transition_cannot_replace_shared_or_direct_provenance(self):
        for service in ("spark-master", "spark-worker-1", "spark-client"):
            with self.subTest(service=service), self.assertRaises(ValueError):
                self.validate(container(service, candidate=True), allow_livy_transition=True)

    def test_candidate_gateway_requires_opt_in_and_preserves_access_checks(self):
        item = container("spark-livy-access", candidate=True)
        with self.assertRaises(ValueError):
            self.validate(item)
        self.validate(item, allow_livy_transition=True)
        item["HostConfig"]["PortBindings"]["2222/tcp"][0]["HostIp"] = "0.0.0.0"
        with self.assertRaises(ValueError):
            self.validate(item, allow_livy_transition=True)

    def test_writable_candidate_mount_is_rejected(self):
        item = container(candidate=True)
        item["Mounts"][0]["RW"] = True
        with self.assertRaises(ValueError):
            self.validate(item, allow_livy_transition=True)

    def test_non_boolean_opt_in_is_rejected(self):
        with self.assertRaises(ValueError):
            self.validate(container(), allow_livy_transition="true")


if __name__ == "__main__":
    unittest.main()
