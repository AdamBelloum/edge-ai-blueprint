"""Offline isolated Livy asset-path tests; no staging or Docker execution."""
from pathlib import Path
import unittest

from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/big_data_spark_runtime"


class CandidateAssetPathTests(unittest.TestCase):
    def setUp(self):
        self.defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.env = Environment(
            loader=FileSystemLoader(str(ROLE / "templates")),
            undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
        self.env.filters["bool"] = to_bool
        self.template = self.env.get_template("compose.yaml.j2")
        self.tasks = yaml.safe_load((ROLE / "tasks/livy.yml").read_text())
        self.root = self.defaults["big_data_spark_runtime_host_path"]

    def settings(self, candidate=False, livy=True, gateway=True):
        settings = dict(self.defaults)
        settings.update(
            big_data_spark_worker_count=1,
            big_data_spark_client_enabled=True,
            big_data_spark_client_bind_ip="192.0.2.10",
            big_data_livy_enabled=livy,
            big_data_livy_access_enabled=gateway)
        if candidate:
            settings["big_data_livy_assets_host_path"] = self.root + "/livy-transition"
        return settings

    def render(self, **options):
        return yaml.safe_load(self.template.render(**self.settings(**options)))

    def test_default_livy_paths_remain_unchanged(self):
        livy = self.render()["services"]["spark-livy"]
        self.assertEqual(livy["build"]["context"], self.root + "/livy-build")
        sources = {mount["source"] for mount in livy["volumes"]}
        self.assertIn(self.root + "/livy.conf", sources)
        self.assertIn(self.root + "/livy-spark-defaults.conf", sources)

    def test_candidate_livy_uses_only_isolated_configuration_and_build_paths(self):
        livy = self.render(candidate=True)["services"]["spark-livy"]
        base = self.root + "/livy-transition"
        self.assertEqual(livy["build"]["context"], base + "/livy-build")
        sources = {mount["source"] for mount in livy["volumes"]}
        self.assertEqual(sources, {
            "/opt/digitafrica/big-data/spark/data",
            base + "/livy.conf", base + "/livy-spark-defaults.conf"})
        self.assertNotIn("ports", livy)
        for mount in livy["volumes"]:
            self.assertIs(mount["read_only"], True)
            self.assertIs(mount["bind"]["create_host_path"], False)

    def test_step1_service_definitions_and_networks_are_unchanged(self):
        direct = self.render(livy=False, gateway=False)
        candidate = self.render(candidate=True)
        for service in ("spark-master", "spark-worker-1", "spark-client"):
            self.assertEqual(direct["services"][service],
                             candidate["services"][service])
        self.assertEqual(direct["networks"], candidate["networks"])
        gateway = candidate["services"]["spark-livy-access"]
        client = candidate["services"]["spark-client"]
        self.assertEqual(gateway["ports"], client["ports"])
        self.assertEqual(
            {m["source"] for m in gateway["volumes"]},
            {self.root + "/client-access/host_key",
             self.root + "/client-access/login_key.pub"})

    def test_all_asset_writers_select_isolated_paths(self):
        paths = []
        settings = self.settings(candidate=True)
        for task in self.tasks:
            for module in ("ansible.builtin.file", "ansible.builtin.get_url",
                           "ansible.builtin.template", "ansible.builtin.copy"):
                if module in task:
                    arguments = task[module]
                    path = arguments.get("dest", arguments.get("path"))
                    paths.append(self.env.from_string(path).render(**settings))
        base = self.root + "/livy-transition"
        self.assertEqual(set(paths), {
            base + "/livy-build", base + "/livy-build/livy.zip",
            base + "/livy-build/Dockerfile", base + "/livy-build/.dockerignore",
            base + "/livy.conf", base + "/livy-spark-defaults.conf"})
        self.assertEqual(len(paths), 6)

    def test_asset_root_guard_rejects_arbitrary_paths(self):
        assertions = self.tasks[0]["ansible.builtin.assert"]["that"]
        guard = next(item for item in assertions
                     if "big_data_livy_assets_host_path" in item)
        evaluate = self.env.compile_expression(guard)
        self.assertTrue(evaluate(big_data_spark_runtime_host_path=self.root))
        for path, accepted in (
            (self.root, True), (self.root + "/livy-transition", True),
            ("/tmp/livy", False), (self.root + "/other", False)):
            with self.subTest(path=path):
                self.assertEqual(evaluate(
                    big_data_spark_runtime_host_path=self.root,
                    big_data_livy_assets_host_path=path), accepted)


if __name__ == "__main__":
    unittest.main()
