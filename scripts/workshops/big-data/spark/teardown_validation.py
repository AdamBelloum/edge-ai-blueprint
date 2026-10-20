"""Validate a Docker snapshot before scoped Spark teardown.

No Docker commands or filesystem mutations occur here.
Legacy-network evidence must be persisted before container removal.
"""

PROJECT = "digitafrica-spark"
ROOT = "/opt/digitafrica/big-data/runtime/spark"
NETWORK = PROJECT + "_spark-private"
OWNERSHIP = {
    "org.digitafrica.workshop": "big-data",
    "org.digitafrica.module": "spark",
    "org.digitafrica.managed-by": "organiser",
}
SERVICES = {
    "spark-master", "spark-worker-1", "spark-worker-2", "spark-livy",
}
DATA_MOUNT = (
    "/opt/digitafrica/big-data/spark/data", "/opt/spark-data/data",
)
LIVY_MOUNTS = {
    (ROOT + "/livy.conf", "/opt/livy/conf/livy.conf"),
    (ROOT + "/livy-spark-defaults.conf",
     "/opt/spark/conf/spark-defaults.conf"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_snapshot(containers, networks, volumes, *,
                      verified_legacy_network_ids=()):
    """Return verified IDs; reject ambiguous ownership before deletion.

    verified_legacy_network_ids must come from protected, host-local
    evidence written after successful validation, not from user input.
    Current network identity and endpoint checks still apply on retry.
    """
    require(not volumes, "Unexpected project-labelled volumes; teardown refused.")
    require(len(networks) <= 1, "Unexpected project networks.")
    ids = set()
    services = set()

    for container in containers:
        identifier = container["Id"]
        require(identifier not in ids, "Duplicate container ID.")
        ids.add(identifier)
        labels = container["Config"].get("Labels") or {}
        service = labels.get("com.docker.compose.service")
        require(service in SERVICES, "Unexpected Spark project service.")
        require(service not in services, "Duplicate Spark service.")
        services.add(service)

        expected = {
            **OWNERSHIP,
            "com.docker.compose.project": PROJECT,
            "com.docker.compose.project.config_files": ROOT + "/compose.yaml",
            "com.docker.compose.project.working_dir": ROOT,
            "com.docker.compose.container-number": "1",
            "com.docker.compose.oneoff": "False",
        }
        require(
            all(labels.get(key) == value for key, value in expected.items()),
            "Container ownership or Compose provenance mismatch.",
        )
        require(
            container["Name"] == f"/{PROJECT}-{service}-1",
            "Unexpected container name.",
        )

        mounts = container.get("Mounts", [])
        expected_mounts = {DATA_MOUNT}
        if service == "spark-livy":
            expected_mounts |= LIVY_MOUNTS
        actual_mounts = set()
        for mount in mounts:
            require(
                mount.get("Type") == "bind" and mount.get("RW") is False,
                "Unexpected writable or non-bind mount.",
            )
            actual_mounts.add((mount["Source"], mount["Destination"]))
        require(
            actual_mounts == expected_mounts
            and len(mounts) == len(expected_mounts),
            "Unexpected or missing container mounts.",
        )

        attached = container["NetworkSettings"].get("Networks") or {}
        require(
            set(attached) <= {NETWORK},
            "Container is attached to an unexpected network.",
        )

    legacy_ids = []
    for network in networks:
        labels = network.get("Labels") or {}
        require(
            network["Name"] == NETWORK
            and network["Driver"] == "bridge"
            and network["Internal"] is True
            and labels.get("com.docker.compose.project") == PROJECT
            and labels.get("com.docker.compose.network") == "spark-private",
            "Network identity or privacy mismatch.",
        )
        endpoints = network.get("Containers") or {}
        require(
            set(endpoints) <= ids,
            "Foreign network endpoints; teardown refused.",
        )

        ownership_present = any(key in labels for key in OWNERSHIP)
        if ownership_present:
            require(
                all(labels.get(key) == value
                    for key, value in OWNERSHIP.items()),
                "Partial or conflicting network ownership labels.",
            )
        else:
            require(
                bool(endpoints)
                or network["Id"] in verified_legacy_network_ids,
                "Empty legacy network requires durable ownership evidence.",
            )
            legacy_ids.append(network["Id"])

        for container in containers:
            attached = container["NetworkSettings"].get("Networks") or {}
            if NETWORK in attached:
                require(
                    attached[NETWORK].get("NetworkID") == network["Id"],
                    "Container/network identity mismatch.",
                )

    if not networks:
        require(
            all(not (c["NetworkSettings"].get("Networks") or {})
                for c in containers),
            "Attached project network was not discovered.",
        )

    return {
        "container_ids": sorted(ids),
        "network_ids": [network["Id"] for network in networks],
        "legacy_network_ids": legacy_ids,
    }
