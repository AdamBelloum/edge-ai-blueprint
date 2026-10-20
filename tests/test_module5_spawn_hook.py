"""Rendered spawn-hook mock tests; no cluster, network or Node.js execution."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from test_spark_workspace_hook import CURRENT, load_hook, run_hook, spawner

ACTIVE = {
    "workshop_type": "cloud-computing-soa",
    "workshop_module": "module5",
    "mode": "beginner",
    "solutions_released": "false",
}
MOUNT = "digitafrica-runtime-module5-node"
PREFIX = ["/bin/sh", "/runtime/module5-node/module5-node-launch.sh"]


class FakeAPI:
    def __init__(self, data):
        self.data = data
        self.calls = []
        self.error = None

    async def read_namespaced_config_map(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(data=self.data)


def participant(data):
    instance = spawner()
    instance.init_containers.append({
        "name": "prepare-module5-node-runtime",
        "args": ["--delivery-enabled", "true"],
    })
    instance.cmd = ["custom-singleuser", "--debug"]
    instance.api = FakeAPI(deepcopy(data))
    return instance


class Module5SpawnTests(unittest.TestCase):
    def setUp(self):
        self.namespace = load_hook(CURRENT, module5=True)

    def test_active_participant_selects_runtime(self):
        instance = participant(ACTIVE)
        run_hook(self.namespace, instance)
        self.assertEqual(instance.cmd, PREFIX + ["custom-singleuser", "--debug"])
        self.assertTrue(instance.volume_mounts[MOUNT]["readOnly"])
        self.assertEqual(instance.environment["DIGITAFRICA_MODULE5_NODE_ENABLED"], "true")
        self.assertEqual(
            instance.environment["DIGITAFRICA_MODULE5_NODE_BIN"],
            self.namespace["MODULE5_NODE_BIN"],
        )
        self.assertNotIn("PATH", instance.environment)
        self.assertEqual(instance.api.calls, [{
            "name": "digitafrica-workshop-state",
            "namespace": "test-workshop",
        }])

    def test_other_workshop_keeps_original_launch(self):
        instance = participant({"workshop_type": "federated-learning"})
        run_hook(self.namespace, instance)
        self.assertEqual(instance.cmd, ["custom-singleuser", "--debug"])
        self.assertNotIn(MOUNT, instance.volume_mounts)
        self.assertNotIn("DIGITAFRICA_MODULE5_NODE_ENABLED", instance.environment)

    def test_administrator_without_group_does_not_read_state(self):
        instance = participant(ACTIVE)
        instance.user = SimpleNamespace(name="admin", groups=[])
        run_hook(self.namespace, instance)
        self.assertEqual(instance.api.calls, [])
        self.assertEqual(instance.cmd, ["custom-singleuser", "--debug"])
        self.assertNotIn(MOUNT, instance.volume_mounts)

    def test_unauthorized_accounts_do_not_read_state(self):
        for groups in ([], ["group_01", "group_02"]):
            with self.subTest(groups=groups):
                instance = participant(ACTIVE)
                instance.user.groups = [SimpleNamespace(name=g) for g in groups]
                with self.assertRaises(RuntimeError):
                    run_hook(self.namespace, instance)
                self.assertEqual(instance.api.calls, [])

    def test_api_failure_blocks_launch_selection(self):
        instance = participant(ACTIVE)
        instance.api.error = PermissionError("mock RBAC denial")
        with self.assertRaisesRegex(RuntimeError, "Cannot read current workshop state"):
            run_hook(self.namespace, instance)
        self.assertEqual(instance.cmd, ["custom-singleuser", "--debug"])
        self.assertNotIn(MOUNT, instance.volume_mounts)

    def test_invalid_active_state_rejects(self):
        for data in (
            {**ACTIVE, "mode": "advanced"},
            {**ACTIVE, "solutions_released": "true"},
        ):
            with self.subTest(data=data):
                instance = participant(data)
                with self.assertRaises(RuntimeError):
                    run_hook(self.namespace, instance)
                self.assertNotIn(MOUNT, instance.volume_mounts)

    def test_repeated_start_and_workshop_switch(self):
        instance = participant(ACTIVE)
        run_hook(self.namespace, instance)
        command = list(instance.cmd)
        run_hook(self.namespace, instance)
        self.assertEqual(instance.cmd, command)
        instance.api.data = {"workshop_type": "none"}
        run_hook(self.namespace, instance)
        self.assertEqual(instance.cmd, ["custom-singleuser", "--debug"])
        self.assertNotIn(MOUNT, instance.volume_mounts)
        self.assertNotIn("DIGITAFRICA_MODULE5_NODE_BIN", instance.environment)
        self.assertEqual(len(instance.api.calls), 3)

    def test_administrator_preparation_is_disabled(self):
        instance = participant(ACTIVE)
        instance.user = SimpleNamespace(name="admin", groups=[])
        run_hook(self.namespace, instance)
        self.assertEqual(instance.init_containers[-1]["args"][-1], "false")
        self.assertEqual(instance.api.calls, [])

    def test_participant_preparation_is_enabled(self):
        instance = participant(ACTIVE)
        run_hook(self.namespace, instance)
        self.assertEqual(instance.init_containers[-1]["args"][-1], "true")

    def test_api_failure_leaves_preparation_disabled(self):
        instance = participant(ACTIVE)
        instance.api.error = PermissionError("mock denial")
        with self.assertRaises(RuntimeError):
            run_hook(self.namespace, instance)
        self.assertEqual(instance.init_containers[-1]["args"][-1], "false")

    def test_model_preparation_preserves_shared_configuration(self):
        from kubernetes.client import V1Container

        instance = participant(ACTIVE)
        unrelated = V1Container(name="tutorial-seed", image="example:locked")
        preparation = V1Container(
            name="prepare-module5-node-runtime",
            args=["--delivery-enabled", "true"],
        )
        shared = [unrelated, preparation]
        before = deepcopy(shared)
        instance.init_containers = shared

        run_hook(self.namespace, instance)
        self.assertIs(instance.init_containers[0], unrelated)
        self.assertEqual(instance.init_containers[1]["args"][-1], "true")
        self.assertEqual(shared, before)

        instance.user = SimpleNamespace(name="admin", groups=[])
        run_hook(self.namespace, instance)
        self.assertEqual(instance.init_containers[1]["args"][-1], "false")
        self.assertEqual(instance.cmd, ["custom-singleuser", "--debug"])
        self.assertNotIn(MOUNT, instance.volume_mounts)
        self.assertEqual(len(instance.api.calls), 1)
        self.assertEqual(shared, before)

    def test_disabled_delivery_never_reads_api(self):
        instance = participant(ACTIVE)
        run_hook(load_hook(CURRENT, module5=False), instance)
        self.assertEqual(instance.api.calls, [])
        self.assertEqual(instance.cmd, ["custom-singleuser", "--debug"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
