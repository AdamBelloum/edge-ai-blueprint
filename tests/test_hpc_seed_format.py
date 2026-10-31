"""Offline seeding-command expansion checks; no cluster access or execution."""
import json
from pathlib import Path
import subprocess
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "roles/k8s_apps/templates"
TEMPLATE = TEMPLATES / "jhub-values.yaml.j2"


def render_seed(source, module5=False):
    section = source.split("    - name: seed-notebooks\n", 1)[1]
    script = section.split("        - |\n", 1)[1].split(
        "\n      volumeMounts:", 1
    )[0]
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    environment.filters["bool"] = bool
    environment.filters["to_json"] = json.dumps
    return environment.from_string(script).render(
        cloud_module5_delivery_enabled=module5,
        cloud_module3_delivery_enabled=True,
        big_data_workspace_enabled=True,
        big_data_spark_credentials_enabled=False,
        hpc_workspace_enabled=True,
        hpc_runtime_enabled=True,
    )


class HPCSeedFormatTests(unittest.TestCase):
    def test_complete_seed_command_expands_and_has_valid_shell_syntax(self):
        for module5 in (False, True):
            with self.subTest(module5=module5):
                rendered = render_seed(TEMPLATE.read_text(), module5)
                expanded = rendered.format(username="group_01")
                result = subprocess.run(
                    ["sh", "-n"],
                    input=expanded,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_original_unescaped_hpc_condition_is_rejected(self):
        source = TEMPLATE.read_text()
        escaped = """{{ '{{' }} [ "$workshop_module" = "openmp-01-basics" ] ||
               [ "$workshop_module" = "mpi-01-basics" ]; {{ '}}' }}; then"""
        original = """{ [ "$workshop_module" = "openmp-01-basics" ] ||
               [ "$workshop_module" = "mpi-01-basics" ]; }; then"""
        self.assertEqual(source.count(escaped), 1)
        broken = source.replace(escaped, original, 1)
        with self.assertRaises(KeyError):
            render_seed(broken).format(username="group_01")


if __name__ == "__main__":
    unittest.main()
