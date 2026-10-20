"""Local source-preflight tests; no Kubernetes or participant delivery."""
import csv
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / (
    "workshop_assets/cloud_computing_soa/module3_containerization_orchestration"
)
TRACKS = ("beginner", "advanced", "solutions", "tests")


class Module3PreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="module3-preflight-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.seed = self.root / "seed"
        self.home = self.root / "home"
        self.map_text = (ASSETS / "asset-map.tsv").read_text()
        self.rows = list(csv.reader(self.map_text.splitlines(), delimiter="\t"))
        environment = Environment(
            loader=FileSystemLoader(str(ROOT / "roles/k8s_apps/templates")),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )
        self.script = environment.get_template(
            "workshop-hooks/cloud-module3-preflight.sh.j2"
        ).render().format(**{})
        self.script = self.script.replace(
            "/seed/cloud-computing-soa/module3", str(self.seed)
        )
        self.write_maps(self.map_text)
        for track, key, relative in self.rows:
            source_root = ASSETS / ("shared/tests" if track == "tests" else track)
            shutil.copyfile(source_root / relative, self.seed / track / key)

    def write_maps(self, text):
        for track in TRACKS:
            directory = self.seed / track
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "asset_map_tsv").write_text(text)

    def run_hook(self, mode="beginner", solutions="false",
                 workshop_type="cloud-computing-soa", module="module3"):
        settings = {
            "workshop_type": workshop_type, "workshop_module": module,
            "mode": mode, "solutions_released": solutions,
        }
        assignments = "\n".join(
            name + "=" + shlex.quote(value) for name, value in settings.items()
        )
        result = subprocess.run(
            ["sh", "-c", "set -eu\n" + assignments + "\n" + self.script],
            cwd=self.root, capture_output=True, text=True, timeout=15,
        )
        self.assertFalse(self.home.exists())
        return result

    def test_real_map_and_sources_pass_for_valid_selections(self):
        for mode, solutions in (
            ("beginner", "false"), ("advanced", "false"), ("advanced", "true")
        ):
            with self.subTest(mode=mode, solutions=solutions):
                result = self.run_hook(mode=mode, solutions=solutions)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("source preflight passed", result.stdout)

    def test_each_selected_source_is_required(self):
        selected = {"advanced", "tests", "solutions"}
        for track, key, relative in self.rows:
            if track not in selected:
                continue
            with self.subTest(track=track, key=key):
                path = self.seed / track / key
                content = path.read_bytes()
                path.unlink()
                try:
                    result = self.run_hook(mode="advanced", solutions="true")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("missing Module 3 source", result.stderr)
                finally:
                    path.write_bytes(content)

    def test_unselected_sources_are_not_required(self):
        shutil.rmtree(self.seed / "advanced")
        shutil.rmtree(self.seed / "solutions")
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_or_inconsistent_maps_fail(self):
        for track in ("beginner", "tests"):
            path = self.seed / track / "asset_map_tsv"
            for replacement in (None, self.map_text + "\n"):
                with self.subTest(track=track, replacement=replacement is None):
                    if replacement is None:
                        path.unlink()
                    else:
                        path.write_text(replacement)
                    try:
                        result = self.run_hook()
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("Module 3", result.stderr)
                    finally:
                        path.write_text(self.map_text)

    def test_unsafe_or_malformed_maps_fail(self):
        first = self.rows[0]
        cases = [
            "advanced\tkey\n",
            "unknown\tkey\tfile.txt\n",
            "advanced\tbad/key\tfile.txt\n",
            "advanced\tasset_map_tsv\tfile.txt\n",
            "advanced\t" + "k" * 254 + "\tfile.txt\n",
        ]
        for relative in (
            "/absolute", "../escape", "a/../escape", "a/./file",
            "a//file", "a/", "file name", "keys/file", ".venv/file",
            "secrets/file", "a/.env", "a/private.PEM",
        ):
            cases.append("advanced\tkey\t" + relative + "\n")
        cases.extend([
            "\t".join(first) + "\n",
            first[0] + "\t" + first[1] + "\tother.txt\n",
            first[0] + "\tother_key\t" + first[2] + "\n",
        ])
        for bad_row in cases:
            with self.subTest(row=bad_row):
                self.write_maps(self.map_text + bad_row)
                result = self.run_hook()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Module 3 map row", result.stderr)
        self.write_maps(self.map_text)

    def test_configmap_style_source_symlinks_are_accepted(self):
        for track in TRACKS:
            directory = self.seed / track
            projection = directory / "..projection"
            projection.mkdir()
            for path in list(directory.iterdir()):
                if path == projection:
                    continue
                stored = projection / path.name
                path.rename(stored)
                path.symlink_to(Path("..projection") / path.name)
        result = self.run_hook(mode="advanced", solutions="true")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_other_workshops_skip_preflight_without_sources(self):
        shutil.rmtree(self.seed)
        result = self.run_hook(
            workshop_type="introduction-to-ai", module="module3"
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
