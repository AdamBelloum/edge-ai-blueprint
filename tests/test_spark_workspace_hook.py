#!/usr/bin/env python3
"""Local mock tests: no Kubernetes, Docker, networking or repository writes.

Save as tests/test_spark_workspace_hook.py and run from the repository:
    python3 tests/test_spark_workspace_hook.py

Requires Jinja2, normally available in the Ansible virtual environment.
Only the group-workspace extraConfig block is rendered and executed.
These tests do not validate Helm, KubeSpawner internals or live Pod startup.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import textwrap
from types import SimpleNamespace
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_PATH = "roles/k8s_apps/templates/jhub-values.yaml.j2"
ROOT = Path(subprocess.check_output(
    ["git", "rev-parse", "--show-toplevel"], text=True
).strip())
CURRENT = (ROOT / TEMPLATE_PATH).read_text(encoding="utf-8")
BASELINE = subprocess.check_output(
    ["git", "show", "HEAD:" + TEMPLATE_PATH], cwd=ROOT, text=True
)
SPARK_VOLUME = "digitafrica-spark-source"
SPARK_ENV = "DIGITAFRICA_SPARK_WORKSPACE_ROLE"
GROUP_NODES = {"group_01": "inventory-worker-a", "group_02": "inventory-worker-b"}


def load_hook(source, enabled=False, oidc=True, hpc=False, runtime=False, module5=False, neutral=False, credentials=False):
    marker = "    10-digitafrica-group-workspace: |\n"
    if marker not in source:
        raise RuntimeError("Group-workspace extraConfig block was not found.")
    block = source.split(marker, 1)[1].split("\n  config:", 1)[0]
    environment = Environment(
        loader=FileSystemLoader(str(ROOT / "roles/k8s_apps/templates")),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=False,
        keep_trailing_newline=False,
    )
    environment.filters["to_json"] = json.dumps
    # All bool-filter inputs in this isolated block are actual Python booleans.
    environment.filters["bool"] = bool
    rendered = environment.from_string(block).render(
        workshop_group_nodes=GROUP_NODES,
        jupyterhub_admin_users=["admin"],
        oidc={"oidc_enabled": oidc},
        big_data_workspace_enabled=enabled,
        hpc_workspace_enabled=hpc,
        hpc_runtime_enabled=runtime,
        cloud_module5_delivery_enabled=module5,
        workshop_reset_neutral=neutral,
        big_data_spark_credentials_enabled=credentials,
        digitafrica_deployment={"digitafrica_namespace": "test-workshop"},
    )
    namespace = {"c": SimpleNamespace(KubeSpawner=SimpleNamespace())}
    exec(compile(textwrap.dedent(rendered), TEMPLATE_PATH + ":workspace-hook", "exec"), namespace)
    return namespace


def seed_container(name="tutorial-seed"):
    return {
        "name": name,
        "env": [{"name": "EXISTING_SETTING", "value": "preserved"}],
        "volumeMounts": [
            {"name": "beginner-assets", "mountPath": "/seed/beginner", "readOnly": True}
        ],
    }


def spawner(username="participant", groups=("group_01",), seed_count=1):
    return SimpleNamespace(
        user=SimpleNamespace(
            name=username, groups=[SimpleNamespace(name=name) for name in groups]
        ),
        init_containers=[seed_container("seed-" + str(i)) for i in range(seed_count)],
        node_selector={"existing-selector": "preserved"},
        volumes={"existing": {"name": "existing", "emptyDir": {}}},
        volume_mounts={"existing": {"name": "existing", "mountPath": "/existing"}},
        environment={"EXISTING_SETTING": "preserved"},
    )


def run_hook(namespace, instance):
    asyncio.run(namespace["configure_digitafrica_group_workspace"](instance))


def snapshot(instance, normalize_disabled=False):
    state = deepcopy({key: getattr(instance, key) for key in (
        "init_containers", "node_selector", "volumes", "volume_mounts", "environment"
    )})
    if normalize_disabled:
        # A disabled marker is an intentional addition, not a placement regression.
        for container in state["init_containers"]:
            container["env"] = [entry for entry in container.get("env", [])
                                if not (entry.get("name") == SPARK_ENV
                                        and entry.get("value") == "disabled")]
    return state


class WorkspaceHookTests(unittest.TestCase):
    def assert_non_spark_matches_baseline(self, original, oidc=True):
        baseline_instance = deepcopy(original)
        current_instance = deepcopy(original)
        run_hook(load_hook(BASELINE, oidc=oidc), baseline_instance)
        run_hook(load_hook(CURRENT, oidc=oidc), current_instance)
        self.assertEqual(snapshot(baseline_instance),
                         snapshot(current_instance, normalize_disabled=True))

    def test_non_spark_oidc_participant_preserves_baseline(self):
        self.assert_non_spark_matches_baseline(spawner())

    def test_non_spark_legacy_participant_preserves_baseline(self):
        self.assert_non_spark_matches_baseline(
            spawner(username="group_02", groups=()), oidc=False
        )

    def test_non_spark_admin_preserves_baseline(self):
        self.assert_non_spark_matches_baseline(spawner(username="admin", groups=()))

    def test_disabled_spark_does_not_require_a_seed_container(self):
        self.assert_non_spark_matches_baseline(spawner(seed_count=0))

    def test_disabled_spark_does_not_require_exactly_one_seed_container(self):
        self.assert_non_spark_matches_baseline(spawner(seed_count=2))

    def test_oidc_rejects_unassigned_and_ambiguous_participants(self):
        for groups in ((), ("group_01", "group_02")):
            for enabled in (False, True):
                with self.subTest(groups=groups, enabled=enabled):
                    with self.assertRaises(RuntimeError):
                        run_hook(load_hook(CURRENT, enabled=enabled), spawner(groups=groups))

    def test_spark_participant_receives_read_only_init_only_source(self):
        instance = spawner()
        run_hook(load_hook(CURRENT, enabled=True), instance)
        self.assertEqual(instance.node_selector["kubernetes.io/hostname"], GROUP_NODES["group_01"])
        self.assertEqual(instance.environment["GROUP_ID"], "group_01")
        source = instance.volumes[SPARK_VOLUME]
        self.assertEqual(source["hostPath"], {
            "path": "/opt/digitafrica/big-data/spark", "type": "Directory"
        })
        mounts = [mount for mount in instance.init_containers[0]["volumeMounts"]
                  if mount.get("name") == SPARK_VOLUME]
        self.assertEqual(mounts, [{
            "name": SPARK_VOLUME, "mountPath": "/seed/big-data/spark", "readOnly": True
        }])
        self.assertFalse(any(mount.get("name") == SPARK_VOLUME
                             for mount in instance.volume_mounts.values()))
        self.assertIn({"name": SPARK_ENV, "value": "participant"},
                      instance.init_containers[0]["env"])

    def test_spark_admin_has_no_participant_source_or_placement(self):
        instance = spawner(username="admin", groups=())
        run_hook(load_hook(CURRENT, enabled=True), instance)
        self.assertNotIn(SPARK_VOLUME, instance.volumes)
        self.assertNotIn("kubernetes.io/hostname", instance.node_selector)
        self.assertNotIn("GROUP_ID", instance.environment)
        self.assertIn({"name": SPARK_ENV, "value": "administrator"},
                      instance.init_containers[0]["env"])

    def test_shared_init_container_configuration_is_not_mutated(self):
        shared = [seed_container()]
        before = deepcopy(shared)
        participant = spawner()
        participant.init_containers = shared
        admin = spawner(username="admin", groups=())
        admin.init_containers = shared
        namespace = load_hook(CURRENT, enabled=True)
        run_hook(namespace, participant)
        run_hook(namespace, admin)
        self.assertEqual(shared, before)
        self.assertNotIn(SPARK_VOLUME, admin.volumes)
        self.assertFalse(any(mount.get("name") == SPARK_VOLUME
                             for mount in admin.init_containers[0]["volumeMounts"]))

    def test_inactive_workshop_hooks_are_absent(self):
        namespace = load_hook(CURRENT, enabled=False)
        for name in (
            "configure_digitafrica_spark_source",
            "configure_digitafrica_hpc_source",
        ):
            self.assertNotIn(name, namespace)

    def test_neutral_spawn_does_not_inspect_init_container_objects(self):
        instance = spawner()
        # An object without dictionary methods reproduces the original
        # interface mismatch. Inactive integrations must not inspect it.
        container = SimpleNamespace(name="tutorial-seed")
        instance.init_containers = [container]
        run_hook(load_hook(CURRENT, enabled=False), instance)
        self.assertIs(instance.init_containers[0], container)
        self.assertEqual(instance.environment["GROUP_ID"], "group_01")
        self.assertEqual(
            instance.node_selector["kubernetes.io/hostname"],
            GROUP_NODES["group_01"],
        )

    def test_fresh_neutral_configuration_has_no_spark_resources(self):
        # Workshop transitions use cleanup and fresh reconciliation,
        # not mutation of an earlier workshop's live spawner.
        spark_instance = spawner()
        run_hook(load_hook(CURRENT, enabled=True), spark_instance)
        self.assertIn(SPARK_VOLUME, spark_instance.volumes)

        neutral_instance = spawner()
        run_hook(load_hook(CURRENT, enabled=False), neutral_instance)
        self.assertNotIn(SPARK_VOLUME, neutral_instance.volumes)
        self.assertFalse(any(
            entry.get("name") == SPARK_ENV
            for container in neutral_instance.init_containers
            for entry in container.get("env", [])
        ))


    def test_reset_neutral_participant_keeps_placement_without_data_mount(self):
        instance = spawner()
        before = snapshot(instance)
        namespace = load_hook(CURRENT, neutral=True)
        run_hook(namespace, instance)

        self.assertEqual(
            instance.node_selector["kubernetes.io/hostname"],
            GROUP_NODES["group_01"],
        )
        self.assertEqual(instance.environment["GROUP_ID"], "group_01")
        self.assertEqual(instance.volumes, before["volumes"])
        self.assertEqual(instance.volume_mounts, before["volume_mounts"])
        self.assertEqual(instance.init_containers, before["init_containers"])
        for name in (
            "configure_digitafrica_spark_source",
            "configure_digitafrica_hpc_source",
            "configure_digitafrica_module5_node_launch",
        ):
            self.assertNotIn(name, namespace)

    def test_reset_neutral_legacy_participant_keeps_placement(self):
        instance = spawner(username="group_02", groups=())
        before = snapshot(instance)
        run_hook(load_hook(CURRENT, oidc=False, neutral=True), instance)
        self.assertEqual(
            instance.node_selector["kubernetes.io/hostname"],
            GROUP_NODES["group_02"],
        )
        self.assertEqual(instance.environment["GROUP_ID"], "group_02")
        self.assertEqual(instance.volumes, before["volumes"])
        self.assertEqual(instance.volume_mounts, before["volume_mounts"])

    def test_reset_neutral_admin_configuration_is_unchanged(self):
        instance = spawner(username="admin", groups=())
        before = snapshot(instance)
        run_hook(load_hook(CURRENT, neutral=True), instance)
        self.assertEqual(snapshot(instance), before)

    def test_reset_neutral_rejects_missing_or_ambiguous_groups(self):
        for groups in ((), ("group_01", "group_02")):
            with self.subTest(groups=groups):
                instance = spawner(groups=groups)
                before = snapshot(instance)
                with self.assertRaises(RuntimeError):
                    run_hook(load_hook(CURRENT, neutral=True), instance)
                self.assertEqual(snapshot(instance), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
