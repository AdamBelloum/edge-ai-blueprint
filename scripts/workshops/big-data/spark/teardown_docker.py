"""Local Docker adapter; no executable entry point."""
import json
import re
import subprocess

PROJECT = "digitafrica-spark"
PREFIX = ["docker", "--host", "unix:///var/run/docker.sock"]
FILTER = "label=com.docker.compose.project=" + PROJECT
# Separate queries implement OR discovery. Inspect and validate the union:
# neither run-label presence nor a name prefix alone authorises removal.
CONTAINER_FILTERS = (
    FILTER,
    "label=org.digitafrica.direct-run-id",
    "label=org.digitafrica.livy-client-run-id",
)


def full_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a full Docker resource ID.")
    return value


class Docker:
    def __init__(self, run=subprocess.run):
        self.run = run

    def command(self, *arguments):
        result = self.run(
            PREFIX + list(arguments), check=True,
            text=True, capture_output=True, timeout=120,
        )
        return result.stdout

    def daemon_id(self):
        value = self.command("info", "--format", "{{.ID}}").strip()
        if not value:
            raise ValueError("Docker daemon identity is missing.")
        return value

    def inspect(self, kind, identifiers):
        if not identifiers:
            return []
        for identifier in identifiers:
            full_id(identifier)
        records = json.loads(self.command(kind, "inspect", *identifiers))
        if not isinstance(records, list) or not all(
            isinstance(record, dict) for record in records
        ):
            raise ValueError("Invalid Docker inspection response.")
        returned = [full_id(record.get("Id")) for record in records]
        if len(returned) != len(identifiers) or set(returned) != set(identifiers):
            raise ValueError("Docker inspection IDs do not match discovery.")
        return records

    def snapshot(self):
        container_ids = set()
        for resource_filter in CONTAINER_FILTERS:
            found = self.command(
                "container", "ls", "--all", "--quiet", "--no-trunc",
                "--filter", resource_filter,
            ).split()
            container_ids.update(full_id(identifier) for identifier in found)
        containers = sorted(container_ids)
        networks = self.command(
            "network", "ls", "--quiet", "--no-trunc", "--filter", FILTER,
        ).split()
        volumes = self.command(
            "volume", "ls", "--quiet", "--filter", FILTER,
        ).split()
        return (
            self.inspect("container", containers),
            self.inspect("network", networks),
            volumes,
        )

    def remove_container(self, identifier):
        self.command("container", "rm", "--force", full_id(identifier))

    def remove_network(self, identifier):
        self.command("network", "rm", full_id(identifier))
