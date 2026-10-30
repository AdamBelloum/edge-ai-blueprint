#!/usr/bin/env python3
"""Build Spark direct-access NetworkPolicies from discovered Docker DNAT rules.

Reads one JSON request on stdin and prints the NetworkPolicy manifests and a
non-secret summary on stdout. It never contacts a cluster and handles no keys.
"""
from __future__ import annotations

import ipaddress
import json
import re
import sys

MANAGED_LABELS = {
    "digitafrica.eu/managed-by": "organiser",
    "digitafrica.eu/module": "spark",
    "digitafrica.eu/workshop": "big-data",
}
GROUP_LABEL = "digitafrica.eu/spark-group"
GROUP_RE = re.compile(r"^group_[0-9]{2,}$")
NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def _has_pair(tokens, flag, value):
    return any(
        tokens[i] == flag and tokens[i + 1] == value
        for i in range(len(tokens) - 1)
    )


def parse_dnat_destination(nat_text, bind_ip, port=2222):
    """Return the single private IPv4 that Docker maps bind_ip:port to."""
    bind = str(ipaddress.ip_address(bind_ip))
    destinations = set()
    for line in nat_text.splitlines():
        tokens = line.split()
        if tokens[:2] != ["-A", "DOCKER"]:
            continue
        if not (
            _has_pair(tokens, "-j", "DNAT")
            and _has_pair(tokens, "-p", "tcp")
            and _has_pair(tokens, "-d", f"{bind}/32")
            and _has_pair(tokens, "--dport", str(port))
        ):
            continue
        for i in range(len(tokens) - 1):
            if tokens[i] == "--to-destination":
                destinations.add(tokens[i + 1])
    if not destinations:
        raise ValueError(f"no DNAT rule for {bind}:{port}")
    if len(destinations) != 1:
        raise ValueError(f"ambiguous DNAT rules for {bind}:{port}")
    (target,) = destinations
    host, separator, target_port = target.rpartition(":")
    if not separator or target_port != str(port):
        raise ValueError(f"unexpected DNAT target port in {target!r}")
    address = ipaddress.ip_address(host)
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
    ):
        raise ValueError(f"DNAT target is not a private container address: {host}")
    return str(address)


def policy_name(group_id):
    return "digitafrica-spark-direct-" + group_id.replace("_", "-")


def build_policy(group_id, destination, namespace, port=2222, release="jhub"):
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": policy_name(group_id),
            "namespace": namespace,
            "labels": dict(MANAGED_LABELS),
        },
        "spec": {
            "podSelector": {
                "matchLabels": {
                    "app": "jupyterhub",
                    "component": "singleuser-server",
                    "release": release,
                    GROUP_LABEL: group_id,
                }
            },
            "policyTypes": ["Egress"],
            "egress": [
                {
                    "to": [{"ipBlock": {"cidr": f"{destination}/32"}}],
                    "ports": [{"protocol": "TCP", "port": port}],
                }
            ],
        },
    }


def build_plan(request):
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    namespace = request.get("namespace", "digitafrica")
    release = request.get("release", "jhub")
    port = request.get("port", 2222)
    for label, value in (("namespace", namespace), ("release", release)):
        if not isinstance(value, str) or not NAME_RE.fullmatch(value):
            raise ValueError(f"invalid {label}: {value!r}")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"invalid port: {port!r}")
    groups = request.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("groups must be a non-empty list")

    policies, summary, seen = [], [], set()
    for item in groups:
        group_id = item.get("group_id") if isinstance(item, dict) else None
        if not isinstance(group_id, str) or not GROUP_RE.fullmatch(group_id):
            raise ValueError(f"invalid group id: {group_id!r}")
        if group_id in seen:
            raise ValueError(f"duplicate group id: {group_id}")
        seen.add(group_id)
        try:
            destination = parse_dnat_destination(
                item.get("nat_text", ""), item.get("bind_ip", ""), port
            )
        except ValueError as exc:
            raise ValueError(f"{group_id}: {exc}") from exc
        policies.append(build_policy(group_id, destination, namespace, port, release))
        summary.append({
            "group_id": group_id,
            "worker": str(item.get("worker", "")),
            "destination": destination,
            "policy": policy_name(group_id),
        })
    return {"policies": policies, "summary": summary}


def main():
    try:
        plan = build_plan(json.load(sys.stdin))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    json.dump(plan, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
