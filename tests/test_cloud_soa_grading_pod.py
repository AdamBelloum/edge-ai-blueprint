"""The grading pod's script (grading-pod.py) with real processes, without Kubernetes.

prepare, serve and grade run as in the pod's three containers, on temporary
folders in place of the pod's volumes: a workspace with the files that the
seeder delivers, an empty home, and the files that grading-local.py sends. The
services are the reference solutions, the delivered tracks and broken
variants. They listen on 127.0.0.1:5000 and 5001 as in JupyterHub, so those
tests are skipped when Flask, cryptography or requests is missing or the
ports are taken.
"""
import base64
import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts/workshops/cloud-computing-soa"
SOA = ROOT / "workshop_assets/cloud-computing-soa"
ASSETS = {"1": SOA / "module1-rest-api", "2": SOA / "module2-microservices"}
POD_SCRIPT = SCRIPTS / "grading-pod.py"


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


pod_module = load("grading_pod", POD_SCRIPT)
local = load("grading_local", SCRIPTS / "grading-local.py")


def ports_free():
    for port in (5000, 5001):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return False
    return True


def services_available():
    try:
        import cryptography  # noqa: F401
        import flask  # noqa: F401
        import requests  # noqa: F401
    except ImportError:
        return False
    return True


def tree_digest(folder):
    digest = hashlib.sha256()
    for path in sorted(Path(folder).rglob("*")):
        digest.update(str(path.relative_to(folder)).encode())
        if path.is_file() and not path.is_symlink():
            digest.update(path.read_bytes())
    return digest.hexdigest()


class Pod:
    """One group's grading pod: temporary folders for its volumes, and its three steps."""

    def __init__(self, test, module, track, kind="tests"):
        temporary = tempfile.TemporaryDirectory(prefix="grading-pod-")
        test.addCleanup(temporary.cleanup)
        self.test, self.module, self.track, self.kind = test, module, track, kind
        self.root = Path(temporary.name)
        for name in ("workspace", "home", "source", "results", "bundle", "bin"):
            (self.root / name).mkdir()
        self.folder = self.root / "workspace/Cloud-Computing-SOA" / f"Module-{module}"
        files, _ = local.bundle(module, kind, local.AUDIT)
        for name, text in files.items():
            (self.root / "bundle" / name).write_text(text, encoding="utf-8")
        # The participant's "python", as in a JupyterHub terminal.
        (self.root / "bin/python").symlink_to(sys.executable)
        self.service = None

    def deliver(self, track=None, solution=False):
        """The track's files as the seeder delivers them, or the reference solution in their place."""
        track = track or self.track
        assets = ASSETS[self.module]
        source = assets / ("solutions" if solution else track)
        for path in source.rglob("*"):
            if path.is_file():
                target = self.folder / track / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        tests = self.folder / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        for path in (assets / "shared/tests").iterdir():
            shutil.copyfile(path, tests / path.name)
        if self.module == "2":
            shutil.copyfile(assets / "requirements.lock", self.folder / "requirements.lock")

    def write(self, relative, text):
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def command(self, step, *extra):
        return [sys.executable, "-s", "-E", "-B", str(POD_SCRIPT), step, "--module", self.module,
                "--track", self.track, "--workspace", str(self.root / "workspace"),
                "--home", str(self.root / "home"), "--source", str(self.root / "source"),
                "--manifest", str(self.root / "bundle/manifest.json"), "--bundle", str(self.root / "bundle"),
                "--results", str(self.root / "results"), *extra]

    def prepare(self, *extra, environment=None):
        result = subprocess.run(self.command("prepare", *extra), capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, **(environment or {})))
        self.test.assertEqual(result.returncode, 0, result.stderr)
        self.prepare_log = result.stdout
        return json.loads((self.root / "source/prepare.json").read_text())

    def serve(self):
        environment = dict(os.environ, PATH=f"{self.root / 'bin'}:{os.environ.get('PATH', '')}")
        self.log = open(self.root / "service.log", "w+")
        self.test.addCleanup(self.log.close)
        self.service = subprocess.Popen(self.command("serve"), stdout=self.log, stderr=subprocess.STDOUT,
                                        env=environment)
        self.test.addCleanup(self.stop)

    def stop(self):
        if self.service and self.service.poll() is None:
            self.service.send_signal(signal.SIGTERM)
            self.service.wait(20)
        deadline = time.monotonic() + 20
        while not ports_free() and time.monotonic() < deadline:
            time.sleep(0.2)

    def grade(self, wait=40, timeout=300):
        result = subprocess.run(self.command("grade", "--kind", self.kind, "--wait", str(wait),
                                             "--timeout", str(timeout)),
                                capture_output=True, text=True, timeout=timeout + wait + 60)
        self.test.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        block = lines[lines.index(pod_module.BEGIN) + 1:lines.index(pod_module.END)]
        self.block = json.loads(gzip.decompress(base64.b64decode("".join(block))))
        return self.block["summary"]

    def points(self):
        report = json.loads(self.block["files"]["tests.json"])
        return report["earned"], report["possible"]

    def service_log(self):
        self.log.flush()
        self.log.seek(0)
        return self.log.read()

    def run(self, wait=40, timeout=300):
        record = self.prepare()
        self.serve()
        summary = self.grade(wait, timeout)
        self.stop()
        return record, summary


