#!/usr/bin/env python3
"""List workshop machines or validate one exact host; never run VM tasks."""
import json
import re
import subprocess
import sys

HOST = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
GROUP = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def validate_scope(data, group, host):
    if not GROUP.fullmatch(group) or (host is not None and not HOST.fullmatch(host)):
        raise ValueError("Invalid exact scope.")
    if not isinstance(data, dict) or group not in data or (host is not None and host in data):
        raise ValueError("Missing group or ambiguous group/host name.")
    visited, members = set(), set()

    def visit(name):
        if name in visited:
            return
        visited.add(name)
        value = data.get(name)
        if not isinstance(value, dict):
            raise ValueError("Invalid inventory group.")
        hosts = value.get("hosts", [])
        children = value.get("children", [])
        if (not isinstance(hosts, list) or not isinstance(children, list)
                or not all(isinstance(v, str) for v in hosts + children)):
            raise ValueError("Invalid inventory membership.")
        members.update(hosts)
        for child in children:
            visit(child)

    visit(group)
    if host is None:
        if not members:
            raise ValueError("No workshop machines found.")
        if any(not HOST.fullmatch(member) or member in data for member in members):
            raise ValueError("Invalid or ambiguous workshop machine name.")
        return sorted(members)
    if host not in members:
        raise ValueError("Machine is outside the selected worker group.")
    return host


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        print("Inventory, group and an exact host or --list-workers required.", file=sys.stderr)
        return 2
    inventory, group, host = args
    try:
        result = subprocess.run(
            ["ansible-inventory", "-i", inventory, "--list"],
            check=True, text=True, capture_output=True, timeout=60)
        if len(result.stdout) > 16 * 1024 * 1024:
            raise ValueError("Inventory exceeded its bound.")
        resolved = validate_scope(
            json.loads(result.stdout), group,
            None if host == "--list-workers" else host)
        if host == "--list-workers":
            print("\n".join(resolved))
    except Exception:
        print("Workshop machine verification failed; no VM tasks were run.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
