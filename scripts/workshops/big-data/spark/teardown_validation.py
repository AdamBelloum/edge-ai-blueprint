"""Validate a Docker snapshot before scoped Spark teardown.

No Docker commands or filesystem mutations occur here.
Legacy-network evidence must be persisted before container removal.
"""

import ipaddress
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
    "spark-master", "spark-worker-1", "spark-worker-2", "spark-livy", "spark-client",
    "spark-livy-access",
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


ACCESS_NETWORK = PROJECT + "_spark-access"
PARTICIPANT_IMAGE = "digitafrica/spark-client:3.5.3-ssh-v1"
PARTICIPANT_CMD = [
    "/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/workshop_sshd_config",
]
PARTICIPANT_MOUNTS = {
    (ROOT + "/client-access/host_key", "/etc/ssh/workshop_host_key"),
    (ROOT + "/client-access/login_key.pub", "/etc/ssh/workshop_authorized_keys"),
}


LIVY_ACCESS_CMD = PARTICIPANT_CMD + [
    "-o", "AllowTcpForwarding=local",
    "-o", "AllowStreamLocalForwarding=no",
    "-o", "PermitOpen=spark-livy:8998",
    "-o", "PermitListen=none",
    "-o", "MaxSessions=0",
    "-o", "AllowAgentForwarding=no",
    "-o", "PermitTunnel=no",
    "-o", "GatewayPorts=no",
    "-o", "X11Forwarding=no",
    "-o", "PermitTTY=no",
]


def validate_participant_service(container, *, livy_access=False):
    """Validate direct SSH or the assessed forwarding-only Livy supervisor."""
    expected_command = LIVY_ACCESS_CMD if livy_access else PARTICIPANT_CMD
    expected_memory = 134217728 if livy_access else 1073741824
    config = container.get("Config") or {}
    host = container.get("HostConfig") or {}
    require(config.get("Image") == PARTICIPANT_IMAGE
            and config.get("User") == "root"
            and config.get("Cmd") == expected_command,
            "Participant client runtime configuration mismatch.")
    require(isinstance(container.get("Image"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", container["Image"]),
            "Invalid participant client image identity.")
    caps = host.get("CapAdd") or []
    require(isinstance(caps, list)
            and all(isinstance(cap, str) for cap in caps),
            "Invalid participant client capabilities.")
    caps = [cap.removeprefix("CAP_") for cap in caps]
    require(host.get("Privileged") is False
            and host.get("ReadonlyRootfs") is False
            and host.get("CapDrop") == ["ALL"]
            and len(caps) == 3
            and set(caps) == {"SETUID", "SETGID", "SYS_CHROOT"}
            and host.get("NetworkMode") in {NETWORK, ACCESS_NETWORK}
            and not host.get("PidMode")
            and host.get("IpcMode") in ("", "private")
            and not host.get("Devices")
            and not host.get("DeviceRequests")
            and host.get("SecurityOpt") == ["no-new-privileges:true"]
            and host.get("Memory") == expected_memory
            and (host.get("RestartPolicy") or {}).get("Name") == "no",
            "Unsafe participant client host configuration.")
    if livy_access:
        require(host.get("NanoCpus") == 250000000,
                "Unexpected Livy access gateway CPU limit.")
    bindings = host.get("PortBindings") or {}
    require(isinstance(bindings, dict)
            and set(bindings) == {"2222/tcp"},
            "Unexpected participant client published ports.")
    ports = bindings["2222/tcp"]
    require(isinstance(ports, list) and len(ports) == 1
            and isinstance(ports[0], dict),
            "Ambiguous participant client SSH binding.")
    address = ipaddress.IPv4Address(ports[0].get("HostIp", ""))
    port = ports[0].get("HostPort")
    require(not address.is_unspecified and not address.is_loopback
            and not address.is_multicast and not address.is_reserved
            and isinstance(port, str) and port.isdecimal()
            and 1024 <= int(port) <= 65535,
            "Unsafe participant client SSH binding.")


def validate_snapshot(containers, networks, volumes, *,
                      verified_legacy_network_ids=()):
    """Return verified IDs; reject ambiguous ownership before deletion.

    verified_legacy_network_ids must come from protected, host-local
    evidence written after successful validation, not from user input.
    Current network identity and endpoint checks still apply on retry.
    """
    require(not volumes, "Unexpected project-labelled volumes; teardown refused.")
    require(len(networks) <= 2, "Unexpected project networks.")
    require(all(isinstance(n.get("Id"), str)
                and re.fullmatch(r"[0-9a-f]{64}", n["Id"])
                for n in networks),
            "Invalid full network ID; teardown refused.")
    require(all(isinstance(n.get("Name"), str) for n in networks),
            "Invalid project network name.")
    require(len({n["Name"] for n in networks}) == len(networks)
            and len({n["Id"] for n in networks}) == len(networks),
            "Duplicate project network identity.")
    ids = set()
    services = set()
    client_ids = set()
    participant_ids = set()

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
        elif service in {"spark-client", "spark-livy-access"}:
            livy_access = service == "spark-livy-access"
            validate_participant_service(container, livy_access=livy_access)
            expected_mounts = (set(PARTICIPANT_MOUNTS) if livy_access
                               else expected_mounts | PARTICIPANT_MOUNTS)
            participant_ids.add(identifier)
            client_ids.add(identifier)
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
            set(attached) <= (
                {NETWORK, ACCESS_NETWORK} if service in {"spark-client", "spark-livy-access"}
                else {NETWORK}
            ),
            "Container is attached to an unexpected network.",
        )

    legacy_ids = []
    for network in networks:
        name = network["Name"]
        access = name == ACCESS_NETWORK
        require(
            isinstance(network["Id"], str)
            and re.fullmatch(r"[0-9a-f]{64}", network["Id"]),
            "Invalid full network ID; teardown refused.",
        )
        labels = network.get("Labels") or {}
        require(
            name in {NETWORK, ACCESS_NETWORK}
            and network["Driver"] == "bridge"
            and network["Internal"] is (not access)
            and labels.get("com.docker.compose.project") == PROJECT
            and labels.get("com.docker.compose.network") == (
                "spark-access" if access else "spark-private"
            ),
            "Network identity or privacy mismatch.",
        )
        endpoints = network.get("Containers") or {}
        require(
            set(endpoints) <= (participant_ids if access else ids),
            "Foreign network endpoints; teardown refused.",
        )

        ownership_present = any(key in labels for key in OWNERSHIP)
        if access or ownership_present:
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
            if name in attached:
                require(
                    attached[name].get("NetworkID") == network["Id"],
                    "Container/network identity mismatch.",
                )

    require(
        all(set(c["NetworkSettings"].get("Networks") or {})
            <= {n["Name"] for n in networks} for c in containers),
        "Attached project network was not discovered.",
    )

    return {
        "container_ids": sorted(ids),
        "client_container_ids": sorted(client_ids),
        "network_ids": [
            network["Id"] for network in sorted(
                networks, key=lambda n: n["Name"] != ACCESS_NETWORK
            )
        ],
        "legacy_network_ids": legacy_ids,
    }
