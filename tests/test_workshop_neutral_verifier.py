"""Offline neutral release verifier tests; no Helm or Kubernetes execution."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import textwrap
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "roles/k8s_apps/files/verify-neutral-jupyterhub.py"
SPEC = importlib.util.spec_from_file_location("neutral_verifier", PATH)
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


def render_hook():
    directory = ROOT / "roles/k8s_apps/templates"
    source = (directory / "jhub-values.yaml.j2").read_text()
    block = source.split(
        "    10-digitafrica-group-workspace: |\n", 1
    )[1].split("\n  config:", 1)[0]
    environment = Environment(
        loader=FileSystemLoader(str(directory)),
        undefined=StrictUndefined,
        trim_blocks=True,
    )
    environment.filters["to_json"] = json.dumps
    environment.filters["bool"] = bool
    return textwrap.dedent(environment.from_string(block).render(
        workshop_group_nodes={"group_01": "worker-a"},
        jupyterhub_admin_users=["admin"],
        oidc={"oidc_enabled": True},
        big_data_workspace_enabled=False,
        hpc_workspace_enabled=False,
        hpc_runtime_enabled=False,
        cloud_module5_delivery_enabled=False,
        workshop_reset_neutral=True,
        digitafrica_deployment={"digitafrica_namespace": "test-workshop"},
    ))


class NeutralVerifierTests(unittest.TestCase):
    def setUp(self):
        self.values = {
            "hub": {"extraConfig": {
                "10-digitafrica-group-workspace": render_hook(),
            }},
            "singleuser": {
                "initContainers": [{"name": "seed-notebooks"}],
                "storage": {"extraVolumes": []},
            },
        }
        self.state = {
            "metadata": {"resourceVersion": "10"},
            "data": {
                "workshop_type": "none",
                "workshop_module": "none",
                "mode": "beginner",
                "solutions_released": "false",
                "cleanup_status": "in_progress",
            },
        }
        self.deployments = {"items": [{
            "metadata": {"generation": 2},
            "spec": {
                "replicas": 1,
                "template": {"spec": {"containers": [{"name": "hub"}]}},
            },
            "status": {
                "observedGeneration": 2,
                "replicas": 1,
                "updatedReplicas": 1,
                "readyReplicas": 1,
                "availableReplicas": 1,
            },
        }]}

    def verify(self):
        VERIFIER.verify(self.values, self.state, self.deployments)

    def test_actual_neutral_render_passes(self):
        self.verify()

    def test_each_conflicting_state_field_is_rejected(self):
        original = deepcopy(self.state)
        for key in original["data"]:
            with self.subTest(key=key):
                self.state = deepcopy(original)
                self.state["data"][key] = "unexpected"
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_missing_or_invalid_hook_is_rejected(self):
        config = self.values["hub"]["extraConfig"]
        for hook in (None, "invalid python !"):
            with self.subTest(hook=hook):
                config["10-digitafrica-group-workspace"] = hook
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_enabled_source_flags_are_rejected(self):
        config = self.values["hub"]["extraConfig"]
        original = config["10-digitafrica-group-workspace"]
        for flag in ("BIG_DATA_WORKSPACE_ENABLED", "HPC_WORKSPACE_ENABLED"):
            with self.subTest(flag=flag):
                config["10-digitafrica-group-workspace"] = original.replace(
                    flag + " = False", flag + " = True"
                )
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_stale_handlers_and_data_mount_are_rejected(self):
        config = self.values["hub"]["extraConfig"]
        original = config["10-digitafrica-group-workspace"]
        additions = (
            "\ndef configure_digitafrica_spark_source():\n    pass\n",
            "\ndef configure_digitafrica_hpc_source():\n    pass\n",
            "\ndef configure_digitafrica_module5_node_launch():\n    pass\n",
            '\nvolume_name = "digitafrica-workshop"\n',
        )
        for addition in additions:
            with self.subTest(addition=addition):
                config["10-digitafrica-group-workspace"] = original + addition
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_missing_hook_registration_is_rejected(self):
        config = self.values["hub"]["extraConfig"]
        config["10-digitafrica-group-workspace"] = config[
            "10-digitafrica-group-workspace"
        ].replace(
            "c.KubeSpawner.pre_spawn_hook = configure_digitafrica_group_workspace",
            "c.KubeSpawner.pre_spawn_hook = None",
        )
        with self.assertRaises(RuntimeError):
            self.verify()

    def test_optional_volumes_are_rejected(self):
        for name in (
            "digitafrica-workshop",
            "digitafrica-spark-source",
            "digitafrica-hpc-source",
            "digitafrica-runtime-hpc",
            "digitafrica-runtime-module5-node",
            "digitafrica-seed-cloud-computing-soa-module3-tests",
            "digitafrica-seed-cloud-computing-soa-module5-beginner",
        ):
            with self.subTest(name=name):
                self.values["singleuser"]["storage"]["extraVolumes"] = [
                    {"name": name}
                ]
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_optional_init_containers_are_rejected(self):
        for name in (
            "prepare-hpc-home",
            "prepare-hpc-runtime",
            "prepare-module5-node-runtime",
        ):
            with self.subTest(name=name):
                self.values["singleuser"]["initContainers"] = [
                    {"name": "seed-notebooks"}, {"name": name}
                ]
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_absent_or_duplicate_seeder_is_rejected(self):
        for containers in (
            [],
            [{"name": "seed-notebooks"}, {"name": "seed-notebooks"}],
        ):
            with self.subTest(containers=containers):
                self.values["singleuser"]["initContainers"] = containers
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_incomplete_rollout_is_rejected(self):
        original = deepcopy(self.deployments)
        for field in original["items"][0]["status"]:
            with self.subTest(field=field):
                self.deployments = deepcopy(original)
                self.deployments["items"][0]["status"][field] = 0
                with self.assertRaises(RuntimeError):
                    self.verify()

    def test_missing_hub_or_deployments_is_rejected(self):
        for items in (
            [],
            [{
                **deepcopy(self.deployments["items"][0]),
                "spec": {
                    "replicas": 1,
                    "template": {"spec": {
                        "containers": [{"name": "proxy"}]
                    }},
                },
            }],
        ):
            with self.subTest(items=items):
                with self.assertRaises(RuntimeError):
                    VERIFIER.verify(self.values, self.state, {"items": items})

    def execute_with(self, final_state):
        responses = [
            deepcopy(self.state), deepcopy(self.values),
            deepcopy(self.deployments), final_state,
        ]
        calls = []

        def read(command):
            calls.append(command)
            return responses.pop(0)

        output = io.StringIO()
        with redirect_stdout(output):
            VERIFIER.execute("test-workshop", read=read)
        return calls, output.getvalue()

    def test_execute_is_read_only_and_reports_limits(self):
        calls, output = self.execute_with(deepcopy(self.state))
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0], calls[-1])
        self.assertEqual(calls[1][:5], [
            "helm", "-n", "test-workshop", "get", "values"
        ])
        self.assertTrue(all("get" in command for command in calls))
        self.assertIn("NOT VALIDATED", output)
        self.assertIn("Cleanup completion is not authorized", output)

    def test_concurrent_state_change_is_rejected(self):
        final = deepcopy(self.state)
        final["metadata"]["resourceVersion"] = "11"
        with self.assertRaises(RuntimeError):
            self.execute_with(final)

    def test_missing_resource_version_is_rejected(self):
        self.state["metadata"].pop("resourceVersion")
        with self.assertRaises(RuntimeError):
            self.execute_with(deepcopy(self.state))


class NeutralVerifierWiringTests(unittest.TestCase):
    def setUp(self):
        import yaml
        self.tasks = yaml.safe_load(
            (ROOT / "roles/k8s_apps/tasks/install.yml").read_text()
        )
        matches = [
            (index, task)
            for index, task in enumerate(self.tasks)
            if task.get("name") == "Verify neutral JupyterHub release after rollout"
        ]
        self.assertEqual(len(matches), 1)
        self.index, self.task = matches[0]

    def test_verifier_immediately_follows_rollout(self):
        self.assertEqual(
            self.tasks[self.index - 1]["name"],
            "Wait for all JupyterHub deployments from release to finish rolling out",
        )

    def test_verifier_is_reset_only_and_reconciliation_tagged(self):
        self.assertEqual(
            self.task["when"],
            "workshop_reset_neutral | default(false) | bool",
        )
        self.assertEqual(
            self.task["tags"], ["workshop_application_reconciliation"]
        )

    def test_verifier_uses_repository_script_and_explicit_kubeconfig(self):
        script = self.task["ansible.builtin.script"]
        self.assertEqual(script["executable"], "python3")
        self.assertIn(
            "role_path ~ '/files/verify-neutral-jupyterhub.py'",
            script["cmd"],
        )
        self.assertIn(
            "digitafrica_deployment.digitafrica_namespace | quote",
            script["cmd"],
        )
        self.assertEqual(self.task["environment"], {
            "KUBECONFIG": "/etc/rancher/k3s/k3s.yaml",
        })
        self.assertTrue(self.task["become"])

    def test_verification_failure_is_not_suppressed(self):
        self.assertFalse(self.task["changed_when"])
        for key in ("ignore_errors", "failed_when", "check_mode"):
            self.assertNotIn(key, self.task)


if __name__ == "__main__":
    unittest.main(verbosity=2)
