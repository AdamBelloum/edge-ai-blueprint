"""Execute isolated seed blocks in temporary directories, not live pods.

Ownership changes are mocked; real mkdir/cp/chmod and receipt writing run.
These tests do not validate full template rendering or Kubernetes startup.
"""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "workshop_assets/cloud_computing_soa/module5_openfaas"
TEMPLATE = ROOT / "roles/k8s_apps/templates/jhub-values.yaml.j2"


def marked_block(text, name):
    start = "          # BEGIN CLOUD MODULE 5 " + name
    end = "          # END CLOUD MODULE 5 " + name
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError("Missing or ambiguous seed block: " + name)
    return textwrap.dedent(text.split(start, 1)[1].split(end, 1)[0])


class OpenFaaSSeedingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="openfaas-seed-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.home = self.root / "home"
        self.workspace = self.home / "Cloud-Computing-SOA/Module-5"
        self.manifest = json.loads((MODULE / "delivery-manifest.json").read_text())
        self.paths = [entry["path"] for entry in self.manifest["files"]]
        for relative in self.paths:
            destination = self.source / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(MODULE / relative, destination)
        text = TEMPLATE.read_text()
        self.validation = marked_block(text, "VALIDATION")
        self.seed = marked_block(text, "SEEDING")
        start = "          copy_seed_file() {"
        end = "          mkdir -p \"$workspace\""
        if text.count(start) != 1 or text.count(end) != 1:
            raise RuntimeError("Missing or ambiguous helper extraction anchors")
        self.helpers = textwrap.dedent(start + text.split(start, 1)[1].split(end, 1)[0])
        self.environment = Environment(undefined=StrictUndefined)
        self.environment.filters["bool"] = bool

    def run_seed(self, enabled=True, mode="beginner", solutions="false",
                 workshop_type="cloud-computing-soa", module="module5"):
        validation = self.environment.from_string(self.validation).render(
            cloud_module5_delivery_enabled=enabled)
        seed = self.seed.replace("/seed/cloud-computing-soa/module5", str(self.source))
        seed = seed.replace("/home/jovyan", str(self.home))
        settings = {"workshop_type": workshop_type, "workshop_module": module,
                    "mode": mode, "solutions_released": solutions}
        assignments = "\n".join(key + "=" + shlex.quote(value)
                                for key, value in settings.items())
        # Mock only chown, so tests can run without root or UID 1000.
        script = "set -eu\nchown() { :; }\n" + assignments + "\n"
        script += validation + "\n" + self.helpers + "\n" + seed
        return subprocess.run(["bash", "-c", script], cwd=self.root,
                              capture_output=True, text=True, timeout=15)

    def test_disabled_delivery_rejects_before_workspace_creation(self):
        result = self.run_seed(enabled=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("delivery is disabled", result.stderr)
        self.assertFalse(self.home.exists())

    def test_unsupported_modes_and_solution_states_reject_before_writes(self):
        for mode, solutions in (("advanced", "false"), ("beginner", "true"),
                                ("invalid", "false"), ("beginner", "invalid")):
            with self.subTest(mode=mode, solutions=solutions):
                result = self.run_seed(mode=mode, solutions=solutions)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("requires beginner mode", result.stderr)
                self.assertFalse(self.home.exists())

    def test_each_missing_source_prevents_module5_workspace_writes(self):
        for relative in self.paths:
            with self.subTest(path=relative):
                source = self.source / relative
                content = source.read_bytes()
                source.unlink()
                try:
                    result = self.run_seed()
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("missing required Module 5 seed file: " + relative,
                                  result.stderr)
                    self.assertFalse(self.home.exists())
                finally:
                    source.write_bytes(content)

    def test_initial_delivery_copies_exact_allowlist_and_receipt(self):
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = "MODULE5_BEGINNER_SEED_RECEIPT.txt"
        delivered = {str(p.relative_to(self.workspace))
                     for p in self.workspace.rglob("*") if p.is_file()}
        self.assertEqual(delivered, set(self.paths) | {receipt})
        for relative in self.paths:
            self.assertEqual((self.workspace / relative).read_bytes(),
                             (self.source / relative).read_bytes())
        self.assertIn("provenance_file=SOURCE.md",
                      (self.workspace / receipt).read_text())
        self.assertIn("live readiness NOT VALIDATED", result.stdout)

    def test_repeat_delivery_preserves_edits_local_config_and_receipt(self):
        first = self.run_seed()
        self.assertEqual(first.returncode, 0, first.stderr)
        edited = self.workspace / "examples/greeting/handler.js"
        edited.write_text("participant modification\n")
        local = self.workspace / "config/lab.local.json"
        local.write_text("local configuration sentinel\n")
        receipt = self.workspace / "MODULE5_BEGINNER_SEED_RECEIPT.txt"
        original_receipt = receipt.read_bytes()
        missing_destination = self.workspace / "fixtures/weather-sample.json"
        missing_destination.unlink()
        second = self.run_seed()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(edited.read_text(), "participant modification\n")
        self.assertEqual(local.read_text(), "local configuration sentinel\n")
        self.assertEqual(receipt.read_bytes(), original_receipt)
        self.assertEqual(missing_destination.read_bytes(),
                         (self.source / "fixtures/weather-sample.json").read_bytes())

    def test_other_workshops_and_modules_skip_module5_blocks(self):
        for workshop_type, module in (("cloud-computing-soa", "module1"),
                                     ("cloud-computing-soa", "module2"),
                                     ("introduction-to-ai", "module3"),
                                     ("federated-learning", "none")):
            with self.subTest(workshop_type=workshop_type, module=module):
                result = self.run_seed(enabled=False, workshop_type=workshop_type,
                                       module=module)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
