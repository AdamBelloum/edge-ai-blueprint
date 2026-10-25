"""Offline checks for Introduction to AI notebook runtime wiring."""

from pathlib import Path
import subprocess
import unittest

import yaml
from jinja2 import Environment, StrictUndefined
from ansible.plugins.filter.core import to_bool


ROOT = Path(__file__).resolve().parents[1]


class IntroductionToAIRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defaults = yaml.safe_load(
            (ROOT / "roles/k8s_apps/defaults/main.yml").read_text()
        )
        cls.profiles = cls.defaults["workshop_notebook_runtime_profiles"]
        cls.template = (
            ROOT / "roles/k8s_apps/templates/jhub-values.yaml.j2"
        ).read_text()

    def render_runtime(self, enabled):
        comment = self.template.index(
            "    # Select and cache the pinned runtime profile"
        )
        start = self.template.rfind(
            "{% if workshop_notebook_runtime.enabled", 0, comment
        )
        self.assertGreaterEqual(start, 0)
        end = self.template.index("    - name: seed-notebooks", comment)
        fragment = self.template[start:end]
        environment = Environment(undefined=StrictUndefined)
        environment.filters["bool"] = to_bool
        return environment.from_string(fragment).render(
            workshop_notebook_runtime={
                "enabled": enabled,
                "image_name": "quay.io/jupyterhub/k8s-singleuser-sample",
                "image_tag": "4.4.2",
            },
            workshop_notebook_runtime_profiles=self.profiles,
        )

    def test_profile_registration_and_sources(self):
        profile = self.profiles["introduction-to-ai"]
        self.assertEqual(
            profile["configmap_name"], "digitafrica-runtime-introduction-to-ai"
        )
        self.assertEqual(
            profile["requirements_source"],
            "workshop_assets/introduction-to-ai/runtime/requirements.lock",
        )
        for name, item in self.profiles.items():
            with self.subTest(profile=name):
                self.assertTrue((ROOT / item["requirements_source"]).is_file())

    def test_ml_requirements_are_pinned_and_complete(self):
        path = ROOT / self.profiles["introduction-to-ai"]["requirements_source"]
        pins = {}
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self.assertEqual(line.count("=="), 1, line)
            name, version = line.split("==")
            name = name.lower().replace("_", "-")
            self.assertTrue(version, line)
            self.assertNotIn(name, pins)
            pins[name] = version
        expected = {
            "numpy", "matplotlib", "scikit-learn", "scipy", "joblib",
            "threadpoolctl", "contourpy", "cycler", "fonttools", "kiwisolver",
            "packaging", "pillow", "pyparsing", "python-dateutil", "six",
        }
        self.assertEqual(set(pins), expected)

    def test_enabled_runtime_mounts_all_profiles(self):
        containers = yaml.safe_load(self.render_runtime(True))
        self.assertEqual(len(containers), 1)
        runtime = containers[0]
        self.assertEqual(runtime["name"], "prepare-workshop-runtime")
        mounts = {
            item["name"]: item["mountPath"]
            for item in runtime["volumeMounts"]
        }
        for name in self.profiles:
            self.assertEqual(
                mounts[f"digitafrica-runtime-{name}"], f"/runtime/{name}"
            )
        self.assertEqual(mounts["home"], "/home/jovyan")
        script = runtime["args"][0]
        self.assertIn('requirements="/runtime/$workshop_type/requirements.lock"', script)
        self.assertIn(
            'python -m pip install --user --no-cache-dir --requirement "$requirements"',
            script,
        )

    def test_rendered_runtime_shell_syntax(self):
        runtime = yaml.safe_load(self.render_runtime(True))[0]
        result = subprocess.run(
            ["bash", "-n"], input=runtime["args"][0],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_disabled_runtime_emits_no_install_container(self):
        self.assertIsNone(yaml.safe_load(self.render_runtime(False)))

    def test_tier_enablement_is_unchanged(self):
        for tier, enabled in (("tier1", False), ("tier2", True)):
            plays = yaml.safe_load((ROOT / f"playbooks/{tier}.yml").read_text())
            runtime = plays[0]["vars"]["workshop_notebook_runtime"]
            with self.subTest(tier=tier):
                self.assertIs(runtime["enabled"], enabled)

    def test_beginner_entry_names_existing_notebook(self):
        folder = ROOT / (
            "workshop_assets/introduction-to-ai/"
            "module2-foundations-of-ml/beginner"
        )
        readme = (folder / "00_START_HERE.md").read_text()
        notebook = "02_foundations_of_ml_beginner.ipynb"
        self.assertIn(f"`{notebook}`", readme)
        self.assertTrue((folder / notebook).is_file())
        self.assertNotIn("01_foundations_of_ml_beginner.ipynb", readme)


if __name__ == "__main__":
    unittest.main()
