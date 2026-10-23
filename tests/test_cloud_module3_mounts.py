"""Local mount-fragment checks; not full Helm or live pod validation."""
from pathlib import Path
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "roles/k8s_apps/templates"
TRACKS = ("beginner", "intermediate", "advanced", "solutions", "tests")


class Module3MountTests(unittest.TestCase):
    def setUp(self):
        self.environment = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            undefined=StrictUndefined,
        )
        self.environment.filters["bool"] = bool

    def render(self, kind, **settings):
        text = self.environment.get_template(
            "workshop-hooks/cloud-module3-" + kind + ".yaml.j2"
        ).render(**settings)
        return yaml.safe_load(text) or []

    def test_disabled_or_undefined_flag_adds_no_resources(self):
        for settings in ({}, {"cloud_module3_delivery_enabled": False}):
            with self.subTest(settings=settings):
                self.assertEqual(self.render("volumes", **settings), [])
                self.assertEqual(self.render("mounts", **settings), [])

    def test_enabled_sources_match_read_only_mounts(self):
        settings = {"cloud_module3_delivery_enabled": True}
        volumes = self.render("volumes", **settings)
        mounts = self.render("mounts", **settings)
        self.assertEqual(len(volumes), len(TRACKS))
        self.assertEqual(len(mounts), len(TRACKS))
        for track, volume, mount in zip(TRACKS, volumes, mounts):
            with self.subTest(track=track):
                name = "digitafrica-seed-cloud-computing-soa-module3-" + track
                self.assertEqual(volume, {
                    "name": name,
                    "configMap": {
                        "name": "digitafrica-notebooks-cloud-computing-soa-module3-"
                                + track,
                    },
                })
                self.assertEqual(mount, {
                    "name": name,
                    "mountPath": "/seed/cloud-computing-soa/module3/" + track,
                    "readOnly": True,
                })

    def test_mount_include_is_only_in_seed_container_mounts(self):
        text = (TEMPLATES / "jhub-values.yaml.j2").read_text()
        volume_include = (
            "{% include 'workshop-hooks/cloud-module3-volumes.yaml.j2' %}"
        )
        mount_include = (
            "{% include 'workshop-hooks/cloud-module3-mounts.yaml.j2' %}"
        )
        marker = "    - name: seed-notebooks\n"
        self.assertEqual(text.count(volume_include), 1)
        self.assertEqual(text.count(mount_include), 1)
        self.assertEqual(text.count(marker), 1)
        before, seed = text.split(marker, 1)
        self.assertIn(volume_include, before)
        self.assertNotIn(mount_include, before)
        script, mounts = seed.split("      volumeMounts:\n", 1)
        self.assertNotIn(mount_include, script)
        self.assertIn(mount_include, mounts)


if __name__ == "__main__":
    unittest.main()
