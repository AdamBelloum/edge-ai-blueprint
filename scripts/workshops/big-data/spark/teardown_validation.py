"""Validate a Docker snapshot before scoped Spark teardown.

No Docker commands or filesystem mutations occur here.
Legacy-network evidence must be persisted before container removal.
"""

import re

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


CLIENT_IMAGE = (
    "apache/spark@sha256:"
    "d0f5d63bfbbffdbec08debb4911554ba671a2fa7398374db8db314d80328f576"
)
CLIENT_LABELS = {
    "org.digitafrica.direct-run-id": ("digitafrica-direct-", "direct-run-", True),
    "org.digitafrica.livy-client-run-id": (
        "digitafrica-livy-client-", "livy-client-run-", False
    ),
}


def validate_client(container):
    """Validate a current organiser client, including stopped/detached orphans.

    Labels alone do not authorise removal. Require the exact name/run-ID,
    pinned image reference, restricted host configuration, reviewed bind
    destinations and private-network scope. Docker remains admin-controlled.
    No filesystem paths are deleted or followed by this validation.
    """
    config = container.get("Config") or {}
    labels = config.get("Labels") or {}
    keys = [key for key in CLIENT_LABELS if key in labels]
    require(len(keys) == 1, "Ambiguous submission client run labels.")
    key = keys[0]
    name_prefix, directory_prefix, direct = CLIENT_LABELS[key]
    token = labels[key]
    require(isinstance(token, str) and re.fullmatch(r"[0-9a-f]{32}", token),
            "Invalid submission client run ID.")
    require(container.get("Name") == "/" + name_prefix + token,
            "Submission client name/run-ID mismatch.")
    require(all(labels.get(k) == v for k, v in OWNERSHIP.items()),
            "Submission client ownership mismatch.")
    require(not any(k.startswith("com.docker.compose.") for k in labels),
            "Submission client has conflicting Compose provenance.")
    require(config.get("Image") == CLIENT_IMAGE,
            "Submission client pinned image reference mismatch.")
    require(isinstance(container.get("Image"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", container["Image"]),
            "Invalid submission client image identity.")
    require(config.get("Entrypoint") == (
                ["/opt/spark/bin/spark-submit"] if direct else ["python3"]),
            "Unexpected submission client entrypoint.")
    require(isinstance(config.get("User"), str)
            and re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", config["User"]),
            "Submission client must use non-root UID/GID.")
    host = container.get("HostConfig") or {}
    require(host.get("Privileged") is False
            and host.get("ReadonlyRootfs") is True
            and not host.get("PortBindings")
            and not host.get("CapAdd")
            and host.get("CapDrop") == ["ALL"]
            and host.get("NetworkMode") == NETWORK
            and not host.get("PidMode")
            and host.get("IpcMode") in ("", "private")
            and not host.get("Devices")
            and not host.get("DeviceRequests")
            and "no-new-privileges:true" in (host.get("SecurityOpt") or []),
            "Unsafe submission client host configuration.")
    require((host.get("RestartPolicy") or {}).get("Name") == "no",
            "Unexpected submission client restart policy.")
    attached = (container.get("NetworkSettings") or {}).get("Networks") or {}
    require(set(attached) <= {NETWORK},
            "Submission client is attached to an unexpected network.")

    mounts = container.get("Mounts") or []
    work = [m for m in mounts if m.get("Destination") == "/work"]
    require(len(work) == 1 and isinstance(work[0].get("Source"), str),
            "Missing or ambiguous submission client work mount.")
    run_dir = work[0]["Source"]
    require(re.fullmatch(re.escape(ROOT + "/" + directory_prefix)
                         + r"[a-z0-9_]{8}", run_dir),
            "Submission client run directory is outside the reviewed scope.")
    expected = {
        (run_dir, "/work", False),
        (run_dir + "/outputs", "/work/outputs", True),
        (DATA_MOUNT[0], "/work/data", False),
    }
    if direct:
        expected.add((DATA_MOUNT[0], DATA_MOUNT[1], False))
    actual = set()
    for mount in mounts:
        require(mount.get("Type") == "bind" and type(mount.get("RW")) is bool,
                "Unexpected submission client mount type or permissions.")
        actual.add((mount.get("Source"), mount.get("Destination"), mount["RW"]))
    require(actual == expected and len(mounts) == len(expected),
            "Unexpected or missing submission client mounts.")


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
    client_ids = set()

    for container in containers:
        identifier = container["Id"]
        require(
            isinstance(identifier, str)
            and re.fullmatch(r"[0-9a-f]{64}", identifier),
            "Invalid full container ID; teardown refused.",
        )
        require(identifier not in ids, "Duplicate container ID.")
        ids.add(identifier)
        labels = container["Config"].get("Labels") or {}
        if any(key in labels for key in CLIENT_LABELS):
            validate_client(container)
            client_ids.add(identifier)
            continue
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
        require(
            isinstance(network["Id"], str)
            and re.fullmatch(r"[0-9a-f]{64}", network["Id"]),
            "Invalid full network ID; teardown refused.",
        )
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
        "client_container_ids": sorted(client_ids),
        "network_ids": [network["Id"] for network in networks],
        "legacy_network_ids": legacy_ids,
    }
