#!/usr/bin/env python3
"""Plan group-local Livy targets using Ansible's canonical inventory order.

Matches groups[worker_group] used by fl_workshop_topology and credential staging.
Never sorts worker aliases, reads credential contents or executes VM tasks.
This plan does not establish runtime readiness or authenticate participants.
"""
import argparse
import json
import re
import sys

HOST = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
GROUP = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


class ScopeError(ValueError):
    pass


def assignments(worker_names):
    """Preserve the caller's canonical inventory sequence exactly."""
    if not isinstance(worker_names, list) or not worker_names:
        raise ScopeError("No ordered workshop machines were resolved.")
    if any(not isinstance(name, str) or not HOST.fullmatch(name)
           for name in worker_names):
        raise ScopeError("Invalid workshop machine alias.")
    if len(set(worker_names)) != len(worker_names):
        raise ScopeError("Duplicate workshop machine aliases.")
    return [{"group_id": f"group_{index:02d}", "worker": name}
            for index, name in enumerate(worker_names, start=1)]


def inventory_hosts(inventory_path, worker_group):
    """Use Ansible's own membership expansion; do not reimplement child ordering."""
    if not isinstance(worker_group, str) or not GROUP.fullmatch(worker_group):
        raise ScopeError("One exact workshop worker group is required.")
    if not isinstance(inventory_path, str) or not inventory_path.strip():
        raise ScopeError("An inventory source is required.")
    from ansible.inventory.manager import InventoryManager
    from ansible.parsing.dataloader import DataLoader

    loader = DataLoader()
    try:
        inventory = InventoryManager(loader=loader, sources=[inventory_path])
        group = inventory.groups.get(worker_group)
        if group is None:
            raise ScopeError("Selected workshop worker group is absent.")
        names = [host.get_name() for host in group.get_hosts()]
        if any(name in inventory.groups for name in names):
            raise ScopeError("Ambiguous inventory group/machine name.")
        return names
    finally:
        loader.cleanup_all_tmp_files()


def resolve_assignments(inventory_path, worker_group):
    return assignments(inventory_hosts(inventory_path, worker_group))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory")
    parser.add_argument("worker_group")
    args = parser.parse_args(argv)
    try:
        groups = resolve_assignments(args.inventory, args.worker_group)
    except ScopeError as error:
        print(f"BLOCKED: {error} No VM tasks were executed.", file=sys.stderr)
        return 2
    except ImportError:
        print("BLOCKED: run with the Python environment providing Ansible. "
              "No alternate ordering was guessed; no VM tasks were executed.",
              file=sys.stderr)
        return 2
    except Exception:
        print("BLOCKED: canonical inventory resolution failed. "
              "No VM tasks were executed.", file=sys.stderr)
        return 2
    print(json.dumps({"status": "PLANNED", "scope": "all-groups",
                      "runtime_readiness": "NOT_VERIFIED", "groups": groups}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
