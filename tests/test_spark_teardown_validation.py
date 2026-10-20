#!/usr/bin/env python3
"""Offline Spark teardown ownership tests; no Docker or deployment access."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / (
    "scripts/workshops/big-data/spark/teardown_validation.py"
)
spec = importlib.util.spec_from_file_location("teardown_validation", MODULE)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def snapshot(legacy=False, livy=True, second_worker=False):
    services = ["spark-master", "spark-worker-1"]
    if second_worker:
        services.append("spark-worker-2")
    if livy:
        services.append("spark-livy")

    network_id = "a" * 64
    containers = []
    for index, service in enumerate(services, 1):
        identifier = f"{index:064x}"
        mounts = {validator.DATA_MOUNT}
        if service == "spark-livy":
            mounts |= validator.LIVY_MOUNTS
        containers.append({
            "Id": identifier,
            "Name": f"/{validator.PROJECT}-{service}-1",
            "Config": {"Labels": {
                **validator.OWNERSHIP,
                "com.docker.compose.project": validator.PROJECT,
                "com.docker.compose.service": service,
                "com.docker.compose.project.config_files":
                    validator.ROOT + "/compose.yaml",
                "com.docker.compose.project.working_dir": validator.ROOT,
                "com.docker.compose.container-number": "1",
                "com.docker.compose.oneoff": "False",
            }},
            "Mounts": [
                {
                    "Type": "bind", "RW": False,
                    "Source": source, "Destination": destination,
                }
                for source, destination in sorted(mounts)
            ],
            "NetworkSettings": {"Networks": {
                validator.NETWORK: {"NetworkID": network_id},
            }},
        })

    labels = {
        "com.docker.compose.project": validator.PROJECT,
        "com.docker.compose.network": "spark-private",
    }
    if not legacy:
        labels.update(validator.OWNERSHIP)
    network = {
        "Id": network_id,
        "Name": validator.NETWORK,
        "Driver": "bridge",
        "Internal": True,
        "Labels": labels,
        "Containers": {c["Id"]: {} for c in containers},
    }
    return containers, [network], []


class SparkTeardownValidationTests(unittest.TestCase):
    def test_supported_runtime_variants(self):
        for legacy in (False, True):
            for livy in (False, True):
                for second in (False, True):
                    with self.subTest(
                        legacy=legacy, livy=livy, second_worker=second
                    ):
                        containers, networks, volumes = snapshot(
                            legacy, livy, second
                        )
                        plan = validator.validate_snapshot(
                            containers, networks, volumes
                        )
                        self.assertEqual(
                            plan["container_ids"],
                            sorted(c["Id"] for c in containers),
                        )
                        self.assertEqual(
                            plan["legacy_network_ids"],
                            [networks[0]["Id"]] if legacy else [],
                        )

    def test_already_clean_snapshot(self):
        plan = validator.validate_snapshot([], [], [])
        self.assertEqual(plan["container_ids"], [])
        self.assertEqual(plan["network_ids"], [])

    def test_empty_labelled_network_is_allowed(self):
        _, networks, _ = snapshot()
        networks[0]["Containers"] = {}
        plan = validator.validate_snapshot([], networks, [])
        self.assertEqual(plan["network_ids"], [networks[0]["Id"]])

    def test_empty_legacy_network_is_refused(self):
        _, networks, _ = snapshot(legacy=True)
        networks[0]["Containers"] = {}
        with self.assertRaisesRegex(ValueError, "durable ownership evidence"):
            validator.validate_snapshot([], networks, [])

    def test_foreign_endpoint_is_refused(self):
        containers, networks, volumes = snapshot()
        networks[0]["Containers"]["f" * 64] = {}
        with self.assertRaisesRegex(ValueError, "Foreign"):
            validator.validate_snapshot(containers, networks, volumes)

    def test_project_volume_is_refused(self):
        containers, networks, _ = snapshot()
        with self.assertRaisesRegex(ValueError, "volumes"):
            validator.validate_snapshot(
                containers, networks, ["unexpected-volume"]
            )

    def test_missing_or_conflicting_container_ownership(self):
        for value in (None, "administrator"):
            with self.subTest(value=value):
                containers, networks, volumes = snapshot()
                labels = containers[0]["Config"]["Labels"]
                key = "org.digitafrica.managed-by"
                if value is None:
                    del labels[key]
                else:
                    labels[key] = value
                with self.assertRaisesRegex(ValueError, "ownership"):
                    validator.validate_snapshot(containers, networks, volumes)

    def test_unexpected_service_is_refused(self):
        containers, networks, volumes = snapshot()
        containers[0]["Config"]["Labels"][
            "com.docker.compose.service"
        ] = "unrelated-service"
        with self.assertRaisesRegex(ValueError, "service"):
            validator.validate_snapshot(containers, networks, volumes)

    def test_wrong_compose_path_is_refused(self):
        containers, networks, volumes = snapshot()
        containers[0]["Config"]["Labels"][
            "com.docker.compose.project.config_files"
        ] = "/tmp/compose.yaml"
        with self.assertRaisesRegex(ValueError, "provenance"):
            validator.validate_snapshot(containers, networks, volumes)

    def test_unsafe_mounts_are_refused(self):
        for field, value in (
            ("RW", True),
            ("Type", "volume"),
            ("Source", "/unrelated/data"),
        ):
            with self.subTest(field=field):
                containers, networks, volumes = snapshot()
                containers[0]["Mounts"][0][field] = value
                with self.assertRaises(ValueError):
                    validator.validate_snapshot(containers, networks, volumes)

    def test_partial_or_conflicting_network_labels_are_refused(self):
        for value in ("organiser", "administrator"):
            with self.subTest(value=value):
                containers, networks, volumes = snapshot(legacy=True)
                networks[0]["Labels"][
                    "org.digitafrica.managed-by"
                ] = value
                with self.assertRaisesRegex(ValueError, "ownership"):
                    validator.validate_snapshot(containers, networks, volumes)

    def test_network_identity_mismatch_is_refused(self):
        containers, networks, volumes = snapshot()
        containers[0]["NetworkSettings"]["Networks"][
            validator.NETWORK
        ]["NetworkID"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            validator.validate_snapshot(containers, networks, volumes)

    def test_missing_discovered_network_is_refused(self):
        containers, _, volumes = snapshot()
        with self.assertRaisesRegex(ValueError, "not discovered"):
            validator.validate_snapshot(containers, [], volumes)

    def test_unexpected_network_attachment_is_refused(self):
        containers, networks, volumes = snapshot()
        containers[0]["NetworkSettings"]["Networks"]["unrelated"] = {}
        with self.assertRaisesRegex(ValueError, "unexpected network"):
            validator.validate_snapshot(containers, networks, volumes)



class LegacyNetworkRetryTests(unittest.TestCase):
    def test_matching_evidence_allows_empty_legacy_network(self):
        _, networks, _ = snapshot(legacy=True)
        networks[0]["Containers"] = {}
        identifier = networks[0]["Id"]
        plan = validator.validate_snapshot(
            [], networks, [],
            verified_legacy_network_ids=[identifier],
        )
        self.assertEqual(plan["network_ids"], [identifier])
        self.assertEqual(plan["legacy_network_ids"], [identifier])

    def test_wrong_id_does_not_authorise_empty_network(self):
        _, networks, _ = snapshot(legacy=True)
        networks[0]["Containers"] = {}
        with self.assertRaisesRegex(ValueError, "durable ownership evidence"):
            validator.validate_snapshot(
                [], networks, [],
                verified_legacy_network_ids=["b" * 64],
            )

    def test_matching_evidence_does_not_allow_foreign_endpoints(self):
        _, networks, _ = snapshot(legacy=True)
        networks[0]["Containers"] = {"f" * 64: {}}
        with self.assertRaisesRegex(ValueError, "Foreign"):
            validator.validate_snapshot(
                [], networks, [],
                verified_legacy_network_ids=[networks[0]["Id"]],
            )

    def test_matching_evidence_does_not_bypass_identity_or_ownership(self):
        for mutation in ("name", "privacy", "ownership"):
            with self.subTest(mutation=mutation):
                _, networks, _ = snapshot(legacy=True)
                network = networks[0]
                network["Containers"] = {}
                if mutation == "name":
                    network["Name"] = "unrelated-network"
                elif mutation == "privacy":
                    network["Internal"] = False
                else:
                    network["Labels"][
                        "org.digitafrica.managed-by"
                    ] = "administrator"

                with self.assertRaises(ValueError):
                    validator.validate_snapshot(
                        [], networks, [],
                        verified_legacy_network_ids=[network["Id"]],
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
