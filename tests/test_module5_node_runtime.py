"""Offline installer tests: no network, Node.js execution or deployment."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "roles/k8s_apps/files/prepare-module5-node-runtime.py"
CONFIG = ROOT / "roles/k8s_apps/files/module5-node-runtime.json"
spec = importlib.util.spec_from_file_location("module5_node_installer", INSTALLER)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class Response(io.BytesIO):
    def __init__(self, content, url):
        super().__init__(content)
        self.url = url

    def geturl(self):
        return self.url


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text())
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        self.state = Path(self.temporary.name) / "state"
        self.state.mkdir()
        self.platform_patch = patch.object(installer.platform, "system", return_value="Linux")
        self.platform_patch.start()
        self.addCleanup(self.platform_patch.stop)
        self.machine_patch = patch.object(installer.platform, "machine", return_value="x86_64")
        self.machine_patch.start()
        self.addCleanup(self.machine_patch.stop)

    def destination(self):
        return self.home / ".local/share/digitafrica/runtime/module5-node" / (
            f"node-{self.config['version']}-linux-x64"
        )

    def run_gate(self, enabled="true", workshop="cloud-computing-soa",
                 module="module5", mode="beginner", solutions="false"):
        for name, value in {
            "workshop_type": workshop, "workshop_module": module,
            "mode": mode, "solutions_released": solutions,
        }.items():
            (self.state / name).write_text(value + "\n")
        # An absent config makes accidental progress past a gate fail locally.
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run(
            [sys.executable, str(INSTALLER), "--config",
             str(self.state / "absent-config.json"), "--state-dir",
             str(self.state), "--delivery-enabled", enabled],
            env=env, capture_output=True, text=True, timeout=10,
        )

    def test_repository_config_is_valid(self):
        installer.validate_config(self.config)

    def test_invalid_config_rejects(self):
        for key, value in (("version", "latest"), ("platform", "linux-arm64"),
                           ("archive", "other.tar.gz"), ("url", "http://example.org"),
                           ("sha256", "bad"), ("npm_version", "latest")):
            with self.subTest(key=key):
                config = copy.deepcopy(self.config)
                config[key] = value
                with self.assertRaises(ValueError):
                    installer.validate_config(config)

    def test_disabled_delivery_skips_without_home_writes(self):
        result = self.run_gate(enabled="false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Delivery disabled", result.stdout)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_other_workshops_and_modules_skip(self):
        for workshop, module in (("none", "none"), ("federated-learning", "none"),
                                 ("cloud-computing-soa", "module2")):
            with self.subTest(workshop=workshop, module=module):
                result = self.run_gate(workshop=workshop, module=module)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("not active", result.stdout)
                self.assertEqual(list(self.home.iterdir()), [])

    def test_invalid_active_state_rejects_before_config_or_home_writes(self):
        for mode, solutions in (("advanced", "false"), ("beginner", "true")):
            with self.subTest(mode=mode, solutions=solutions):
                result = self.run_gate(mode=mode, solutions=solutions)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires beginner mode", result.stderr)
                self.assertNotIn("absent-config", result.stderr)
                self.assertEqual(list(self.home.iterdir()), [])

    def test_unsupported_architecture_rejects_before_download(self):
        with patch.object(installer.platform, "machine", return_value="aarch64"):
            with self.assertRaisesRegex(RuntimeError, "Linux x86_64"):
                installer.prepare(self.config, self.home, opener=self.fail)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_checksum_failure_never_extracts(self):
        with patch.object(installer.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
                installer.prepare(self.config, self.home,
                                  opener=lambda *a, **k: Response(b"bad", self.config["url"]))
            run.assert_not_called()
        self.assertFalse(self.destination().exists())
        self.assertEqual(list(self.destination().parent.iterdir()), [])

    def test_redirect_rejects_before_extraction(self):
        with patch.object(installer.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "redirect"):
                installer.prepare(self.config, self.home,
                                  opener=lambda *a, **k: Response(b"bad", "https://example.org/"))
            run.assert_not_called()
        self.assertFalse(self.destination().exists())

    def test_success_publishes_receipt_and_cache_skips_download(self):
        payload = b"mock archive; never extracted by a real command"
        config = dict(self.config, sha256=hashlib.sha256(payload).hexdigest())

        def fake_extract(command, **kwargs):
            self.assertEqual(command[:3], ["tar", "--no-same-owner", "-xzf"])
            staging = Path(command[-1])
            (staging / self.destination().name / "bin").mkdir(parents=True)
            return subprocess.CompletedProcess(command, 0)

        with patch.object(installer.subprocess, "run", side_effect=fake_extract) as run:
            with patch.object(installer, "check_binaries") as check:
                result = installer.prepare(config, self.home,
                                           opener=lambda *a, **k: Response(payload, config["url"]))
                self.assertEqual(result, self.destination() / "bin")
                run.assert_called_once()
                check.assert_called_once()
        receipt = self.destination() / ".digitafrica-runtime.json"
        self.assertEqual(json.loads(receipt.read_text()), config)
        with patch.object(installer, "check_binaries") as check:
            result = installer.prepare(config, self.home, opener=self.fail)
            check.assert_called_once_with(self.destination(), config)
            self.assertEqual(result, self.destination() / "bin")
        self.assertFalse((self.home / "Cloud-Computing-SOA").exists())

    def test_unmanaged_installation_is_not_overwritten(self):
        self.destination().mkdir(parents=True)
        sentinel = self.destination() / "keep.txt"
        sentinel.write_text("preserve")
        with self.assertRaisesRegex(RuntimeError, "refusing overwrite"):
            installer.prepare(self.config, self.home, opener=self.fail)
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_wrong_binary_version_rejects(self):
        with patch.object(installer.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, stdout="v0.0.0\n")):
            with self.assertRaisesRegex(RuntimeError, "Unexpected node version"):
                installer.check_binaries(self.destination(), self.config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
