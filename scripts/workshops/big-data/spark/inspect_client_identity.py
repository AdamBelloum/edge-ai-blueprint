#!/usr/bin/env python3
"""Public-only evidence from one organiser-managed running Spark client."""
import argparse
import ipaddress
import json
import os
import socket
import subprocess
import sys


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def output(argv):
    return subprocess.check_output(argv, text=True, stderr=subprocess.PIPE, timeout=20)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--expected-image", required=True)
    args = parser.parse_args()
    ids = output(["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=" + args.project,
                  "--filter", "label=com.docker.compose.service=spark-client"]).split()
    require(len(ids) == 1, "Expected exactly one running client")
    client = json.loads(output(["docker", "inspect", ids[0]]))[0]
    labels = client["Config"].get("Labels") or {}
    require(labels.get("org.digitafrica.managed-by") == "organiser", "Unmanaged client")
    require(client["State"]["Running"], "Client not running")
    require(client["Config"]["Image"] == args.expected_image, "Unexpected client image")
    for target, source in (
        ("/etc/ssh/workshop_host_key", "host_key"),
        ("/etc/ssh/workshop_authorized_keys", "login_key.pub"),
    ):
        mounts = [m for m in client["Mounts"] if m["Destination"] == target]
        expected = os.path.realpath(os.path.join(args.runtime, "client-access", source))
        require(len(mounts) == 1 and os.path.realpath(mounts[0]["Source"]) == expected
                and mounts[0]["RW"] is False, "Unexpected active key mount")
    ports = client["NetworkSettings"]["Ports"].get("2222/tcp") or []
    require(len(ports) == 1, "Expected one published client endpoint")
    host, port = ports[0]["HostIp"], int(ports[0]["HostPort"])
    address = ipaddress.ip_address(host)
    require(address.version == 4 and not address.is_unspecified and not address.is_loopback,
            "Invalid published client address")
    access = client["NetworkSettings"]["Networks"].get(args.project + "_spark-access", {})
    access_ip = access.get("IPAddress", "")
    require(bool(access_ip), "Missing Spark access-network address")
    ipaddress.ip_address(access_ip)
    host_public = output(["docker", "exec", "--user", "0", ids[0],
                          "ssh-keygen", "-y", "-P", "", "-f", "/etc/ssh/workshop_host_key"])
    authorized_public = output(["docker", "exec", "--user", "0", ids[0],
                                "cat", "/etc/ssh/workshop_authorized_keys"])
    print(json.dumps(dict(worker_node=socket.getfqdn(), running_client_count=1,
        managed_by="organiser", image=client["Config"]["Image"], mounts_verified=True,
        host=host, port=port, access_ip=access_ip,
        host_public=host_public.strip(), authorized_public=authorized_public.strip())))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Active client identity inspection failed; no credentials changed.", file=sys.stderr)
        sys.exit(2)
