#!/usr/bin/env python3
"""Local-only manifests from installation allowlists and resolved inventory."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import yaml

spec = importlib.util.spec_from_file_location(
    "hpc_cleanup_engine", Path(__file__).with_name("cleanup-staged-files.py"))
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def ordered_hosts(inventory, name):
    if name in ("all", "ungrouped") or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise ValueError("Broad or unsafe cleanup group")
    result = []

    def visit(group_name, ancestors):
        if group_name in ancestors:
            raise ValueError("Inventory group cycle")
        group = inventory.get(group_name)
        if not isinstance(group, dict):
            raise ValueError("Missing released inventory group")
        hosts = group.get("hosts", [])
        children = group.get("children", [])
        if not isinstance(hosts, list) or not isinstance(children, list):
            raise ValueError("Invalid inventory group")
        for host in hosts:
            if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", host):
                raise ValueError("Unsafe inventory host alias")
            if host not in result:
                result.append(host)
        for child in children:
            if not isinstance(child, str):
                raise ValueError("Invalid child group")
            visit(child, ancestors | {group_name})

    visit(name, set())
    if not result:
        raise ValueError("Released cleanup group has no hosts")
    return result


def read_yaml(path):
    with path.open() as stream:
        return yaml.safe_load(stream)


def authorize_revision(root, revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Source revision must be a full lowercase commit SHA")
    def git(*arguments):
        return subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True, check=False,
        )
    kind = git("cat-file", "-t", revision)
    if kind.returncode != 0 or kind.stdout.strip() != b"commit":
        raise ValueError("Source revision is not an available commit")
    if git("merge-base", "--is-ancestor", revision, "HEAD").returncode != 0:
        raise ValueError("Source revision is not an ancestor of current HEAD")
    if git("diff", "--quiet", revision, "--",
           "roles/hpc_workspace", "roles/hpc_runtime").returncode != 0:
        raise ValueError("Historical installation roles differ; reviewed migration is required")


def digest(path, revision=None, repository=None):
    if revision is not None:
        relative = path.relative_to(repository).as_posix()
        result = subprocess.run(
            ["git", "-C", str(repository), "show", revision + ":" + relative],
            capture_output=True, check=False,
        )
        if result.returncode != 0:
            raise ValueError("Installation source is absent from pinned revision: " + relative)
        content = result.stdout
    else:
        if not stat.S_ISREG(path.lstat().st_mode) or path.resolve() != path:
            raise ValueError("Installation source is not a regular non-symlink file")
        content = path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def build(root, inventory, worker_group, control_group, revision=None):
    root = Path(root).resolve()
    if revision is not None:
        authorize_revision(root, revision)
    workers = ordered_hosts(inventory, worker_group)
    central = ordered_hosts(inventory, control_group)
    hosts = list(dict.fromkeys(workers + central))
    workspace = read_yaml(root / "roles/hpc_workspace/defaults/main.yml")
    runtime = read_yaml(root / "roles/hpc_runtime/defaults/main.yml")

    expected = {
        "hpc_workspace_host_path": "/opt/digitafrica/hpc",
        "hpc_runtime_host_path": "/opt/digitafrica/hpc-runtime",
        "hpc_workspace_source": "{{ playbook_dir }}/../workshop_assets/hpc",
        "hpc_runtime_environment_source":
            "{{ playbook_dir }}/../workshop_assets/hpc/runtime/environment.yml",
        "hpc_workspace_files": workspace["hpc_workspace_files"],
        "hpc_workspace_directories": workspace["hpc_workspace_directories"],
    }
    defaults = dict(workspace, **runtime)
    for key, value in expected.items():
        if defaults.get(key) != value:
            raise ValueError("Nonstandard installation default: " + key)

    hostvars = inventory.get("_meta", {}).get("hostvars", {})
    if not isinstance(hostvars, dict):
        raise ValueError("Invalid inventory hostvars")
    for host in hosts:
        values = hostvars.get(host, {})
        if not isinstance(values, dict):
            raise ValueError("Invalid resolved host variables")
        for key, value in expected.items():
            if key in values and values[key] != value:
                raise ValueError("Unsupported override on " + host + ": " + key)

    tasks = read_yaml(root / "roles/hpc_workspace/tasks/main.yml")
    copies = [task for task in tasks if "ansible.builtin.copy" in task]
    expected_copy = {
        "src": "{{ hpc_workspace_source }}/{{ item }}",
        "dest": "{{ hpc_workspace_host_path }}/{{ item }}",
        "owner": "root",
        "group": "root",
        "mode": "{{ '0755' if item in ['OpenMP/helpers/openmp_start', 'MPI/helpers/mpi_start'] else '0644' }}",
    }
    if (len(copies) != 1
            or copies[0].get("loop") != "{{ hpc_workspace_files }}"
            or copies[0]["ansible.builtin.copy"] != expected_copy):
        raise ValueError("Workspace installation contract changed; review cleanup")

    workspace_entries = [
        {
            "path": name,
            "sha256": "0" * 64,
            "mode": 0o755 if name in (
                "OpenMP/helpers/openmp_start", "MPI/helpers/mpi_start"
            ) else 0o644,
        }
        for name in workspace["hpc_workspace_files"]
    ]
    engine.validate_entries(workspace_entries)
    for entry in workspace_entries:
        entry["sha256"] = digest(root / "workshop_assets/hpc" / entry["path"], revision, root)

    runtime_entries = []
    tasks = read_yaml(root / "roles/hpc_runtime/tasks/main.yml")
    for task in tasks:
        if "ansible.builtin.copy" not in task:
            continue
        copy = task["ansible.builtin.copy"]
        prefix = "{{ hpc_runtime_host_path }}/"
        destination = copy.get("dest")
        if not isinstance(destination, str) or not destination.startswith(prefix):
            raise ValueError("Runtime destination contract changed")
        name = destination[len(prefix):]
        if copy.get("owner") != "root" or copy.get("group") != "root":
            raise ValueError("Runtime ownership contract changed")
        source = copy.get("src")
        if source == "{{ hpc_runtime_environment_source }}" and name == "environment.yml":
            path = root / "workshop_assets/hpc/runtime/environment.yml"
        elif source == name and name in (
            "prepare-hpc-environment.sh", "hpc-notebook-launch.sh"
        ):
            path = root / "roles/hpc_runtime/files" / name
        else:
            raise ValueError("Runtime source contract changed")
        runtime_entries.append({
            "path": name,
            "sha256": digest(path, revision, root),
            "mode": int(str(copy["mode"]), 8),
        })

    if {entry["path"] for entry in runtime_entries} != {
        "environment.yml", "prepare-hpc-environment.sh", "hpc-notebook-launch.sh"
    }:
        raise ValueError("Runtime installation allowlist changed")
    engine.validate_entries(runtime_entries)

    return {
        "hpc_cleanup_source_revision": revision or "working-tree",
        "hpc_cleanup_hosts": hosts,
        "hpc_cleanup_jobs": [
            {"scope": "workspace", "hosts": workers,
             "manifest": {"scope": "workspace", "files": workspace_entries}},
            {"scope": "runtime", "hosts": central,
             "manifest": {"scope": "runtime", "files": runtime_entries}},
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--inventory-json", required=True)
    parser.add_argument("--worker-group", required=True)
    parser.add_argument("--control-group", required=True)
    parser.add_argument("--source-revision")
    args = parser.parse_args()
    try:
        with open(args.inventory_json) as stream:
            inventory = json.load(stream)
        if not isinstance(inventory, dict):
            raise ValueError("Inventory must be a JSON object")
        print(json.dumps(build(
            args.repository_root, inventory,
            args.worker_group, args.control_group, args.source_revision)))
    except (ValueError, TypeError, KeyError, OSError,
            yaml.YAMLError, engine.CleanupError) as error:
        print("ERROR: HPC manifest refused: " + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
