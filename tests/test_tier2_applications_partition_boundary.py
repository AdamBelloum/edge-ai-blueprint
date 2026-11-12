"""Infrastructure deployment must not require organiser-prepared FL partitions."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = "fl_workshop_client_assets"
FLAG = "fl_stage_partitions"


def _load(rel):
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


def _role_name(entry):
    return entry.get("role") if isinstance(entry, dict) else entry


class TestTier2ApplicationsPartitionBoundary(unittest.TestCase):
    def test_tier2_applications_disables_partition_staging(self):
        plays = [
            p for p in _load("playbooks/tier2.yml")
            if any(_role_name(r) == ROLE for r in p.get("roles", []))
        ]
        self.assertEqual(len(plays), 1)
        self.assertIn("applications", plays[0].get("tags", []))
        entries = [
            r for r in plays[0]["roles"]
            if isinstance(r, dict) and r.get("role") == ROLE
        ]
        self.assertEqual(len(entries), 1)
        self.assertIs(entries[0].get("vars", {}).get(FLAG), False)

    def test_only_partition_tasks_are_gated_and_default_enabled(self):
        tasks = _load(f"roles/{ROLE}/tasks/main.yml")
        gated = [t for t in tasks if FLAG in str(t.get("when", ""))]
        partition = [t for t in tasks if "partition" in t["name"].lower()]
        self.assertEqual(len(partition), 2)
        self.assertEqual({t["name"] for t in gated}, {t["name"] for t in partition})
        for task in gated:
            self.assertIn("default(true)", str(task["when"]))
            self.assertIn("fl_partition_data", task["tags"])

    def test_organiser_staging_playbook_keeps_default(self):
        text = (ROOT / "playbooks/fl-workshop-stage-partitions.yml").read_text(
            encoding="utf-8")
        self.assertNotIn(FLAG, text)

    def test_no_other_playbook_disables_partition_staging(self):
        for path in (ROOT / "playbooks").glob("*.yml"):
            if path.name == "tier2.yml":
                continue
            self.assertNotIn(FLAG, path.read_text(encoding="utf-8"), path.name)


if __name__ == "__main__":
    unittest.main()
