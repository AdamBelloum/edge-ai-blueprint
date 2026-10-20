"""Execute the Module 3 task shell with temporary staging and mocked k3s."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPOSITORY = Path(__file__).resolve().parents[1]
TASK = REPOSITORY / "roles/k8s_apps/tasks/cloud-soa-module3-assets.yml"
TRACKS = ("beginner", "advanced", "solutions", "tests")

MOCK = r'''
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log = Path(os.environ["MOCK_LOG"])
fault = os.environ.get("MOCK_FAULT", "")

def record(event):
    with log.open("a") as stream:
        stream.write(event + "\n")

if args[:2] != ["kubectl", "-n"]:
    raise SystemExit("Unexpected mocked command")

namespace = args[2]
operation = args[3]

if operation == "create":
    if args[4] != "configmap" or args[-3:] != ["--dry-run=client", "-o", "json"]:
        raise SystemExit("Unexpected render command")
    name = args[5]
    track = name.rsplit("-", 1)[1]
    record("render:" + track)
    if fault == "render_failure" and track == "tests":
        raise SystemExit(9)
    data = {}
    for argument in args:
        if argument.startswith("--from-file="):
            key, filename = argument[len("--from-file="):].split("=", 1)
            data[key] = Path(filename).read_text()
    manifest = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "creationTimestamp": None,
        },
        "data": data,
    }
    if track == "tests":
        if fault == "oversized":
            data["example_txt"] = "x" * 204801
        elif fault == "wrong_namespace":
            manifest["metadata"]["namespace"] = "wrong"
        elif fault == "binary_data":
            manifest["binaryData"] = {"unexpected": "eA=="}
        elif fault == "malformed_json":
            print("{")
            raise SystemExit(0)
    print(json.dumps(manifest))
elif operation == "apply":
    if args[4] != "-f":
        raise SystemExit("Unexpected apply command")
    manifest = json.loads(Path(args[5]).read_text())
    track = manifest["metadata"]["name"].rsplit("-", 1)[1]
    record("apply:" + track)
    if fault == "partial_apply" and track == "advanced":
        raise SystemExit(8)
    # Minimal stateful apply model, not a full Kubernetes API emulator.
    # Reject the exact server-managed field responsible for the live loop.
    if "creationTimestamp" in manifest["metadata"]:
        raise SystemExit("Applied manifest contains server-managed creationTimestamp")
    if manifest["metadata"].get("annotations") != {}:
        raise SystemExit("Applied manifest lacks normalized empty annotations")

    state = log.parent / "applied"
    state.mkdir(exist_ok=True)
    saved = state / (track + ".json")
    if not saved.exists():
        status = "created"
    elif json.loads(saved.read_text()) == manifest:
        status = "unchanged"
    else:
        status = "configured"
    saved.write_text(json.dumps(manifest, sort_keys=True))
    print("configmap/" + manifest["metadata"]["name"] + " " + status)
else:
    raise SystemExit("Unexpected mocked operation")
'''


class Module3ReconciliationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.stage = self.directory / "stage"
        self.stage.mkdir()
        rows = []
        for track in TRACKS:
            folder = self.stage / track
            folder.mkdir()
            (folder / "example_txt").write_text("Teaching fixture\n")
            rows.append(f"{track}\texample_txt\texample.txt\n")
        (self.stage / "asset-map.tsv").write_text("".join(rows))

        self.log = self.directory / "calls.log"
        mock_script = self.directory / "mock.py"
        mock_script.write_text(MOCK)
        mock_command = self.directory / "k3s"
        mock_command.write_text(
            "#!/bin/bash\nexec "
            + __import__("shlex").quote(sys.executable)
            + " "
            + __import__("shlex").quote(str(mock_script))
            + ' "$@"\n'
        )
        mock_command.chmod(0o755)

        shell = yaml.safe_load(TASK.read_text())[-1]["ansible.builtin.shell"]
        old_root = "root=/opt/digitafrica/k8s-notebooks/cloud-computing-soa/module3/source"
        old_namespace = (
            "namespace={{ digitafrica_deployment.digitafrica_namespace | quote }}"
        )
        self.assertEqual(shell.count(old_root), 1)
        self.assertEqual(shell.count(old_namespace), 1)
        self.shell = shell.replace(
            old_root, "root=" + __import__("shlex").quote(str(self.stage))
        ).replace(old_namespace, "namespace=test-module3")
        self.environment = dict(os.environ)
        self.environment["PATH"] = (
            str(self.directory) + os.pathsep + os.environ["PATH"]
        )
        self.environment["MOCK_LOG"] = str(self.log)

    def run_task(self, fault=""):
        environment = dict(self.environment, MOCK_FAULT=fault)
        return subprocess.run(
            ["bash", "-c", self.shell],
            env=environment, capture_output=True, text=True, timeout=30,
        )

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_valid_run_and_repeat(self):
        expected = (
            ["render:" + track for track in TRACKS]
            + ["apply:" + track for track in TRACKS]
        )
        for status in ("created", "unchanged"):
            result = self.run_task()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                [line for line in result.stdout.splitlines()
                 if line.startswith("configmap/")],
                [
                    "configmap/digitafrica-notebooks-cloud-computing-soa-module3-"
                    + track + " " + status
                    for track in TRACKS
                ],
            )
        self.assertEqual(self.calls(), expected * 2)

    def test_applied_manifests_are_normalized(self):
        result = self.run_task()
        self.assertEqual(result.returncode, 0, result.stderr)
        for track in TRACKS:
            with self.subTest(track=track):
                manifest = json.loads(
                    (self.directory / "applied" / (track + ".json")).read_text()
                )
                self.assertNotIn("creationTimestamp", manifest["metadata"])
                self.assertEqual(manifest["metadata"]["annotations"], {})
                self.assertEqual(manifest["data"]["example_txt"], "Teaching fixture\n")
                self.assertEqual(
                    manifest["data"]["asset_map_tsv"],
                    (self.stage / "asset-map.tsv").read_text(),
                )

    def test_changed_asset_configures_only_its_track_then_converges(self):
        initial = self.run_task()
        self.assertEqual(initial.returncode, 0, initial.stderr)
        (self.stage / "advanced/example_txt").write_text("Updated fixture\n")

        for changed in (True, False):
            result = self.run_task()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                [line for line in result.stdout.splitlines()
                 if line.startswith("configmap/")],
                [
                    "configmap/digitafrica-notebooks-cloud-computing-soa-module3-"
                    + track + " "
                    + ("configured" if changed and track == "advanced"
                       else "unchanged")
                    for track in TRACKS
                ],
            )

    def test_rendered_preflight_failures_prevent_every_apply(self):
        for fault in (
            "oversized", "wrong_namespace", "binary_data", "malformed_json"
        ):
            with self.subTest(fault=fault):
                self.log.unlink(missing_ok=True)
                result = self.run_task(fault)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(
                    self.calls(), ["render:" + track for track in TRACKS]
                )

    def test_render_failure_prevents_every_apply(self):
        result = self.run_task("render_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call.startswith("apply:") for call in self.calls()))

    def test_missing_last_track_source_prevents_every_apply(self):
        (self.stage / "tests/example_txt").unlink()
        result = self.run_task()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing staged asset", result.stderr)
        self.assertFalse(any(call.startswith("apply:") for call in self.calls()))

    def test_partial_apply_stops_and_rerun_attempts_all_tracks(self):
        failed = self.run_task("partial_apply")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(
            self.calls(),
            ["render:" + track for track in TRACKS]
            + ["apply:beginner", "apply:advanced"],
        )
        self.log.unlink()
        retried = self.run_task()
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertEqual(
            self.calls(),
            ["render:" + track for track in TRACKS]
            + ["apply:" + track for track in TRACKS],
        )


class Module3WiringTests(unittest.TestCase):
    def setUp(self):
        self.tasks = yaml.safe_load(
            (REPOSITORY / "roles/k8s_apps/tasks/install.yml").read_text()
        )
        self.includes = [
            (index, task)
            for index, task in enumerate(self.tasks)
            if isinstance(task.get("ansible.builtin.include_tasks"), dict)
            and task["ansible.builtin.include_tasks"].get("file")
            == "cloud-soa-module3-assets.yml"
        ]

    def test_single_include_immediately_after_namespace_creation(self):
        self.assertEqual(len(self.includes), 1)
        index, _ = self.includes[0]
        self.assertGreater(index, 0)
        self.assertEqual(
            self.tasks[index - 1].get("name"), "Ensure namespace exists"
        )

    def test_include_and_children_receive_reconciliation_tags(self):
        self.assertEqual(len(self.includes), 1)
        _, task = self.includes[0]
        expected = {"workshop_assets", "workshop_application_reconciliation"}
        self.assertEqual(set(task["tags"]), expected)
        self.assertEqual(
            set(task["ansible.builtin.include_tasks"]["apply"]["tags"]),
            expected,
        )

    def test_asset_reconciliation_has_no_publication_condition(self):
        self.assertEqual(len(self.includes), 1)
        _, task = self.includes[0]
        self.assertNotIn("when", task)
        self.assertEqual(
            set(task["ansible.builtin.include_tasks"]),
            {"file", "apply"},
        )


class Module3ChangeReportingTests(unittest.TestCase):
    def setUp(self):
        from ansible.plugins.test.core import TestModule
        from jinja2 import Environment, StrictUndefined

        task = yaml.safe_load(TASK.read_text())[-1]
        self.assertEqual(
            task["register"], "cloud_module3_asset_reconciliation"
        )
        environment = Environment(undefined=StrictUndefined)
        environment.tests["match"] = TestModule().tests()["match"]
        self.expression = environment.compile_expression(task["changed_when"])

    def changed(self, lines):
        return self.expression(
            cloud_module3_asset_reconciliation={"stdout_lines": lines}
        )

    def test_created_reports_changed(self):
        self.assertTrue(self.changed(["configmap/example created"]))

    def test_configured_reports_changed(self):
        self.assertTrue(self.changed(["configmap/example configured"]))

    def test_all_unchanged_reports_no_change(self):
        self.assertFalse(self.changed([
            "configmap/example-beginner unchanged",
            "configmap/example-advanced unchanged",
            "configmap/example-solutions unchanged",
            "configmap/example-tests unchanged",
        ]))

    def test_mixed_output_reports_changed(self):
        self.assertTrue(self.changed([
            "PASS: beginner rendered ConfigMap budget",
            "configmap/example-beginner unchanged",
            "configmap/example-advanced configured",
            "configmap/example-tests unchanged",
        ]))

    def test_preflight_and_unrelated_output_report_no_change(self):
        self.assertFalse(self.changed([
            "PASS: beginner rendered ConfigMap budget",
            "deployment/example configured",
            "configured",
            "configmap/example unchanged",
        ]))
        self.assertFalse(self.changed([]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
