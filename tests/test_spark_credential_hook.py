
"""Local credential-hook tests; no real keys, Kubernetes or networking."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from test_spark_workspace_hook import CURRENT, load_hook, run_hook, spawner

INIT = "digitafrica-spark-credentials"
SOURCE = "digitafrica-spark-direct-source"
CODE = "digitafrica-spark-direct-code"
HOME_INIT = "digitafrica-spark-home"

class CredentialHookTests(unittest.TestCase):
    def hook(self, credentials=True, neutral=False):
        return load_hook(CURRENT, enabled=True,
                         credentials=credentials, neutral=neutral)

    def participant(self, groups=("group_01",)):
        value = spawner(groups=groups)
        value.image = "example/notebook:1"
        value.fs_gid = 100
        return value

    def test_scoped_secret_and_unprivileged_init_only_mounts(self):
        value = self.participant()
        run_hook(self.hook(), value)
        self.assertEqual(value.volumes[SOURCE]["secret"]["secretName"],
                         "digitafrica-spark-direct-group-01")
        self.assertEqual(value.volumes[SOURCE]["secret"]["defaultMode"], 0o440)
        init = value.init_containers[-1]
        self.assertEqual(init["name"], INIT)
        self.assertEqual(init["securityContext"]["runAsUser"], 1000)
        self.assertTrue(init["securityContext"]["readOnlyRootFilesystem"])
        self.assertFalse({m["name"] for m in value.volume_mounts.values()} & {SOURCE, CODE})
        for other in value.init_containers[:-1]:
            self.assertFalse({m["name"] for m in other.get("volumeMounts", [])} & {SOURCE, CODE})

    def test_group_two_selection(self):
        value = self.participant(("group_02",))
        run_hook(self.hook(), value)
        self.assertEqual(value.volumes[SOURCE]["secret"]["secretName"],
                         "digitafrica-spark-direct-group-02")

    def test_repeat_does_not_duplicate_init(self):
        value = self.participant()
        hook = self.hook()
        run_hook(hook, value)
        first = deepcopy(value.init_containers)
        run_hook(hook, value)
        self.assertEqual(value.init_containers, first)
        self.assertEqual(sum(c["name"] == INIT for c in value.init_containers), 1)

    def test_admin_clears_prior_credentials(self):
        value = self.participant()
        hook = self.hook()
        run_hook(hook, value)
        value.user.name = "admin"
        value.user.groups = []
        run_hook(hook, value)
        self.assertNotIn(SOURCE, value.volumes)
        self.assertNotIn(CODE, value.volumes)
        self.assertFalse(any(c["name"] == INIT for c in value.init_containers))

    def test_rejected_user_clears_prior_credentials(self):
        value = self.participant()
        hook = self.hook()
        run_hook(hook, value)
        value.user.groups = []
        with self.assertRaises(RuntimeError):
            run_hook(hook, value)
        self.assertNotIn(SOURCE, value.volumes)
        self.assertFalse(any(c["name"] == INIT for c in value.init_containers))

    def test_opt_in_required(self):
        value = self.participant()
        run_hook(self.hook(credentials=False), value)
        self.assertNotIn(SOURCE, value.volumes)

    def test_neutral_delivery_disabled(self):
        self.assertFalse(self.hook(neutral=True)["SPARK_DIRECT_CREDENTIALS_ENABLED"])

    def test_shared_configuration_preserved(self):
        value = self.participant()
        shared = (value.init_containers, value.volumes)
        before = deepcopy(shared)
        run_hook(self.hook(), value)
        self.assertEqual(shared, before)

    def test_wrong_fs_group_rejected(self):
        value = self.participant()
        value.fs_gid = 999
        with self.assertRaises(RuntimeError):
            run_hook(self.hook(), value)
        self.assertNotIn(SOURCE, value.volumes)

    def test_include_boundaries_with_whitespace_trimming(self):
        from unittest.mock import patch
        import test_spark_workspace_hook as base
        original = base.Environment
        for lstrip in (False, True):
            with self.subTest(lstrip_blocks=lstrip):
                def environment(*args, **kwargs):
                    kwargs["lstrip_blocks"] = lstrip
                    return original(*args, **kwargs)
                with patch.object(base, "Environment", environment):
                    namespace = self.hook()
                    self.assertTrue(namespace["SPARK_DIRECT_CREDENTIALS_ENABLED"])

    def test_home_preparation_is_root_only_non_recursive_and_ordered(self):
        value = self.participant()
        run_hook(self.hook(), value)
        names = [c["name"] for c in value.init_containers]
        self.assertEqual(names.count(HOME_INIT), 1)
        self.assertLess(names.index(HOME_INIT), names.index(INIT))
        home = value.init_containers[names.index(HOME_INIT)]
        self.assertEqual(home["securityContext"]["runAsUser"], 0)
        self.assertFalse(home["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(home["securityContext"]["capabilities"],
                         {"drop": ["ALL"], "add": ["CHOWN", "FOWNER"]})
        script = home["args"][0]
        self.assertIn("chown 1000:100 /home/jovyan", script)
        self.assertNotIn(" -R", script)
        self.assertEqual({m["name"] for m in home["volumeMounts"]},
                         {"home", "digitafrica-workshop-state"})

    def test_home_preparation_skips_inactive_workshop(self):
        value = self.participant()
        run_hook(self.hook(), value)
        home = next(c for c in value.init_containers if c["name"] == HOME_INIT)
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "workshop_type"
            state.write_text("federated-learning")
            script = home["args"][0].replace("/state/workshop_type", str(state))
            result = subprocess.run(["sh", "-c", script], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("inactive", result.stdout)
            state.unlink()
            result = subprocess.run(["sh", "-c", script], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("inactive", result.stdout)

    def test_administrator_clears_home_preparation(self):
        value = self.participant()
        hook = self.hook()
        run_hook(hook, value)
        value.user.name = "admin"
        value.user.groups = []
        run_hook(hook, value)
        self.assertFalse(any(c["name"] == HOME_INIT for c in value.init_containers))

    def test_bootstrap_binding_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, source, helper = [root / n for n in ("state", "request", "helper.py")]
            state.write_text("big-data")
            helper.write_text('print("fixture helper reached")\n')
            script = self.hook()["SPARK_DIRECT_BOOTSTRAP"]
            for old, new in (
                ("/state/workshop_type", state),
                ("/run/spark-direct-source/request.json", source),
                ("/run/spark-direct-code/reconcile_credentials.py", helper),
            ):
                script = script.replace(old, str(new))
            for group, node, actual, expected in (
                ("group_01", "inventory-worker-a", "inventory-worker-a", 0),
                ("group_02", "inventory-worker-a", "inventory-worker-a", 2),
                ("group_01", "wrong-node", "inventory-worker-a", 2),
                ("group_01", "inventory-worker-a", "wrong-node", 2),
            ):
                with self.subTest(group=group, node=node, actual=actual):
                    source.write_text(json.dumps({
                        "operation": "apply", "group_id": group, "worker_node": node,
                    }))
                    env = dict(os.environ, GROUP_ID="group_01",
                        DIGITAFRICA_SPARK_EXPECTED_NODE="inventory-worker-a",
                        DIGITAFRICA_SPARK_POD_NODE=actual)
                    result = subprocess.run([sys.executable, "-c", script],
                        env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    if expected:
                        self.assertNotIn("fixture helper reached", result.stdout)

if __name__ == "__main__":
    unittest.main(verbosity=2)
