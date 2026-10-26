"""Grading on the organiser's machine: grading-local.py, grading-main.sh and the menus.

The bash tests run the organiser's grading entry with run_deployment_remote
replaced by a local shell, so that grading-remote.py runs here against a fake
k3s and helm (grading_fake_cluster.py) whose pods finish at once. No
Kubernetes, Helm, Ansible or network access.
"""
import base64
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
from grading_fake_cluster import FakeCluster, results_log, tests_result  # noqa: E402

SCRIPTS = ROOT / "scripts/workshops/cloud-computing-soa"
LOCAL = SCRIPTS / "grading-local.py"
SOA = ROOT / "workshop_assets/cloud-computing-soa"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    written = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # no caches next to the files under test
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


local = load("grading_local", LOCAL)
remote = load("grading_remote", SCRIPTS / "grading-remote.py")


def framed(answer):
    """Ansible's output around the answer of grading-remote.py."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        remote.answer(answer)
    return "central | CHANGED | rc=0 >>\n" + output.getvalue()


def helper(*arguments, stdin=""):
    return subprocess.run([sys.executable, str(LOCAL), *arguments], input=stdin, capture_output=True,
                          text=True, timeout=60)


class LocalHelperTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="grading-local-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_the_bundle_holds_the_pod_script_the_manifest_and_one_kind_of_files(self):
        expected = {
            ("1", "tests"): ["read_from.csv", "test_api.py"],
            ("1", "audit"): ["audit_a1.py", "audit_common.py"],
            ("2", "tests"): ["read_from.csv", "test_microservices.py", "test_ownership_isolation.py"],
            ("2", "audit"): ["audit_a1.py", "audit_a2.py", "audit_common.py"],
        }
        for (module, kind), names in expected.items():
            with self.subTest(module=module, kind=kind):
                files, paths = local.bundle(module, kind, local.AUDIT)
                self.assertEqual(sorted(files), sorted(names + ["grading-pod.py", "manifest.json"]))
                for name, path in paths.items():
                    self.assertEqual(files[name], path.read_text(encoding="utf-8"))
                manifest = json.loads(files["manifest.json"])
                assets = local.MODULES[module]["assets"]
                for code in local.MODULES[module]["code"]:
                    self.assertEqual(manifest["solution"][code],
                                     hashlib.sha256((assets / "solutions" / code).read_bytes()).hexdigest())
                    for track in ("beginner", "intermediate", "advanced"):
                        self.assertEqual(manifest["delivered"][track][code],
                                         hashlib.sha256((assets / track / code).read_bytes()).hexdigest())

    def test_every_start_fits_into_one_ansible_argument_with_room_to_grow(self):
        for module in ("1", "2"):
            for kind in ("tests", "audit"):
                with self.subTest(module=module, kind=kind):
                    run_dir = self.root / f"{module}-{kind}"
                    result = helper("script", "start", "--namespace", "digitafrica", "--run-dir", str(run_dir),
                                    "--run", "0123abcd", "--module", module, "--track", "advanced", "--kind", kind)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    script = result.stdout
                    # run_inventory_target_remote passes base64(script) in one argument of at most 128 KiB.
                    self.assertLess(len(base64.b64encode(script.encode())) + 40, 131072)
                    self.assertLess(len(script), 0.85 * local.SCRIPT_LIMIT)
                    payload = script.split("python3 - ", 1)[1].split(" <<", 1)[0]
                    sent = json.loads(gzip.decompress(base64.b64decode(payload)))
                    code = script.split("b64decode('", 1)[1].split("')", 1)[0]
                    self.assertEqual(gzip.decompress(base64.b64decode(code)),
                                     (SCRIPTS / "grading-remote.py").read_bytes())
                    self.assertEqual((sent["operation"], sent["kind"], sent["module"]), ("start", kind, module))
                    record = json.loads((run_dir / "run.json").read_text())
                    self.assertEqual(record["run"], "0123abcd")
                    bundle = json.loads(gzip.decompress(base64.b64decode(sent["bundle"])))
                    self.assertEqual(sorted(list(record["files"]) + ["manifest.json"]), sorted(bundle))
                    self.assertEqual(record["manifest"], json.loads(bundle["manifest.json"]))
                    self.assertEqual(oct(run_dir.stat().st_mode & 0o777), "0o700")

    def test_start_refuses_bad_input(self):
        base = ["script", "start", "--namespace", "digitafrica", "--module", "1", "--track", "advanced",
                "--kind", "tests"]
        cases = [
            (["--run-dir", str(self.root / "a"), "--run", "../../x"], "--run must be"),
            (["--run-dir", str(self.root / "b"), "--run", "0123abcd", "--groups", "group_01,../x"], "Not a group"),
            (["--run-dir", str(self.root), "--run", "0123abcd"], "exists already"),
            (["--run-dir", str(self.root / "c"), "--run", "0123abcd", "--parallel", "0"], "--parallel"),
        ]
        for extra, message in cases:
            with self.subTest(message):
                result = helper(*base, *extra)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_receive_reads_the_answer_or_shows_the_remote_error(self):
        answer = {"state": {"workshop_type": "cloud-computing-soa", "mode": "advanced\x1b[31m"},
                  "lock": None, "groups": ["group_01", "group_02"], "host": "central.example/x"}
        result = helper("receive", "status", "--run-dir", "", stdin=framed(answer))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("groups=2", result.stdout.splitlines())
        self.assertIn("mode=advanced?[31m", result.stdout.splitlines())
        self.assertIn("host=central.example-x", result.stdout.splitlines())
        self.assertIn("lock_run=", result.stdout.splitlines())
        self.assertIn("lock_idle=", result.stdout.splitlines())
        failed = "central | FAILED | rc=1 >>\nERROR: Kubernetes v1.28.1 cannot run the grading pods\n"
        result = helper("receive", "status", "--run-dir", "", stdin=failed)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: Kubernetes v1.28.1", result.stderr)
        self.assertIn("did not complete", result.stderr)

    def test_receive_saves_known_files_of_known_groups_only(self):
        run_dir = self.root / "run"
        run_dir.mkdir()
        (run_dir / "run.json").write_text(json.dumps({"run": "0123abcd"}))
        block = {"summary": {"kind": "tests", "work": "changed", "outcome": "graded", "network": {
                     "attempts": 2, "hosts": 1, "cut": False,
                     "targets": [{"kind": "lookup", "target": "en.wikipedia.org", "count": 2}]}},
                 "files": {"tests.txt": "x", "tests.json": json.dumps({"earned": 3, "possible": 12, "lines": []}),
                           "../evil.txt": "no", "service.log": "no"}}
        result = {"state": "done", "reason": "", "pod": {}, "events": [], "results": block,
                  "logs": {"service": "[shortener] up\n", "other": "no"}}
        answer = {"run": "0123abcd", "groups": {"group_01": "done", "group_02": "running"},
                  "results": {"group_01": result}}
        done = helper("receive", "step", "--run-dir", str(run_dir), stdin=framed(answer))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "remaining=1")
        self.assertIn("group_01  changed    3/12 points  (its code tried to reach other hosts)", done.stderr)
        self.assertEqual(sorted(path.name for path in (run_dir / "group_01").iterdir()),
                         ["result.json", "service.log", "tests.json", "tests.txt"])
        self.assertFalse((self.root / "evil.txt").exists())
        answer["results"] = {"../group_03": result}
        bad = helper("receive", "step", "--run-dir", str(run_dir), stdin=framed(answer))
        self.assertNotEqual(bad.returncode, 0)
        self.assertFalse((self.root / "group_03").exists())

    def test_summary_of_a_test_run_and_of_an_audit(self):
        def result(group, kind, files, **summary):
            folder = run_dir / group
            folder.mkdir()
            for name, text in files.items():
                (folder / name).write_text(text)
            record = {"state": "done", "reason": "", "pod": {}, "events": [],
                      "summary": dict({"kind": kind, "work": "changed", "outcome": "graded"}, **summary)}
            (folder / "result.json").write_text(json.dumps(record))

        tests = {"lines": [{"line": "Methods: PUT /:id (200, 400, 404)", "status": "failed"},
                           {"line": "Methods: POST / (201, 400)", "status": "passed"}],
                 "earned": 11, "possible": 12}
        for kind in ("tests", "audit"):
            with self.subTest(kind=kind):
                run_dir = self.root / kind
                run_dir.mkdir()
                # The audit of this run came from another folder than the checkout's.
                files = {"audit_common.py": {"path": "/elsewhere/ta-audit/audit_common.py"}} if kind == "audit" else {}
                (run_dir / "run.json").write_text(json.dumps({
                    "run": "0123abcd", "module": "1", "track": "intermediate", "kind": kind, "egress": "none",
                    "created": "2026-10-25T10:00:00Z", "started": "2026-10-25T10:00:05Z", "image": "img:1",
                    "groups": ["group_01", "group_02", "group_03", "group_04", "group_05"], "files": files}))
                if kind == "tests":
                    result("group_01", kind, {"tests.json": json.dumps(tests)})
                else:
                    audit = {"counts": {"FAIL": 1, "WARN": 2, "ERROR": 0},
                             "checks": [{"id": "A1-URL-03", "status": "FAIL"}, {"id": "A1-ID-02", "status": "WARN"}]}
                    result("group_01", kind, {"audit.json": json.dumps(audit)})
                result("group_02", kind, {}, work="missing", outcome="not graded", reason="no Module-1 folder")
                result("group_03", kind, {}, closed=[5000], listening=[5050], network={
                    "attempts": 30, "hosts": 25, "cut": True, "targets": [
                        {"kind": "lookup", "target": f"host{number}.example", "count": 2} for number in range(4)]
                    + [{"kind": "connect", "target": "192.0.2.1:5432", "count": 1}]})
                # Names come from the group's code: in summary.md they are set as code.
                result("group_05", kind, {f"{kind}.txt": "Traceback"}, exit=2, network={
                    "attempts": 1, "hosts": 1, "cut": False,
                    "targets": [{"kind": "query", "target": "<img/src=x/onerror=alert(1)>`|", "count": 1}]})
                printed = helper("summary", "--run-dir", str(run_dir))
                self.assertEqual(printed.returncode, 0, printed.stderr)
                rows = list(__import__("csv").reader(io.StringIO((run_dir / "summary.csv").read_text())))
                self.assertEqual(rows[0][5], "Network use")
                first = ["group_01", "changed", "11/12 points", "graded", "Methods: PUT /:id (200, 400, 404)", ""] \
                    if kind == "tests" else ["group_01", "changed", "FAIL 1, WARN 2, ERROR 0", "graded", "A1-URL-03",
                                             ""]
                self.assertEqual(rows[1], first)
                self.assertEqual(rows[2], ["group_02", "missing", "", "not graded: no Module-1 folder", "", ""])
                self.assertEqual(rows[3][3], "no service on port 5000 (listening: 5050)")
                # A service that cannot start without its database, for example.
                self.assertEqual(rows[3][5], "looked up host0.example (2), host1.example (2), host2.example (2) "
                                             "and 1 more; connected to 192.0.2.1:5432 (1); 20 more "
                                             "(more were left out)")
                self.assertEqual(rows[4], ["group_04", "-", "", "no results", "", ""])
                self.assertEqual(rows[5][3], f"no {kind}.json (exit 2); see {kind}.txt")
                self.assertEqual(rows[5][5], "asked the DNS for <img/src=x/onerror=alert(1)>`| (1)")
                markdown = (run_dir / "summary.md").read_text()
                self.assertIn("| group_01 | changed |", markdown)
                self.assertIn("| looked up `host0.example` (2), `host1.example` (2), `host2.example` (2) and 1 more; "
                              "connected to `192.0.2.1:5432` (1); 20 more (more were left out) |", markdown)
                self.assertIn("| asked the DNS for `<img/src=x/onerror=alert(1)>'\\|` (1) |", markdown)
                self.assertIn(str(run_dir), printed.stdout)
                # The organiser can grade these groups again with network: same track, image and audit.
                action = "cloud-module1-grade" if kind == "tests" else "cloud-module1-audit"
                audit = " CLOUD_SOA_TA_AUDIT_DIR=/elsewhere/ta-audit" if kind == "audit" else ""
                command = ("    CLOUD_SOA_GRADING_EGRESS=participant CLOUD_SOA_GRADING_GROUPS=group_03,group_05 "
                           f"CLOUD_COMPUTING_SOA_MODE=intermediate CLOUD_SOA_GRADING_IMAGE=img:1{audit} "
                           f"scripts/workshops/organizer-main.sh {action}")
                for text in (markdown, printed.stdout):
                    self.assertIn("The code of these groups tried to reach other hosts: group_03, group_05", text)
                    self.assertIn(command, text.splitlines())


class OrganiserFlowTests(unittest.TestCase):
    """cloud_soa_grade_groups from the status check to the summary, against the fake cluster."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="grading-flow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "bin").mkdir()
        for program in ("k3s", "helm"):
            wrapper = self.root / "bin" / program
            wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{TESTS / "grading_fake_cluster.py"}" '
                               f'{program} "$@"\n')
            wrapper.chmod(0o755)
        self.cluster = FakeCluster()
        self.cluster.state["finish"] = tests_result(earned=12)
        self.state_file = self.root / "cluster.json"
        self.results = self.root / "results"

    def grade(self, module="1", kind="tests", answers="", **environment):
        self.state_file.write_text(json.dumps(self.cluster.state))
        script = r'''
set -euo pipefail
print_heading() { printf '== %s\n' "$*"; }
log() { :; }
confirm() {
  [[ "${DIGITAFRICA_ASSUME_YES:-false}" == true ]] && return 0
  local reply; read -r reply; [[ "$reply" == y ]]
}
run_deployment_remote() { bash -c "$1"; }
DIGITAFRICA_NAMESPACE=digitafrica
source "$1"
cloud_soa_grade_groups "$2" "$3"
'''
        env = {"PATH": f"{self.root / 'bin'}:{os.environ['PATH']}", "FAKE_CLUSTER": str(self.state_file),
               "CLOUD_SOA_GRADING_RESULTS": str(self.results), "CLOUD_SOA_GRADING_POLL_SECONDS": "0",
               "DIGITAFRICA_ASSUME_YES": "true", "HOME": str(self.root)}
        env.update(environment)
        result = subprocess.run(["bash", "-c", script, "grading-test", str(SCRIPTS / "course-main.sh"), module, kind],
                                input=answers, env=env, capture_output=True, text=True, timeout=300)
        self.cluster = FakeCluster(json.loads(self.state_file.read_text()))
        return result

    def run_objects(self):
        return [name for kind, items in self.cluster.objects.items() for name, item in items.items()
                if "digitafrica.io/grading-run" in item["metadata"].get("labels", {})]

    def run_dirs(self):
        return sorted(self.results.glob("*/*")) if self.results.exists() else []

    def test_a_run_grades_every_group_saves_the_results_and_cleans_up(self):
        result = self.grade(CLOUD_SOA_GRADING_PARALLEL="2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        [run_dir] = self.run_dirs()
        self.assertRegex(run_dir.name, r"^\d{8}-\d{6}-module1-tests-[0-9a-f]{8}$")
        record = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((record["track"], record["groups"]), ("intermediate", ["group_01", "group_02", "group_03"]))
        self.assertEqual(record["image"], "quay.io/jupyterhub/k8s-singleuser-sample:4.4.2")
        self.assertEqual((record["egress"], record["unreachable"]), ("none", []))  # no network by default
        self.assertIn("Network: none: the groups' code cannot reach the internet or the cluster.", result.stdout)
        for group in record["groups"]:
            self.assertTrue((run_dir / group / "tests.json").is_file(), group)
        self.assertIn("group_03  changed  12/12 points  graded", result.stdout)
        self.assertIn("Network: none: the groups' code could not reach the internet", (run_dir / "summary.md").read_text())
        self.assertEqual(self.run_objects(), [])  # nothing of the run is left in the cluster
        self.assertIn("Removed 1 pods, 1 network policy and 2 ConfigMaps", result.stderr)

    def test_a_service_log_cut_inside_a_character_is_saved(self):
        # kubectl cuts logs at a byte limit: byte 60000 of this log falls inside an "é".
        line = "[shortener] GET /é 200\n"
        log = "start\n" + line * 8000
        self.assertEqual(len("start\n".encode()) + 2499 * len(line.encode()) + 18, 60000)
        self.cluster.state["container_logs"]["service"] = log
        result = self.grade()
        self.assertEqual(result.returncode, 0, result.stderr)
        [run_dir] = self.run_dirs()
        for group in ("group_01", "group_02", "group_03"):
            saved = (run_dir / group / "service.log").read_text(encoding="utf-8")
            self.assertTrue(saved.startswith("start\n" + line) and saved.endswith(line), group)

    def test_the_network_setting_is_checked_and_recorded(self):
        result = self.grade(CLOUD_SOA_GRADING_EGRESS="internet")
        self.assertEqual(result.returncode, 2)
        self.assertIn("CLOUD_SOA_GRADING_EGRESS must be none or participant, not internet.", result.stderr)
        self.assertEqual((self.run_dirs(), self.run_objects()), ([], []))
        result = self.grade(CLOUD_SOA_GRADING_EGRESS="participant")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Network: the internet, as from participant servers, but not the nodes", result.stdout)
        [run_dir] = self.run_dirs()
        record = json.loads((run_dir / "run.json").read_text())
        self.assertEqual((record["egress"], record["unreachable"]), ("participant", ["203.0.113.10/32",
                                                                                    "203.0.113.11/32"]))

    def test_the_track_comes_from_the_active_module_or_the_organiser(self):
        result = self.grade(module="2")  # Module 1 is active, and there is no terminal to ask
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLOUD_COMPUTING_SOA_MODE", result.stderr)
        for module, mode in (("2", "advanced"), ("1", "beginner"), ("1", "")):
            result = self.grade(module=module, CLOUD_COMPUTING_SOA_MODE=mode)
            self.assertEqual(result.returncode, 0, result.stderr)
        tracks = {run_dir.name.split("-", 2)[2]: json.loads((run_dir / "run.json").read_text())["track"]
                  for run_dir in self.run_dirs()}
        self.assertEqual(sorted(tracks.values()), ["advanced", "beginner", "intermediate"])

    def leftover(self, minutes_ago):
        when = time.time() - 60 * minutes_ago  # grading-remote.py runs here with the real clock
        started = remote.timestamp(when)
        self.cluster.add("configmap", "digitafrica-grading-run", data={
            "run": "ffff0000", "started": started, "touched": started, "kind": "audit", "module": "1",
        })["metadata"]["labels"] = {"digitafrica.io/grading-run": "ffff0000"}
        return started

    def test_a_leftover_run_is_removed_only_with_consent(self):
        started = self.leftover(minutes_ago=30)
        result = self.grade(answers="n\n", DIGITAFRICA_ASSUME_YES="false")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"Grading run ffff0000 (audit of Module 1, started {started}) is still in the cluster",
                      result.stderr)
        self.assertIn("Nobody has followed it for 30 minutes", result.stderr)
        self.assertIn("digitafrica-grading-run", self.cluster.objects["configmap"])
        self.assertEqual(self.run_dirs(), [])
        result = self.grade()  # an interrupted run is removed with DIGITAFRICA_ASSUME_YES
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_objects(), [])

    def test_a_run_that_may_still_be_running_is_never_removed_automatically(self):
        self.leftover(minutes_ago=2)
        result = self.grade()  # DIGITAFRICA_ASSUME_YES=true, and nobody answers
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("so it may still be running", result.stderr)
        self.assertIn("digitafrica-grading-run", self.cluster.objects["configmap"])
        result = self.grade(answers="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_objects(), [])

    def test_nothing_starts_while_a_reset_is_incomplete(self):
        self.cluster.objects["configmap"]["digitafrica-workshop-state"]["data"]["cleanup_status"] = "in_progress"
        result = self.grade()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Workshop cleanup is incomplete", result.stderr)
        self.assertEqual(self.run_dirs(), [])
        self.assertEqual(self.run_objects(), [])

    def test_a_failed_start_still_cleans_up(self):
        self.cluster.state["fail"] = ["create -f - -o json"]  # the lock cannot be written
        result = self.grade()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot create ConfigMap digitafrica-grading-run", result.stderr)
        self.assertIn("Removing grading run", result.stderr)
        self.assertEqual(self.run_objects(), [])
        self.cluster = FakeCluster()
        self.cluster.state["version"]["serverVersion"]["minor"] = "28"
        result = self.grade()
        self.assertIn("they need sidecar containers", result.stderr)
        self.assertEqual(self.run_objects(), [])

    def test_declining_starts_nothing(self):
        result = self.grade(answers="n\n", DIGITAFRICA_ASSUME_YES="false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No grading run was started.", result.stdout)
        self.assertEqual(self.run_dirs(), [])
        self.assertEqual(self.run_objects(), [])


class EntryPointTests(unittest.TestCase):
    def test_actions_are_listed_and_routed(self):
        text = (ROOT / "scripts/workshops/organizer-main.sh").read_text()
        dispatch = text.split("# Dispatch only after", 1)[1]
        for action, arguments in (("cloud-module1-grade", "1 tests"), ("cloud-module1-audit", "1 audit"),
                                  ("cloud-module2-grade", "2 tests"), ("cloud-module2-audit", "2 audit")):
            with self.subTest(action=action):
                self.assertIn(f"  {action} ", text.split("USAGE", 2)[1])
                self.assertIn(f"|{action}|", text)
                body = dispatch.split(f"  {action})", 1)[1].split(";;", 1)[0]
                result = subprocess.run(["bash", "-c", 'cloud_soa_grade_groups() { printf "%s %s" "$1" "$2"; }\n'
                                         + body], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.stdout, arguments)

    def test_module_menus_offer_tests_and_audit(self):
        for module in ("1", "2"):
            for choice, kind in (("7", "tests"), ("8", "audit")):
                with self.subTest(module=module, choice=choice):
                    script = r'''
source "$1"
workshop_ui_heading() { :; }; workshop_ui_section() { :; }; workshop_ui_option() { :; }
workshop_ui_note() { :; }; workshop_ui_prompt() { :; }
cloud_soa_grade_groups() { printf 'GRADE %s %s\n' "$1" "$2"; }
run_cloud_computing_soa_module_menu "$2"
'''
                    result = subprocess.run(
                        ["bash", "-c", script, "menu-test", str(SCRIPTS / "course-main.sh"), module],
                        input=f"{choice}\n0\n", capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f"GRADE {module} {kind}", result.stdout)


if __name__ == "__main__":
    unittest.main()
