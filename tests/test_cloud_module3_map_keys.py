"""Local Module 3 map-key acceptance tests; no cluster access."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
HELPER = Path("scripts/workshops/cloud-computing-soa/module3-local.sh")
ASSETS = Path(
    "workshop_assets/cloud_computing_soa/module3_containerization_orchestration"
)


class Module3MapKeyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repository = Path(self.temporary.name)
        self.helper = self.repository / HELPER
        self.helper.parent.mkdir(parents=True)
        shutil.copy2(REPOSITORY / HELPER, self.helper)
        self.assets = self.repository / ASSETS
        self.rows = []
        for track in ("beginner", "advanced", "solutions", "tests"):
            folder = "shared/tests" if track == "tests" else track
            directory = self.assets / folder
            directory.mkdir(parents=True)
            (directory / "example.txt").write_text("Teaching fixture\n")
            (directory / "second.txt").write_text("Second fixture\n")
            self.rows.append([track, "example_txt", "example.txt"])

    def run_check(self):
        content = "".join("\t".join(row) + "\n" for row in self.rows)
        (self.assets / "asset-map.tsv").write_text(content)
        return subprocess.run(
            ["bash", str(self.helper), "check", "beginner"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def assert_rejected(self, message):
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertNotIn("PASS: selected assets", result.stdout)

    def test_valid_keys(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_253_character_key_is_accepted(self):
        self.rows[0][1] = "a" * 253
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_key_characters(self):
        for key in ("bad/key", "bad key", "bad:key", "café"):
            with self.subTest(key=key):
                self.rows[0][1] = key
                self.assert_rejected("invalid ConfigMap key")

    def test_empty_key(self):
        self.rows[0][1] = ""
        self.assert_rejected("invalid ConfigMap key")

    def test_oversized_key(self):
        self.rows[0][1] = "a" * 254
        self.assert_rejected("exceeds 253 characters")

    def test_reserved_map_key(self):
        self.rows[0][1] = "asset_map_tsv"
        self.assert_rejected("reserved for the map")

    def test_duplicate_key_with_different_destination(self):
        self.rows.append(["beginner", "example_txt", "second.txt"])
        self.assert_rejected("duplicate destination or asset key")

    def test_duplicate_destination_with_different_key(self):
        self.rows.append(["beginner", "another_key", "example.txt"])
        self.assert_rejected("duplicate destination or asset key")


    def test_oversized_selected_track(self):
        (self.assets / "beginner/example.txt").write_text("x" * 204801)
        self.assert_rejected("beginner: ConfigMap exceeds")

    def test_oversized_unselected_track(self):
        (self.assets / "solutions/example.txt").write_text("x" * 204801)
        self.assert_rejected("solutions: ConfigMap exceeds")

    def test_shared_tests_budget(self):
        (self.assets / "shared/tests/example.txt").write_text("x" * 204801)
        self.assert_rejected("tests: ConfigMap exceeds")

    def test_json_escaping_counts_toward_budget(self):
        # Raw content is below budget; JSON escaping pushes it over.
        (self.assets / "beginner/example.txt").write_text("\\" * 110000)
        self.assert_rejected("beginner: ConfigMap exceeds")

    def test_exact_serialized_budget_boundary(self):
        import json

        map_text = "".join("\t".join(row) + "\n" for row in self.rows)
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": (
                    "digitafrica-notebooks-cloud-computing-soa-module3-beginner"
                ),
                "namespace": "n" * 63,
            },
            "data": {"asset_map_tsv": map_text, "example_txt": ""},
        }
        overhead = len(
            json.dumps(manifest, ensure_ascii=True).encode("utf-8")
        ) + 1
        source = self.assets / "beginner/example.txt"
        source.write_text("x" * (204800 - overhead))
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

        source.write_text("x" * (204800 - overhead + 1))
        self.assert_rejected("beginner: ConfigMap exceeds")


if __name__ == "__main__":
    unittest.main(verbosity=2)