class PrepareTests(unittest.TestCase):
    """What prepare copies and how it describes the group's work; no services."""

    def test_work_states(self):
        cases = [
            ("missing", lambda pod: None, "no Module-1 folder"),
            ("missing", lambda pod: pod.deliver("beginner"), "no intermediate/app.py"),
            ("unchanged", lambda pod: pod.deliver(), "the files the group received, unchanged"),
            ("solution", lambda pod: pod.deliver(solution=True), "the reference solution"),
            ("changed", lambda pod: (pod.deliver(), pod.write("intermediate/app.py", "print(1)\n")), ""),
        ]
        for work, setup, reason in cases:
            with self.subTest(work=work, reason=reason):
                pod = Pod(self, "1", "intermediate")
                setup(pod)
                record = pod.prepare()
                self.assertEqual((record["work"], record["reason"]), (work, reason))
                copied = (pod.root / "home/Cloud-Computing-SOA/Module-1").is_dir()
                self.assertEqual(copied, work in ("unchanged", "solution", "changed"))

    def test_module2_needs_both_services(self):
        pod = Pod(self, "2", "advanced")
        pod.deliver()
        self.assertEqual(pod.prepare()["work"], "unchanged")
        (pod.folder / "advanced/shortener_service/shortener.py").unlink()
        shutil.rmtree(pod.root / "source")
        (pod.root / "source").mkdir()
        record = pod.prepare()
        self.assertEqual(record["work"], "missing")
        self.assertEqual(record["files"]["auth_service/auth.py"]["state"], "delivered")

    def test_copy_keeps_links_skips_special_files_and_never_writes_the_workspace(self):
        pod = Pod(self, "1", "intermediate")
        pod.deliver(solution=True)
        pod.write("intermediate/data/urls.json", "{}")
        pod.write("intermediate/.venv/pyvenv.cfg", "home = /usr/bin\n")
        pod.write("intermediate/__pycache__/app.cpython-312.pyc", "x")
        os.symlink("data/urls.json", pod.folder / "intermediate/link.json")
        os.symlink("/etc/passwd", pod.folder / "intermediate/outside")
        os.mkfifo(pod.folder / "intermediate/pipe")
        before = tree_digest(pod.root / "workspace")
        record = pod.prepare()
        self.assertEqual(tree_digest(pod.root / "workspace"), before)
        copy = pod.root / "home/Cloud-Computing-SOA/Module-1/intermediate"
        self.assertEqual(os.readlink(copy / "link.json"), "data/urls.json")
        self.assertEqual(os.readlink(copy / "outside"), "/etc/passwd")
        self.assertFalse((copy / "pipe").exists())
        self.assertEqual(record["skipped"], ["intermediate/pipe: not a regular file"])
        # The audit's copy of the source: regular files only, no environments or caches.
        source = sorted(path.relative_to(pod.root / "source/track").as_posix()
                        for path in (pod.root / "source/track").rglob("*") if path.is_file())
        self.assertEqual(source, ["app.py", "data/urls.json"])

    def test_the_code_is_copied_only_once_the_network_rules_are_in_force(self):
        # Listening sockets stand in for the Kubernetes API and the kubelet on the pod's node,
        # which answer until the pod's rules block them.
        kubelet, api = socket.socket(), socket.socket()
        self.addCleanup(kubelet.close)
        self.addCleanup(api.close)
        try:
            kubelet.bind(("127.0.0.1", pod_module.KUBELET))
        except OSError:
            self.skipTest(f"127.0.0.1:{pod_module.KUBELET} is in use")
        api.bind(("127.0.0.1", 0))
        for listener in (kubelet, api):
            listener.listen(50)
        address = {"KUBERNETES_SERVICE_HOST": "127.0.0.1", "KUBERNETES_SERVICE_PORT": str(api.getsockname()[1]),
                   "HOST_IP": "127.0.0.1"}

        def prepare(environment=address):
            pod = Pod(self, "1", "intermediate")
            pod.deliver(solution=True)
            return pod, pod.prepare("--policy-wait", "2", environment=environment)

        pod, record = prepare()
        self.assertEqual((record["work"], record["network_rules"]), ("error", "not in force"))
        self.assertIn("network rules were not in force after 2 s, so the group's code was not run", record["reason"])
        self.assertFalse((pod.root / "home/Cloud-Computing-SOA").exists())
        self.assertEqual(pod.grade()["outcome"], "not graded")
        # The API is down, but the kubelet still answers: the rules are not in force.
        api.close()
        _, record = prepare()
        self.assertEqual((record["work"], record["network_rules"]), ("error", "not in force"))
        # Neither answers, as for blocked connections: the copy is made.
        kubelet.close()
        pod, record = prepare()
        self.assertEqual(record["work"], "solution")
        self.assertRegex(record["network_rules"], r"^in force after \d+\.\d s$")
        self.assertIn("[runner] network rules in force after", pod.prepare_log)
        self.assertTrue((pod.root / "home/Cloud-Computing-SOA/Module-1/intermediate/app.py").is_file())
        # Without these addresses, nothing can be checked, and nothing runs.
        for name in address:
            with self.subTest(missing=name):
                pod, record = prepare(dict(address, **{name: ""}))
                self.assertEqual(record["work"], "error")
                self.assertIn("cannot check the network rules", record["reason"])
                self.assertFalse((pod.root / "home/Cloud-Computing-SOA").exists())

    def test_the_copy_never_writes_through_a_link(self):
        # The group's server may swap a folder for a link while prepare copies.
        pod = Pod(self, "1", "intermediate")
        pod.write("intermediate/data/urls.json", "{}")
        outside = pod.root / "outside"
        outside.mkdir()
        copy = pod.root / "home/copy"
        (copy / "intermediate").mkdir(parents=True)
        os.symlink(outside, copy / "intermediate/data")
        pod_module.copy_tree(pod.folder, copy)
        self.assertEqual(list(outside.iterdir()), [])

    def test_files_that_vanish_during_prepare_are_skipped(self):
        pod = Pod(self, "1", "intermediate")
        pod.deliver(solution=True)
        pod.write("intermediate/notes.txt", "gone soon")
        vanishing = str(pod.folder / "intermediate/notes.txt")
        real = os.lstat

        def lstat(path, *arguments, **keywords):
            if str(path) == vanishing:
                raise FileNotFoundError(path)
            return real(path, *arguments, **keywords)

        pod_module.os.lstat = lstat
        try:
            self.assertEqual(pod_module.measure(pod.folder)[0], 6)  # two folders, four files
            pod_module.keep_source(pod.folder / "intermediate", pod.root / "kept")
        finally:
            pod_module.os.lstat = real
        self.assertEqual(sorted(path.name for path in (pod.root / "kept").iterdir()), ["app.py"])

    def test_results_are_cut_but_json_is_left_out(self):
        pod = Pod(self, "1", "intermediate")
        big = "x" * (pod_module.FILE_LIMIT + 10)
        (pod.root / "results/tests.txt").write_text(big)
        (pod.root / "results/tests.json").write_text(json.dumps({"detail": big}))
        self.assertTrue(pod_module.readable(pod.root / "results/tests.txt").endswith("[cut at 2 MB]\n"))
        self.assertIsNone(pod_module.readable(pod.root / "results/tests.json"))

    def test_large_folders_are_not_copied(self):
        pod = Pod(self, "1", "intermediate")
        pod.deliver()
        manifest = json.loads((pod.root / "bundle/manifest.json").read_text())
        limit = pod_module.COPY_LIMIT
        try:
            pod_module.COPY_LIMIT = 100
            record = pod_module.examine(pod.folder, "intermediate", pod_module.MODULES["1"], manifest)
        finally:
            pod_module.COPY_LIMIT = limit
        self.assertEqual(record["work"], "too large")

    def test_the_grader_reports_work_it_cannot_grade_without_waiting(self):
        pod = Pod(self, "1", "intermediate")
        pod.prepare()
        started = time.monotonic()
        summary = pod.grade(wait=60)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual((summary["work"], summary["outcome"]), ("missing", "not graded"))
        self.assertNotIn("tests.txt", pod.block["files"])
        (pod.root / "source/prepare.json").unlink()
        self.assertEqual(pod.grade()["work"], "error")


