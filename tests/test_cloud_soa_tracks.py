"""Cloud Computing SOA Modules 1-3: beginner, intermediate and advanced tracks.

Runs the complete JupyterHub seeder with local sh, temporary paths and a
mocked chown, for every track and for solution release. The Module 2 seed
files are built from the ConfigMap commands in install.yml, so the seeder and
the staging must agree on every key. Also runs the staging prune steps and the
organiser's solution-release guard against a fake k3s.

No Kubernetes, Helm or network access.
"""
import csv
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOA = ROOT / "workshop_assets/cloud-computing-soa"
MODULE_DIRECTORIES = {
    "module1": SOA / "module1-rest-api",
    "module2": SOA / "module2-microservices",
    "module3": SOA / "module3-containerization-orchestration",
}
MODES = ("beginner", "intermediate", "advanced")
RECEIPT = re.compile(r"MODULE\d_[A-Z]+_(SEED|RELEASE)_RECEIPT\.txt|MODULE3_DELIVERY_RECEIPT\.txt")


def module2_configmaps():
    """Track -> {ConfigMap key: path in module2-microservices} from install.yml."""
    text = (ROOT / "roles/k8s_apps/tasks/install.yml").read_text(encoding="utf-8")
    prefix = "create configmap digitafrica-notebooks-cloud-computing-soa-module2-"
    configmaps = {}
    for block in text.split(prefix)[1:]:
        track = block.split(None, 1)[0]
        block = block.split("--dry-run", 1)[0]
        configmaps[track] = dict(re.findall(r'--from-file=(\w+)="\$root/([^"]+)"', block))
    return configmaps


class SeederTracksTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        text = (ROOT / "roles/k8s_apps/templates/jhub-values.yaml.j2").read_text()
        container = text.split("    - name: seed-notebooks\n", 1)[1]
        source = textwrap.dedent(container.split(
            "      args:\n        - |\n", 1)[1].split("      volumeMounts:\n", 1)[0])
        environment = Environment(
            loader=FileSystemLoader(str(ROOT / "roles/k8s_apps/templates")),
            undefined=StrictUndefined,
        )
        environment.filters["bool"] = bool
        # KubeSpawner formats init-container arguments with str.format, so the
        # rendered script is formatted too: a stray brace would fail here.
        self.script = environment.from_string(source).render(
            cloud_module3_delivery_enabled=True,
            cloud_module5_delivery_enabled=False,
        ).format(**{})

        temporary = tempfile.TemporaryDirectory(prefix="cloud-soa-tracks-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.state = self.root / "state"
        self.state.mkdir()
        self.seed = self.root / "seed/cloud-computing-soa"
        self.stage_module1()
        self.stage_module2()
        self.stage_module3()

    def stage_module1(self):
        # ConfigMaps built from the staged folders: one key per file.
        for track in MODES + ("solutions", "tests"):
            folder = "shared/tests" if track == "tests" else track
            source = MODULE_DIRECTORIES["module1"] / folder
            destination = self.seed / "module1" / track
            destination.mkdir(parents=True)
            for path in source.iterdir():
                if path.is_file():
                    shutil.copyfile(path, destination / path.name)

    def stage_module2(self):
        self.module2_keys = module2_configmaps()
        self.assertEqual(set(self.module2_keys), set(MODES) | {"solutions", "tests"})
        for track, keys in self.module2_keys.items():
            destination = self.seed / "module2" / track
            destination.mkdir(parents=True)
            for key, relative in keys.items():
                shutil.copyfile(MODULE_DIRECTORIES["module2"] / relative, destination / key)

    def stage_module3(self):
        directory = MODULE_DIRECTORIES["module3"]
        map_text = (directory / "asset-map.tsv").read_text(encoding="utf-8")
        self.module3_rows = list(csv.reader(map_text.splitlines(), delimiter="\t"))
        for track in MODES + ("solutions", "tests"):
            (self.seed / "module3" / track).mkdir(parents=True)
            (self.seed / "module3" / track / "asset_map_tsv").write_text(map_text)
        for track, key, relative in self.module3_rows:
            folder = "shared/tests" if track == "tests" else track
            shutil.copyfile(directory / folder / relative, self.seed / "module3" / track / key)

    def run_seed(self, module, mode, released="false"):
        settings = {"workshop_type": "cloud-computing-soa", "workshop_module": module,
                    "mode": mode, "solutions_released": released}
        for name, value in settings.items():
            (self.state / name).write_text(value + "\n")
        script = self.script.replace("/home/jovyan", str(self.home))
        script = script.replace("/seed", str(self.root / "seed"))
        script = script.replace("state_dir=/state", "state_dir=" + str(self.state))
        return subprocess.run(["sh", "-c", "chown() { :; }\n" + script],
                              cwd=self.root, capture_output=True, text=True, timeout=60)

    def delivered(self, module):
        workspace = self.home / "Cloud-Computing-SOA" / ("Module-" + module[-1])
        return {
            path.relative_to(workspace).as_posix(): path
            for path in workspace.rglob("*")
            if path.is_file() and not RECEIPT.fullmatch(path.name)
        }

    def expected_module1(self, mode, released):
        expected = {}
        for track in (mode, "tests") + (("solutions",) if released else ()):
            folder = "shared/tests" if track == "tests" else track
            for path in (MODULE_DIRECTORIES["module1"] / folder).iterdir():
                if path.is_file():
                    expected[f"{track}/{path.name}"] = path
        return expected

    def expected_module2(self, mode, released):
        directory = MODULE_DIRECTORIES["module2"]
        # The module README and .gitignore describe the design of the other
        # tracks: the advanced track gets them only with the solutions.
        root_files = ["requirements.lock"]
        if mode != "advanced" or released:
            root_files += ["README.md", ".gitignore"]
        expected = {name: directory / name for name in root_files}
        tracks = (mode, "tests") + (("solutions",) if released else ())
        for track in tracks:
            folder = "shared/tests" if track == "tests" else track
            for path in (directory / folder).rglob("*"):
                if path.is_file():
                    expected[f"{track}/{path.relative_to(directory / folder).as_posix()}"] = path
        return expected

    def expected_module3(self, mode, released):
        directory = MODULE_DIRECTORIES["module3"]
        tracks = (mode, "tests") + (("solutions",) if released else ())
        return {
            f"{track}/{relative}": directory / ("shared/tests" if track == "tests" else track) / relative
            for track, _, relative in self.module3_rows if track in tracks
        }

    def assert_delivery(self, module, mode, released):
        expected = getattr(self, "expected_" + module)(mode, released)
        actual = self.delivered(module)
        self.assertEqual(sorted(actual), sorted(expected))
        for relative, path in actual.items():
            self.assertEqual(path.read_bytes(), expected[relative].read_bytes(), relative)

    def test_every_track_delivers_exactly_its_files(self):
        for module in MODULE_DIRECTORIES:
            for mode in MODES:
                with self.subTest(module=module, mode=mode):
                    shutil.rmtree(self.home, ignore_errors=True)
                    result = self.run_seed(module, mode)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assert_delivery(module, mode, released=False)

    def test_solutions_are_released_for_intermediate_and_advanced(self):
        for module in MODULE_DIRECTORIES:
            for mode in ("intermediate", "advanced"):
                with self.subTest(module=module, mode=mode):
                    shutil.rmtree(self.home, ignore_errors=True)
                    self.assertEqual(self.run_seed(module, mode).returncode, 0)
                    result = self.run_seed(module, mode, released="true")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assert_delivery(module, mode, released=True)

    def test_beginner_release_and_unknown_modes_are_refused(self):
        for module in MODULE_DIRECTORIES:
            for mode, released, message in (
                ("beginner", "true", "solutions require"),
                ("expert", "false", "mode"),
            ):
                with self.subTest(module=module, mode=mode):
                    shutil.rmtree(self.home, ignore_errors=True)
                    result = self.run_seed(module, mode, released)
                    self.assertEqual(result.returncode, 1, result.stdout)
                    self.assertIn(message, result.stderr)
                    self.assertFalse((self.home / "Cloud-Computing-SOA" / ("Module-" + module[-1]) / "solutions").exists())

    def test_participant_changes_survive_a_second_spawn(self):
        result = self.run_seed("module2", "intermediate")
        self.assertEqual(result.returncode, 0, result.stderr)
        edited = self.home / "Cloud-Computing-SOA/Module-2/intermediate/auth_service/auth.py"
        edited.write_text("participant work\n")
        result = self.run_seed("module2", "intermediate", released="true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(edited.read_text(), "participant work\n")


class StagingPruneTests(unittest.TestCase):
    """The prune steps remove staged files whose source is gone."""

    def python_of(self, path, task_name):
        tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
        found = [task for task in self.flatten(tasks) if task.get("name") == task_name]
        self.assertEqual(len(found), 1, task_name)
        shell = found[0]["ansible.builtin.shell"]
        return shell.split("<<'PYTHON_PRUNE'\n", 1)[1].split("PYTHON_PRUNE", 1)[0]

    def flatten(self, tasks):
        for task in tasks or []:
            yield task
            yield from self.flatten(task.get("block"))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cloud-soa-prune-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_module1_and_module2_prune_keeps_current_and_generated_files(self):
        code = self.python_of(
            ROOT / "roles/k8s_apps/tasks/install.yml",
            "Remove staged Cloud Computing SOA Module 1 and 2 files that the repository no longer has",
        )
        stage = self.root / "advanced"
        (stage / "auth_service").mkdir(parents=True)
        for name in ("README.md", "app.py", "WORKSHOP_VERSION.json", "auth_service/auth.py"):
            (stage / name).write_text("x\n")
        result = subprocess.run(["python3", "-", str(stage), '["README.md"]'], input=code,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        remaining = sorted(path.relative_to(stage).as_posix() for path in stage.rglob("*"))
        self.assertEqual(remaining, ["README.md", "WORKSHOP_VERSION.json"])

    def test_module3_flat_staging_preserves_separate_nested_source_tree(self):
        task_path = ROOT / "roles/k8s_apps/tasks/cloud-soa-module3-assets.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        deployed_root = (
            "/opt/digitafrica/k8s-notebooks/cloud-computing-soa/module3/mapped-v1"
        )
        self.assertEqual(tasks[0]["ansible.builtin.file"]["path"], deployed_root)
        self.assertEqual(
            tasks[1]["vars"]["cloud_module3_stage_root"], deployed_root
        )
        self.assertIn(
            "root=" + deployed_root + "\n",
            tasks[-1]["ansible.builtin.shell"],
        )

        legacy = self.root / "source/advanced/containerization/auth.py"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("preserve existing nested content\n")

        stage = self.root / "mapped-v1"
        (stage / "advanced").mkdir(parents=True)
        (stage / "advanced/kept").write_text("mapped asset\n")
        (stage / "advanced/stale").write_text("obsolete flat asset\n")
        (stage / "asset-map.tsv").write_text("advanced\tkept\tREADME.md\n")

        code = self.python_of(
            task_path, "Remove staged Module 3 files that are no longer mapped"
        )
        for attempt in range(2):
            result = subprocess.run(
                ["python3", "-", str(stage)], input=code,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                legacy.read_text(), "preserve existing nested content\n"
            )
            self.assertEqual(
                (stage / "advanced/kept").read_text(), "mapped asset\n"
            )
            self.assertFalse((stage / "advanced/stale").exists())
            if attempt == 1:
                self.assertEqual(result.stdout, "")

    def test_module3_prune_keeps_only_mapped_keys(self):
        code = self.python_of(
            ROOT / "roles/k8s_apps/tasks/cloud-soa-module3-assets.yml",
            "Remove staged Module 3 files that are no longer mapped",
        )
        stage = self.root / "source"
        for track, key in (("advanced", "kept"), ("advanced", "stale"), ("removed_track", "old")):
            (stage / track).mkdir(parents=True, exist_ok=True)
            (stage / track / key).write_text("x\n")
        (stage / "asset-map.tsv").write_text("advanced\tkept\tREADME.md\n")
        result = subprocess.run(["python3", "-", str(stage)], input=code,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        remaining = sorted(path.relative_to(stage).as_posix() for path in stage.rglob("*"))
        self.assertEqual(remaining, ["advanced", "advanced/kept", "asset-map.tsv"])


class ReleaseGuardTests(unittest.TestCase):
    """Organiser release for Modules 1 and 2 against a fake k3s."""

    FAKE_K3S = r'''#!/bin/sh
# Answers the kubectl calls of the release script from files in $FAKE_STATE.
shift  # kubectl
case "$*" in
  *"get configmap digitafrica-workshop-state"*)
    key="$(printf '%s' "$*" | sed -n 's/.*{\.data\.\([a-z_]*\)}.*/\1/p')"
    cat "$FAKE_STATE/$key" 2>/dev/null
    ;;
  *"get configmap digitafrica-notebooks-cloud-computing-soa-module"*"-solutions"*)
    printf 'reference code'
    ;;
  *"patch configmap digitafrica-workshop-state"*)
    printf '%s\n' "$*" >> "$FAKE_STATE/patches"
    ;;
  *) echo "unexpected: $*" >&2; exit 9 ;;
esac
'''

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cloud-soa-release-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "bin").mkdir()
        k3s = self.root / "bin/k3s"
        k3s.write_text(self.FAKE_K3S)
        k3s.chmod(0o755)

    def release(self, module, workshop_module, mode):
        state = self.root / "state"
        shutil.rmtree(state, ignore_errors=True)
        state.mkdir()
        for name, value in (("workshop_type", "cloud-computing-soa"),
                            ("workshop_module", workshop_module), ("mode", mode)):
            (state / name).write_text(value)
        script = r'''
set -euo pipefail
source "$1"
print_heading() { :; }
log() { :; }
confirm() { return 0; }
run_deployment_remote() { bash -c "$1"; }
cloud_module1_show_status() { :; }
cloud_module2_show_status() { :; }
DIGITAFRICA_NAMESPACE=test
ASSUME_YES=true
cloud_module${2}_release_solutions
'''
        result = subprocess.run(
            ["bash", "-c", script, "release-test",
             str(ROOT / "scripts/workshops/cloud-computing-soa/course-main.sh"), str(module)],
            env={"PATH": f"{self.root / 'bin'}:/usr/bin:/bin", "FAKE_STATE": str(state)},
            capture_output=True, text=True, timeout=30,
        )
        patches = (state / "patches").read_text() if (state / "patches").exists() else ""
        return result, patches

    def test_release_only_for_its_module_and_intermediate_or_advanced(self):
        for module in (1, 2):
            for workshop_module, mode, allowed in (
                (f"module{module}", "intermediate", True),
                (f"module{module}", "advanced", True),
                (f"module{module}", "beginner", False),
                (f"module{3 - module}", "advanced", False),
            ):
                with self.subTest(module=module, workshop_module=workshop_module, mode=mode):
                    result, patches = self.release(module, workshop_module, mode)
                    if allowed:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn('"solutions_released":"true"', patches)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("can be released only", result.stderr)
                        self.assertEqual(patches, "")


if __name__ == "__main__":
    unittest.main()
