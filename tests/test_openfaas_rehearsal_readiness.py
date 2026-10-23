"""Mocked readiness validation; no Helm, Kubernetes or network access."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/workshops/cloud-computing-soa/openfaas/module-main.sh"


class RehearsalReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ["bash", "-c", '''
source "$1"
DIGITAFRICA_NAMESPACE=test-namespace
run_deployment_remote() { printf '%s\n' "$1"; }
cloud_module5_check_rehearsal_readiness
''', "_", str(MODULE)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.remote = result.stdout
        cls.check = cls.remote.split("<<'CHECK'\n", 1)[1].split("\nCHECK\n", 1)[0]

    def setUp(self):
        manifest = json.loads((ROOT / "workshop_assets/cloud-computing-soa/"
                               "module5-openfaas/delivery-manifest.json").read_text())
        self.assets = {"data": {
            item["key"]: "test asset" for item in manifest["files"]
        }}
        self.assets["data"]["asset_009"] = json.dumps({"live_test_enabled": False})
        self.values = {"singleuser": {
            "extraVolumes": [{
                "name": "module5",
                "configMap": {
                    "name": manifest["configmap_name"],
                    "items": manifest["files"],
                },
            }],
            "initContainers": [{
                "name": "seed-notebooks",
                "args": ["cloud_module5_delivery_enabled=true"],
                "volumeMounts": [{
                    "name": "module5",
                    "mountPath": "/seed/cloud-computing-soa/module5",
                    "readOnly": True,
                }],
            }],
        }}

    def validate(self, assets=None, values=None, failure=False):
        responses = [copy.deepcopy(assets if assets is not None else self.assets),
                     copy.deepcopy(values if values is not None else self.values)]
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(
                command, 1 if failure else 0,
                json.dumps(responses[len(calls) - 1]), "secret sentinel",
            )

        with patch.object(sys, "argv", ["check", "test-namespace"]), \
             patch.object(subprocess, "run", side_effect=fake_run), \
             contextlib.redirect_stdout(io.StringIO()):
            exec(compile(self.check, "<readiness-check>", "exec"),
                 {"__name__": "__main__"})
        return calls

    def test_remote_script_has_valid_bash_syntax(self):
        result = subprocess.run(["bash", "-n"], input=self.remote,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_complete_offline_configuration_passes(self):
        calls = self.validate()
        self.assertEqual(calls[0][:4], ["k3s", "kubectl", "-n", "test-namespace"])
        self.assertEqual(calls[1],
                         ["helm", "-n", "test-namespace",
                          "get", "values", "jhub", "-o", "json"])

    def test_missing_asset_rejects(self):
        del self.assets["data"]["asset_020"]
        with self.assertRaisesRegex(SystemExit, "assets are incomplete"):
            self.validate()

    def test_live_enabled_template_rejects(self):
        self.assets["data"]["asset_009"] = '{"live_test_enabled":true}'
        with self.assertRaisesRegex(SystemExit, "disable live execution"):
            self.validate()

    def test_disabled_seed_rejects(self):
        self.values["singleuser"]["initContainers"][0]["args"] = [
            "cloud_module5_delivery_enabled=false"
        ]
        with self.assertRaisesRegex(SystemExit, "disables Module 5"):
            self.validate()

    def test_missing_mount_rejects(self):
        self.values["singleuser"]["initContainers"][0]["volumeMounts"] = []
        with self.assertRaisesRegex(SystemExit, "seed mount is disabled"):
            self.validate()

    def test_missing_volume_rejects(self):
        self.values["singleuser"]["extraVolumes"] = []
        with self.assertRaisesRegex(SystemExit, "volume is absent"):
            self.validate()

    def test_command_failure_does_not_expose_output(self):
        with self.assertRaises(SystemExit) as raised:
            self.validate(failure=True)
        self.assertIn("Cannot retrieve", str(raised.exception))
        self.assertNotIn("secret sentinel", str(raised.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