@unittest.skipUnless(services_available(), "Flask, cryptography and requests are needed")
class ServiceTests(unittest.TestCase):
    """The pod's steps with the group's services running on 127.0.0.1:5000 and 5001."""

    def setUp(self):
        if not ports_free():
            self.skipTest("127.0.0.1:5000 or 5001 is in use")

    def test_module1_reference_and_delivered_tracks(self):
        for track, solution, work, expected in (
            ("intermediate", True, "solution", (12, 12)),
            ("beginner", False, "unchanged", (11, 12)),
            ("advanced", False, "unchanged", (0, 12)),
        ):
            with self.subTest(track=track, solution=solution):
                pod = Pod(self, "1", track)
                pod.deliver(solution=solution)
                record, summary = pod.run(wait=15 if track == "advanced" else 40)
                self.assertEqual(record["work"], work)
                self.assertEqual(summary["outcome"], "graded")
                self.assertEqual(pod.points(), expected)
                if track == "advanced":  # the delivered app.py holds only comments
                    self.assertEqual(summary["closed"], [5000])
                    self.assertIn("shortener stopped with exit code 0", pod.service_log())

    def test_module1_broken_variants(self):
        solution = (ASSETS["1"] / "solutions/app.py").read_text()
        variants = {
            "crash": ("raise SystemExit('this service is broken')\n" + solution, (0, 12)),
            "other port": (solution.replace('"5000"', '"5050"'), (0, 12)),
            "slow start": ("import time\ntime.sleep(8)\n" + solution, (12, 12)),
            "writes to home": (solution.replace(
                "app = Flask(__name__)",
                "app = Flask(__name__)\nimport os\nopen(os.path.expanduser('~/visits.log'), 'a').write('x')"),
                (12, 12)),
            "stops halfway": (solution.replace(
                "app = Flask(__name__)",
                "app = Flask(__name__)\nimport os\ncount = [0]\n"
                "@app.before_request\ndef stop():\n    count[0] += 1\n    if count[0] > 40:\n        os._exit(3)"),
                None),
        }
        for name, (code, expected) in variants.items():
            with self.subTest(variant=name):
                pod = Pod(self, "1", "intermediate")
                pod.deliver()
                pod.write("intermediate/app.py", code)
                # The group's own copy of the tests does not count.
                pod.write("tests/test_api.py", "print('12/12   tested by this script')\n")
                record, summary = pod.run(wait=8 if name in ("crash", "other port") else 20)
                self.assertEqual(record["work"], "changed")
                if expected:
                    self.assertEqual(pod.points(), expected)
                if name == "crash":
                    self.assertIn("this service is broken", pod.service_log())
                    self.assertEqual(summary["closed"], [5000])
                if name == "other port":
                    self.assertEqual(summary["closed"], [5000])
                    if Path("/proc/net/tcp").exists():
                        self.assertIn(5050, summary["listening"])
                if name == "writes to home":
                    self.assertTrue((pod.root / "home/visits.log").is_file())
                if name == "stops halfway":
                    self.assertLess(pod.points()[0], 12)
                    self.assertIn("shortener stopped with exit code 3", pod.service_log())

    def test_a_service_that_never_answers_times_out(self):
        pod = Pod(self, "1", "intermediate")
        pod.deliver()
        pod.write("intermediate/app.py", "import socket, time\nserver = socket.socket()\n"
                  "server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
                  "server.bind(('127.0.0.1', 5000))\nserver.listen(50)\ntime.sleep(600)\n")
        _, summary = pod.run(wait=20, timeout=15)
        self.assertEqual(summary["outcome"], "timed out")
        self.assertIn("[stopped after 15 s]", pod.block["files"]["tests.txt"])

    def test_module2_reference_and_beginner(self):
        for track, solution, work in (("intermediate", True, "solution"), ("beginner", False, "unchanged")):
            with self.subTest(track=track):
                pod = Pod(self, "2", track)
                pod.deliver(solution=solution)
                record, summary = pod.run()
                self.assertEqual(record["work"], work)
                self.assertEqual(pod.points(), (11, 11))
                log = pod.service_log()
                self.assertIn("setup_local_keys.sh exited with code 0", log)
                self.assertIn("[auth]", log)
                self.assertIn("[shortener]", log)

    def test_module2_virtual_environment_in_the_track(self):
        pod = Pod(self, "2", "intermediate")
        pod.deliver(solution=True)
        venv.create(pod.folder / "intermediate/.venv", system_site_packages=True, symlinks=True)
        pod.run()
        self.assertIn("using the virtual environment", pod.service_log())
        self.assertEqual(pod.points(), (11, 11))

    def test_module1_audit_of_the_reference_solution(self):
        pod = Pod(self, "1", "intermediate", kind="audit")
        pod.deliver(solution=True)
        _, summary = pod.run(timeout=900)
        self.assertEqual(summary["outcome"], "graded")
        report = json.loads(pod.block["files"]["audit.json"])
        self.assertEqual((report["counts"]["FAIL"], report["counts"]["WARN"], report["counts"]["ERROR"]), (0, 0, 0))
        self.assertIn("# TA audit, Assignment 1", pod.block["files"]["audit.md"])


if __name__ == "__main__":
    unittest.main()
