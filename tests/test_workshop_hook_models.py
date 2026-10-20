#!/usr/bin/env python3
"""Real Kubernetes-model regression tests; no cluster or networking required.

Requires Jinja2 and kubernetes. Run:
    python3 tests/test_workshop_hook_models.py
"""
from copy import deepcopy
import unittest

from kubernetes.client import V1Container, V1EnvVar, V1VolumeMount

import test_spark_workspace_hook as helpers


def model_container():
    return V1Container(
        name="tutorial-seed",
        env=[V1EnvVar(name="EXISTING_SETTING", value="preserved")],
        volume_mounts=[
            V1VolumeMount(
                name="beginner-assets",
                mount_path="/seed/beginner",
                read_only=True,
            )
        ],
    )


class WorkshopModelTests(unittest.TestCase):
    def test_active_workshops_support_models_and_preserve_shared_input(self):
        for workshop in ("spark", "hpc"):
            with self.subTest(workshop=workshop):
                namespace = helpers.load_hook(
                    helpers.CURRENT,
                    enabled=workshop == "spark",
                    hpc=workshop == "hpc",
                    runtime=workshop == "hpc",
                )
                shared = [model_container()]
                before = deepcopy(shared)
                participant = helpers.spawner()
                participant.init_containers = shared
                helpers.run_hook(namespace, participant)

                volume = f"digitafrica-{workshop}-source"
                role_env = f"DIGITAFRICA_{workshop.upper()}_WORKSPACE_ROLE"
                seed_path = "/seed/big-data/spark" if workshop == "spark" else "/seed/hpc"

                self.assertEqual(shared, before)
                container = participant.init_containers[0]
                self.assertIsInstance(container, dict)
                self.assertIn(
                    {"name": "EXISTING_SETTING", "value": "preserved"},
                    container["env"],
                )
                self.assertIn(
                    {"name": role_env, "value": "participant"},
                    container["env"],
                )
                self.assertIn(
                    {"name": "beginner-assets", "mountPath": "/seed/beginner",
                     "readOnly": True},
                    container["volumeMounts"],
                )
                self.assertIn(
                    {"name": volume, "mountPath": seed_path, "readOnly": True},
                    container["volumeMounts"],
                )
                self.assertIn(volume, participant.volumes)
                self.assertFalse(any(
                    mount.get("name") == volume
                    for mount in participant.volume_mounts.values()
                ))

                admin = helpers.spawner(username="admin", groups=())
                admin.init_containers = shared
                helpers.run_hook(namespace, admin)
                self.assertEqual(shared, before)
                self.assertNotIn(volume, admin.volumes)
                self.assertIn(
                    {"name": role_env, "value": "administrator"},
                    admin.init_containers[0]["env"],
                )

    def test_neutral_and_staged_runtime_leave_models_untouched(self):
        for runtime in (False, True):
            with self.subTest(runtime=runtime):
                namespace = helpers.load_hook(helpers.CURRENT, runtime=runtime)
                instance = helpers.spawner()
                original = model_container()
                instance.init_containers = [original]
                helpers.run_hook(namespace, instance)
                self.assertIs(instance.init_containers[0], original)
                self.assertNotIn("configure_digitafrica_spark_source", namespace)
                self.assertNotIn("configure_digitafrica_hpc_source", namespace)

    def test_active_workshops_accept_mixed_container_representations(self):
        for workshop in ("spark", "hpc"):
            with self.subTest(workshop=workshop):
                namespace = helpers.load_hook(
                    helpers.CURRENT,
                    enabled=workshop == "spark",
                    hpc=workshop == "hpc",
                    runtime=workshop == "hpc",
                )
                instance = helpers.spawner()
                sidecar = {"name": "other-init", "image": "example:locked"}
                instance.init_containers = [model_container(), sidecar]
                helpers.run_hook(namespace, instance)
                self.assertEqual(instance.init_containers[1], sidecar)


if __name__ == "__main__":
    unittest.main(verbosity=2)
