"""Focused mocked deployed checks, state updates and routing."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/workshops/cloud-computing-soa/module3-deployed.py"
spec = importlib.util.spec_from_file_location("module3_deployed", MODULE)
deployed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployed)


class Module3LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "namespace": "test", "operation": "publish", "mode": "beginner",
            "map": "fixture-map\n",
            "assets": {
                track: {"asset": hashlib.sha256(b"fixture\n").hexdigest()}
                for track in ("beginner", "intermediate", "advanced", "solutions", "tests")
            },
        }
        self.state = {
            "workshop_type": "cloud-computing-soa",
            "workshop_module": "module3", "mode": "advanced",
            "solutions_released": "false",
        }
        self.values = {"singleuser": {
            "initContainers": [{
                "name": "seed-notebooks",
                "args": ["cloud_module3_delivery_enabled=true"],
                "volumeMounts": [],
            }],
            "extraVolumes": [],
        }}
        for track in self.payload["assets"]:
            name = "digitafrica-notebooks-cloud-computing-soa-module3-" + track
            self.values["singleuser"]["extraVolumes"].append({
                "name": track, "configMap": {"name": name}
            })
            self.values["singleuser"]["initContainers"][0]["volumeMounts"].append({
                "name": track, "readOnly": True,
                "mountPath": "/seed/cloud-computing-soa/module3/" + track,
            })
        self.broken = ""
        self.patches = []

    def read(self, command):
        if command[0] == "helm":
            return self.values
        if "deployment" in command:
            return {"items": [{
                "metadata": {"generation": 1},
                "spec": {"replicas": 1},
                "status": {
                    "observedGeneration": 1, "updatedReplicas": 1,
                    "availableReplicas": 0 if self.broken == "rollout" else 1,
                },
            }]}
        name = command[command.index("configmap") + 1]
        if name == "digitafrica-workshop-state":
            return {"metadata": {"resourceVersion": "7"}, "data": self.state}
        if self.broken == "api":
            raise RuntimeError("Mock API unavailable.")
        data = {"asset_map_tsv": self.payload["map"], "asset": "fixture\n"}
        if self.broken == "asset":
            data["asset"] = "stale\n"
        if self.broken == "map":
            data["asset_map_tsv"] = "stale map\n"
        return {"metadata": {"name": name, "namespace": "test"}, "data": data}

    def run_command(self, command, **kwargs):
        self.patches.append(json.loads(command[-1]))
        return types.SimpleNamespace(returncode=0)

    def test_publication_updates_only_expected_state_and_clears_release(self):
        for mode in ("beginner", "intermediate", "advanced"):
            with self.subTest(mode=mode):
                self.payload["mode"] = mode
                self.patches.clear()
                deployed.execute(self.payload, self.read, self.run_command)
                self.assertEqual(len(self.patches), 1)
                self.assertEqual(self.patches[0][0], {
                    "op": "test", "path": "/metadata/resourceVersion", "value": "7"
                })
                updates = {
                    item["path"]: item["value"] for item in self.patches[0][1:]
                }
                self.assertEqual(updates, {
                    "/data/workshop_type": "cloud-computing-soa",
                    "/data/workshop_module": "module3", "/data/mode": mode,
                    "/data/solutions_released": "false",
                })

    def test_missing_delivery_prerequisites_never_patch(self):
        baseline = copy.deepcopy(self.values)
        for broken in ("api", "asset", "map", "rollout", "disabled", "mount", "volume"):
            with self.subTest(broken=broken):
                self.values = copy.deepcopy(baseline)
                self.broken = broken
                seed = self.values["singleuser"]["initContainers"][0]
                if broken == "disabled":
                    seed["args"] = ["cloud_module3_delivery_enabled=false"]
                if broken == "mount":
                    seed["volumeMounts"][0]["readOnly"] = False
                if broken == "volume":
                    self.values["singleuser"]["extraVolumes"] = []
                with self.assertRaises(RuntimeError):
                    deployed.execute(self.payload, self.read, self.run_command)
                self.assertEqual(self.patches, [])

    def test_release_rejects_wrong_type_module_or_beginner(self):
        self.payload.update(operation="release", mode="advanced")
        for key, value in (
            ("workshop_type", "introduction-to-ai"),
            ("workshop_module", "module2"),
            ("mode", "beginner"),
        ):
            with self.subTest(key=key):
                previous = self.state[key]
                self.state[key] = value
                with self.assertRaises(RuntimeError):
                    deployed.execute(self.payload, self.read, self.run_command)
                self.assertEqual(self.patches, [])
                self.state[key] = previous

    def test_release_requires_complete_solutions_and_only_sets_release_flag(self):
        self.payload.update(operation="release", mode="advanced")
        self.broken = "asset"
        with self.assertRaises(RuntimeError):
            deployed.execute(self.payload, self.read, self.run_command)
        self.assertEqual(self.patches, [])
        self.broken = ""
        deployed.execute(self.payload, self.read, self.run_command)
        self.assertEqual(self.patches[0][1:], [{
            "op": "add", "path": "/data/solutions_released", "value": "true"
        }])

    def test_release_for_the_active_intermediate_or_advanced_track(self):
        for mode in ("intermediate", "advanced"):
            with self.subTest(mode=mode):
                self.patches.clear()
                self.state["mode"] = mode
                self.payload.update(operation="release", mode=mode)
                deployed.execute(self.payload, self.read, self.run_command)
                self.assertEqual(self.patches[0][1:], [{
                    "op": "add", "path": "/data/solutions_released", "value": "true"
                }])

    def test_release_rejects_a_track_that_is_not_active_or_beginner(self):
        for active, requested in (
            ("intermediate", "advanced"), ("advanced", "intermediate"),
            ("beginner", "beginner"),
        ):
            with self.subTest(active=active, requested=requested):
                self.state["mode"] = active
                self.payload.update(operation="release", mode=requested)
                with self.assertRaises(RuntimeError):
                    deployed.execute(self.payload, self.read, self.run_command)
                self.assertEqual(self.patches, [])

    def test_check_is_read_only(self):
        self.payload["operation"] = "check"
        deployed.execute(self.payload, self.read, self.run_command)
        self.assertEqual(self.patches, [])

    def test_new_dispatch_branches_call_module_helpers(self):
        text = (ROOT / "scripts/workshops/organizer-main.sh").read_text()
        dispatch = text.split("# Dispatch only after", 1)[1]
        for action, function in (
            ("cloud-module3-readiness", "cloud_module3_check_activation_readiness"),
            ("cloud-module3-deployment-status", "cloud_module3_show_deployment_status"),
            ("cloud-module3-publish", "cloud_module3_activate"),
            ("cloud-module3-release-solutions", "cloud_module3_release_solutions"),
        ):
            with self.subTest(action=action):
                body = dispatch.split("  " + action + ")", 1)[1].split(";;", 1)[0]
                result = subprocess.run(
                    ["bash", "-c",
                     'cloud_module3_select_mode() { printf beginner; }\n'
                     + function + '() { printf "ROUTED"; }\n' + body],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("ROUTED", result.stdout)

    def test_reconciliation_opt_in_and_help_parse_without_deployment_context(self):
        entry = ROOT / "scripts/workshops/reconcile-workshop-applications.sh"
        result = subprocess.run(
            ["bash", str(entry), "--enable-cloud-module3-delivery", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--enable-cloud-module3-delivery", result.stdout)
        self.assertIn("no activation or exercise runtime", result.stdout)


if __name__ == "__main__":
    unittest.main()
