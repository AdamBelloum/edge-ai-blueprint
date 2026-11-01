"""Read-only host-local staging adapters; no live entry point.

The shared submission lock must surround these observations and subsequent writes.
Other Docker/filesystem writers must be excluded administratively: snapshots
are not atomic and the cooperative lock does not constrain those writers.
"""
from contextlib import contextmanager
import json
import os
import re
import subprocess

from teardown_directory import (
    FLAGS, SUBMISSION_COMPONENTS, check_ancestor, locked_submission_runtime,
)
from teardown_assets import mount_paths

ID = re.compile(r"[0-9a-f]{64}")
BATCH_SIZE = 64
MAX_CONTAINERS = 4096


def require(condition, message):
    if not condition:
        raise ValueError(message)


@contextmanager
def open_runtime():
    """Require existing protected ancestors; never create runtime directories."""
    if os.geteuid() != 0:
        raise PermissionError("Candidate staging requires root.")
    descriptors = []
    try:
        fd = os.open("/", FLAGS)
        descriptors.append(fd)
        check_ancestor(fd)
        for component in SUBMISSION_COMPONENTS:
            fd = os.open(component, FLAGS, dir_fd=fd)
            descriptors.append(fd)
            check_ancestor(fd)
        yield fd
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def observe_mounts(*, run=subprocess.run, host_mounts=mount_paths):
    """Inspect every container and refuse unstable or unverifiable inventories."""
    def command(argv):
        result = run(argv, text=True, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, timeout=30, check=False)
        require(result.returncode == 0 and isinstance(result.stdout, str),
                "Docker mount observation command failed.")
        return result.stdout.strip()

    def daemon():
        value = command(["docker", "info", "--format", "{{.ID}}"])
        require(value and len(value) <= 256 and not any(c.isspace() for c in value),
                "Docker daemon identity is unverifiable.")
        return value

    def inventory():
        values = command([
            "docker", "container", "ls", "--all", "--quiet", "--no-trunc"
        ]).split()
        require(len(values) <= MAX_CONTAINERS
                and len(values) == len(set(values))
                and all(ID.fullmatch(value) for value in values),
                "Invalid or excessive full container inventory.")
        return sorted(values)

    host_before = set(host_mounts())
    before_daemon = daemon()
    ids = inventory()
    sources = set()
    for offset in range(0, len(ids), BATCH_SIZE):
        batch = ids[offset:offset + BATCH_SIZE]
        containers = json.loads(command(["docker", "container", "inspect", *batch]))
        require(isinstance(containers, list)
                and len(containers) == len(batch)
                and all(isinstance(c, dict) for c in containers)
                and {c.get("Id") for c in containers} == set(batch),
                "Docker inspection does not match the complete requested inventory.")
        for container in containers:
            mounts = container.get("Mounts")
            require(isinstance(mounts, list), "Container mounts are unverifiable.")
            for mount in mounts:
                require(isinstance(mount, dict)
                        and mount.get("Type") in {"bind", "volume", "tmpfs"},
                        "Unexpected Docker mount type.")
                if mount["Type"] == "tmpfs":
                    continue
                source = mount.get("Source")
                require(isinstance(source, str) and source.startswith("/"),
                        "Docker mount source is unverifiable.")
                sources.add(source)
    require(inventory() == ids, "Container inventory changed during observation.")
    require(daemon() == before_daemon, "Docker daemon changed during observation.")
    host_after = set(host_mounts())
    require(host_before == host_after, "Host mount inventory changed during observation.")
    return {"docker_sources": sorted(sources), "host_mounts": sorted(host_after)}
