"""Local playbook regression tests; no Ansible tasks or services executed."""
from copy import deepcopy
from pathlib import Path
import unittest

from jinja2 import Environment
import yaml

ROOT = Path(__file__).resolve().parents[1]


class DirectDatasetPreflightTests(unittest.TestCase):
    def task(self, tasks, name):
        matches = [task for task in tasks if task.get("name") == name]
        self.assertEqual(len(matches), 1, name)
        return matches[0]

    def setUp(self):
        play = yaml.safe_load(
            (ROOT / "playbooks/participant-big-data-spark-direct.yml").read_text()
        )[0]
        self.prepare = self.task(
            play["tasks"], "Prepare participant runtime without starting services"
        )
        self.start = self.task(play["tasks"], "Start the staged Step 1 runtime only")
        self.inspect = self.task(
            self.start["block"], "Inspect required dataset paths before runtime startup"
        )
        self.guard = self.task(
            self.start["block"], "Require the staged dataset before any startup operation"
        )
        self.valid = [
            {"isdir": True, "islnk": False, "xoth": True},
            {"isreg": True, "islnk": False, "size": 1024, "roth": True},
        ]

    def passes(self, stats):
        context = {
            self.inspect["register"]: {
                "results": [{"stat": deepcopy(stat)} for stat in stats]
            }
        }
        conditions = self.guard["ansible.builtin.assert"]["that"]
        self.assertTrue(conditions)
        env = Environment()
        return all(bool(env.compile_expression(expr)(**context)) for expr in conditions)

    def test_asset_staging_order(self):
        tasks = self.prepare["block"]
        names = [
            "Require inactive project before preparation",
            "Stage the canonical participant assets and dataset before runtime preparation",
            "Stage existing Spark and optional Livy assets plus client",
        ]
        positions = [tasks.index(self.task(tasks, name)) for name in names]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(
            self.task(tasks, names[1])["ansible.builtin.include_role"]["name"],
            "big_data_workspace",
        )

    def test_staging_is_prepare_only(self):
        self.assertEqual(self.prepare["when"], "big_data_direct_action == 'prepare'")
        self.assertEqual(self.start["when"], "big_data_direct_action == 'start'")
        for task in self.start["block"]:
            for action in ("include_role", "copy", "file"):
                self.assertNotIn("ansible.builtin." + action, task)

    def test_readonly_guard_precedes_compose_and_startup(self):
        tasks = self.start["block"]
        self.assertEqual(tasks[:2], [self.inspect, self.guard])
        directory = "/opt/digitafrica/big-data/spark/data"
        self.assertEqual(
            self.inspect["loop"],
            [directory, directory + "/Bank_Personal_Loan_Modelling.csv"],
        )
        self.assertIs(self.inspect["ansible.builtin.stat"]["follow"], False)
        self.assertIs(self.inspect["changed_when"], False)
        for name in (
            "Read staged client-profile configuration",
            "Start only master, one worker and client without replacing active services",
        ):
            self.assertGreater(tasks.index(self.task(tasks, name)), 1)

    def test_valid_dataset_passes(self):
        self.assertTrue(self.passes(self.valid))

    def test_missing_paths_fail(self):
        for index in (0, 1):
            for missing in ({}, {"exists": False}):
                with self.subTest(index=index, missing=missing):
                    stats = deepcopy(self.valid)
                    stats[index] = missing
                    self.assertFalse(self.passes(stats))

    def test_symlinked_paths_fail(self):
        for index in (0, 1):
            with self.subTest(index=index):
                stats = deepcopy(self.valid)
                stats[index]["islnk"] = True
                self.assertFalse(self.passes(stats))

    def test_wrong_types_and_empty_csv_fail(self):
        for index, field, value in (
            (0, "isdir", False), (1, "isreg", False), (1, "size", 0),
        ):
            with self.subTest(index=index, field=field):
                stats = deepcopy(self.valid)
                stats[index][field] = value
                self.assertFalse(self.passes(stats))

    def test_inaccessible_paths_fail(self):
        for index, field in ((0, "xoth"), (1, "roth")):
            with self.subTest(index=index, field=field):
                stats = deepcopy(self.valid)
                stats[index][field] = False
                self.assertFalse(self.passes(stats))


if __name__ == "__main__":
    unittest.main()
