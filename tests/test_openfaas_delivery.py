"""Local delivery mapping tests; no Kubernetes or live Pod validation."""
import json
from pathlib import Path
import re
import unittest

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "workshop_assets/cloud-computing-soa/module5-openfaas"
FLAG = "cloud_module5_delivery_enabled"
PATTERN = (
    r"{% if cloud_module5_delivery_enabled \| default\(false\) \| bool %}"
    r".*?{% endif %}"
)


class OpenFaaSDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((MODULE / "delivery-manifest.json").read_text())
        self.template = (ROOT / "roles/k8s_apps/templates/jhub-values.yaml.j2").read_text()
        self.all_blocks = re.findall(PATTERN, self.template, flags=re.DOTALL)
        # Projection assertions concern singleuser volumes and mounts only.
        marker = "\nsingleuser:\n"
        if self.template.count(marker) != 1:
            raise RuntimeError("Expected exactly one singleuser section.")
        singleuser = self.template.split(marker, 1)[1]
        self.blocks = re.findall(PATTERN, singleuser, flags=re.DOTALL)
        self.environment = Environment(undefined=StrictUndefined)
        # These isolated rendering tests pass actual booleans only.
        self.environment.filters["bool"] = bool

    def test_delivery_is_disabled_by_default(self):
        defaults = yaml.safe_load((ROOT / "roles/k8s_apps/defaults/main.yml").read_text())
        self.assertIs(defaults[FLAG], False)
        self.assertEqual(len(self.blocks), 2)
        for block in self.all_blocks:
            for settings in ({}, {FLAG: False}):
                self.assertFalse(self.environment.from_string(block).render(**settings).strip())

    def test_enabled_projection_matches_manifest(self):
        self.assertEqual(len(self.blocks), 2)
        volumes, mounts = [
            yaml.safe_load(self.environment.from_string(block).render(**{FLAG: True}))
            for block in self.blocks
        ]
        teaching_name = "digitafrica-seed-cloud-computing-soa-module5-beginner"
        runtime_name = "digitafrica-runtime-module5-node"
        self.assertEqual(
            {entry["name"] for entry in volumes},
            {teaching_name, runtime_name},
        )
        self.assertEqual(len(volumes), 2)
        volume = next(entry for entry in volumes if entry["name"] == teaching_name)
        runtime = next(entry for entry in volumes if entry["name"] == runtime_name)
        self.assertEqual(runtime, {
            "name": runtime_name,
            "configMap": {"name": runtime_name},
        })
        self.assertEqual(len(mounts), 1)
        mount = mounts[0]
        self.assertEqual(volume["configMap"]["name"], self.manifest["configmap_name"])
        self.assertEqual(volume["configMap"]["items"], self.manifest["files"])
        self.assertEqual(mount, {
            "name": volume["name"],
            "mountPath": "/seed/cloud-computing-soa/module5",
            "readOnly": True,
        })
        self.assertEqual(self.template.count("name: " + volume["name"]), 2)

    def test_manifest_paths_are_unique_safe_and_present(self):
        entries = self.manifest["files"]
        self.assertEqual(len(entries), 20)
        self.assertEqual(len({entry["key"] for entry in entries}), len(entries))
        self.assertEqual(len({entry["path"] for entry in entries}), len(entries))
        for entry in entries:
            with self.subTest(path=entry["path"]):
                self.assertRegex(entry["key"], r"^asset_[0-9]{3}$")
                relative = Path(entry["path"])
                self.assertFalse(relative.is_absolute())
                self.assertNotIn("..", relative.parts)
                self.assertTrue((MODULE / relative).is_file())
                self.assertNotIn(relative.parts[0], ("tests", "workspace", "workspaces"))
        self.assertNotIn("config/lab.local.json", {entry["path"] for entry in entries})

    def test_publication_include_is_gated(self):
        tasks = yaml.safe_load((ROOT / "roles/k8s_apps/tasks/install.yml").read_text())
        includes = [task for task in tasks
                    if task.get("ansible.builtin.include_tasks", {}).get("file")
                    == "openfaas-assets.yml"]
        self.assertEqual(len(includes), 1)
        include = includes[0]
        self.assertEqual(include["when"], FLAG + " | default(false) | bool")
        tags = ["workshop_assets", "workshop_application_reconciliation"]
        self.assertEqual(include["tags"], tags)
        self.assertEqual(include["ansible.builtin.include_tasks"]["apply"]["tags"], tags)

    def test_publication_tasks_match_allowlist_and_render_paths(self):
        tasks = yaml.safe_load((ROOT / "roles/k8s_apps/tasks/openfaas-assets.yml").read_text())
        self.assertEqual(len(tasks), 4)
        directories, copy, render, apply = tasks
        paths = [entry["path"] for entry in self.manifest["files"]]
        staging = "/opt/digitafrica/k8s-notebooks/cloud-computing-soa/module5/source"
        expected_directories = sorted({staging} | {
            str(Path(staging) / Path(p).parent) for p in paths
        })
        self.assertEqual(directories["loop"], expected_directories)
        self.assertEqual(copy["loop"], paths)
        for relative in paths:
            context = {"playbook_dir": "/checkout/playbooks", "item": relative}
            settings = copy["ansible.builtin.copy"]
            source = self.environment.from_string(settings["src"]).render(**context)
            destination = self.environment.from_string(settings["dest"]).render(**context)
            self.assertEqual(source, "/checkout/playbooks/../workshop_assets/"
                             "cloud-computing-soa/module5-openfaas/" + relative)
            self.assertEqual(destination, staging + "/" + relative)
        command = render["ansible.builtin.command"]
        context = {"digitafrica_deployment": {"digitafrica_namespace": "test-namespace"}}
        argv = [self.environment.from_string(arg).render(**context)
                for arg in command["argv"]]
        expected = ["k3s", "kubectl", "-n", "test-namespace", "create", "configmap",
                    self.manifest["configmap_name"]]
        expected += ["--from-file=" + entry["key"] + "=" + staging + "/" + entry["path"]
                     for entry in self.manifest["files"]]
        expected += ["--dry-run=client", "-o", "yaml"]
        self.assertEqual(argv, expected)
        self.assertIs(render["changed_when"], False)
        apply_command = apply["ansible.builtin.command"]
        apply_argv = [self.environment.from_string(arg).render(**context)
                      for arg in apply_command["argv"]]
        self.assertEqual(apply_argv, ["k3s", "kubectl", "-n", "test-namespace", "apply", "-f", "-"])
        rendered_stdin = self.environment.from_string(apply_command["stdin"]).render(
            cloud_module5_asset_configmap={"stdout": "test ConfigMap YAML"})
        self.assertEqual(rendered_stdin, "test ConfigMap YAML")
        expression = self.environment.compile_expression(apply["changed_when"])
        for output, expected_change in (("created", True), ("configured", True), ("unchanged", False)):
            self.assertEqual(expression(cloud_module5_asset_apply={"stdout": output}), expected_change)

    def test_manifest_supports_only_beginner_without_solution_release(self):
        self.assertEqual(self.manifest["schema_version"], 1)
        self.assertEqual(self.manifest["workshop_type"], "cloud-computing-soa")
        self.assertEqual(self.manifest["workshop_module"], "module5")
        self.assertEqual(self.manifest["mode"], "beginner")
        self.assertIs(self.manifest["solutions_released"], False)
        self.assertEqual(self.manifest["workspace_relative_path"], "Cloud-Computing-SOA/Module-5")


if __name__ == "__main__":
    unittest.main(verbosity=2)
