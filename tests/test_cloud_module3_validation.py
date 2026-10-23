"""Local validation tests; no Kubernetes, delivery or runtime-readiness claims."""
from pathlib import Path
import shlex
import subprocess
import tempfile
import textwrap
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "roles/k8s_apps/templates"


class Module3ValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="module3-validation-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.state = self.root / "state"
        self.state.mkdir()
        self.environment = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            undefined=StrictUndefined,
        )
        self.environment.filters["bool"] = bool

        text = (TEMPLATES / "jhub-values.yaml.j2").read_text()
        marker = "    - name: seed-notebooks\n"
        self.assertEqual(text.count(marker), 1)
        container = text.split(marker, 1)[1]
        self.full_source = textwrap.dedent(
            container.split("      args:\n        - |\n", 1)[1]
            .split("      volumeMounts:\n", 1)[0]
        )

    def execute(self, enabled=False, mode="beginner", solutions="false",
                workshop_type="cloud-computing-soa", module="module3",
                full=False):
        settings = {
            "workshop_type": workshop_type, "workshop_module": module,
            "mode": mode, "solutions_released": solutions,
        }
        if full:
            for name, value in settings.items():
                (self.state / name).write_text(value + "\n")
            template = self.environment.from_string(self.full_source)
        else:
            template = self.environment.get_template(
                "workshop-hooks/cloud-module3-validation.sh.j2"
            )
        script = template.render(
            cloud_module3_delivery_enabled=enabled,
            cloud_module5_delivery_enabled=False,
        ).format(**{})
        script = script.replace("/home/jovyan", str(self.home))
        script = script.replace("state_dir=/state", "state_dir=" + str(self.state))
        assignments = "\n".join(
            name + "=" + shlex.quote(value) for name, value in settings.items()
        )
        return subprocess.run(
            ["sh", "-c", "set -eu\n" + assignments + "\n" + script],
            capture_output=True, text=True, timeout=15,
        )

    def test_invalid_states_fail_in_full_seeder_before_home_creation(self):
        cases = [
            ({}, "delivery is disabled"),
            ({"enabled": True, "mode": "invalid"}, "invalid Cloud Module 3 mode"),
            ({"enabled": True, "solutions": "invalid"},
             "invalid Cloud Module 3 solutions_released"),
            ({"enabled": True, "solutions": "true"},
             "solutions require intermediate or advanced mode"),
        ]
        for settings, expected in cases:
            with self.subTest(settings=settings):
                result = self.execute(full=True, **settings)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.home.exists())

    def test_valid_states_pass_validation_only_without_writes(self):
        for mode, solutions in (
            ("beginner", "false"), ("intermediate", "false"),
            ("intermediate", "true"), ("advanced", "false"), ("advanced", "true")
        ):
            with self.subTest(mode=mode, solutions=solutions):
                result = self.execute(
                    enabled=True, mode=mode, solutions=solutions
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.home.exists())

    def test_other_workshops_skip_module3_validation(self):
        for workshop_type, module in (
            ("cloud-computing-soa", "module2"),
            ("cloud-computing-soa", "module5"),
            ("introduction-to-ai", "module3"),
            ("federated-learning", "none"),
        ):
            with self.subTest(workshop_type=workshop_type, module=module):
                result = self.execute(
                    workshop_type=workshop_type, module=module,
                    mode="invalid", solutions="invalid",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main()
