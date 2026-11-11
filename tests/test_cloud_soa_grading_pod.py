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
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import venv
from pathlib import Path
from unittest import mock

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
        for name in ("workspace", "home", "source", "results", "bundle", "bin", "network", "queries"):
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
                "--results", str(self.root / "results"), "--network", str(self.root / "network"),
                "--queries", str(self.root / "queries"), *extra]

    def prepare(self, *extra, environment=None):
        result = subprocess.run(self.command("prepare", *extra), capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, **(environment or {})))
        self.test.assertEqual(result.returncode, 0, result.stderr)
        self.prepare_log = result.stdout
        return json.loads((self.root / "source/prepare.json").read_text())

    def serve(self, *extra):
        environment = dict(os.environ, PATH=f"{self.root / 'bin'}:{os.environ.get('PATH', '')}")
        self.log = open(self.root / "service.log", "w+")
        self.test.addCleanup(self.log.close)
        self.service = subprocess.Popen(self.command("serve", *extra), stdout=self.log, stderr=subprocess.STDOUT,
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

    def test_every_version_that_groups_may_have_received_counts(self):
        # An earlier cohort's files, or those that the cluster seeds, may differ from this checkout's.
        earlier = "print('as an earlier cohort received it')\n"
        for known, work in ((False, "changed"), (True, "unchanged")):
            with self.subTest(known=known):
                pod = Pod(self, "1", "intermediate")
                pod.deliver()
                pod.write("intermediate/app.py", earlier)
                if known:
                    path = pod.root / "bundle/manifest.json"
                    manifest = json.loads(path.read_text())
                    manifest["delivered"]["intermediate"]["app.py"].append(hashlib.sha256(earlier.encode()).hexdigest())
                    path.write_text(json.dumps(manifest))
                self.assertEqual(pod.prepare()["work"], work)

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

    def test_the_copy_keeps_each_file_s_mode(self):
        pod = Pod(self, "1", "intermediate")
        modes = {"private.pem": 0o600, "run.sh": 0o750, "tool": 0o4755, "read-only.txt": 0o444}
        for name, mode in modes.items():
            pod.write(f"intermediate/{name}", "x")
            (pod.folder / "intermediate" / name).chmod(mode)
        pod_module.copy_tree(pod.folder, pod.root / "home/copy")
        copied = {name: stat.S_IMODE((pod.root / "home/copy/intermediate" / name).stat().st_mode) for name in modes}
        # Readable and writable for the participant, who owns the copy.
        self.assertEqual(copied, dict(modes, **{"read-only.txt": 0o644}))

    def test_folders_more_than_100_levels_deep_are_left_out(self):
        pod = Pod(self, "1", "intermediate")
        deepest = pod.folder.joinpath("intermediate", *["d"] * 100)  # 101 levels below the Module folder
        deepest.mkdir(parents=True)
        (deepest / "x.txt").write_text("x")
        (deepest.parent / "y.txt").write_text("y")
        copied, skipped = pod_module.copy_tree(pod.folder, pod.root / "home/copy")
        self.assertEqual(copied, {"files": 1, "bytes": 1})  # y.txt
        self.assertEqual(skipped, ["intermediate/" + "d/" * 99 + "d: more than 100 folders deep"])

    def test_a_module_folder_that_is_a_link_is_copied(self):
        # examine() follows such a link, and so does the copy.
        pod = Pod(self, "1", "intermediate")
        pod.deliver(solution=True)
        pod.folder.rename(pod.folder.with_name("my-module-1"))
        pod.folder.symlink_to("my-module-1")
        self.assertEqual(pod.prepare()["work"], "solution")
        self.assertTrue((pod.root / "home/Cloud-Computing-SOA/Module-1/intermediate/app.py").is_file())

    def copy_in_time(self, pod, pipe=None):
        """copy_tree in a thread, so that a copy that waits on a pipe fails the test instead of hanging it."""
        result = []

        def copy():
            try:
                result.append(pod_module.copy_tree(pod.folder, pod.root / "home/copy"))
            except Exception as error:
                result.append(error)

        thread = threading.Thread(target=copy, daemon=True)
        thread.start()
        thread.join(30)
        if thread.is_alive():
            if pipe:
                os.close(os.open(pipe, os.O_WRONLY | os.O_NONBLOCK))  # a writer, so that the reader goes on
            thread.join(5)
            self.fail("the copy hangs")
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]

    def test_a_file_swapped_during_the_copy_is_skipped(self):
        # The group's server swaps a file for a link or a pipe just after prepare looked at it.
        for kind in ("link", "pipe"):
            with self.subTest(kind=kind):
                pod = Pod(self, "1", "intermediate")
                pod.write("intermediate/notes.txt", "notes")
                pod.write("intermediate/run.sh", "echo run")
                (pod.folder / "intermediate/run.sh").chmod(0o750)
                outside = pod.root / "outside.txt"
                outside.write_text("not the group's file")
                outside.chmod(0o600)
                swapped = str(pod.folder / "intermediate/notes.txt")
                real = {"lstat": os.lstat, "stat": os.stat}

                def looked_at(call):
                    def look(path, *arguments, **keywords):
                        info = real[call](path, *arguments, **keywords)
                        if os.path.basename(str(path)) == "notes.txt" and stat.S_ISREG(info.st_mode) \
                                and not os.path.lexists(swapped + ".old"):
                            os.rename(swapped, swapped + ".old")
                            if kind == "link":
                                os.symlink(outside, swapped)
                            else:
                                os.mkfifo(swapped)
                        return info
                    return look

                os.lstat, os.stat = looked_at("lstat"), looked_at("stat")
                try:
                    copied, skipped = self.copy_in_time(pod, pipe=swapped if kind == "pipe" else None)
                finally:
                    os.lstat, os.stat = real["lstat"], real["stat"]
                self.assertTrue(os.path.lexists(swapped + ".old"))  # the swap happened
                # Neither its mode set nor its content copied through the link.
                self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o600)
                self.assertFalse(os.path.lexists(pod.root / "home/copy/intermediate/notes.txt"))
                self.assertEqual([entry.split(":")[0] for entry in skipped], ["intermediate/notes.txt"])
                # The other file is copied, with its mode.
                self.assertEqual(stat.S_IMODE((pod.root / "home/copy/intermediate/run.sh").stat().st_mode), 0o750)
                self.assertEqual(copied, {"files": 1, "bytes": 8})

    def test_a_folder_swapped_during_the_copy_is_skipped(self):
        # The group's server swaps a folder for a link to another folder, a pipe or a file just
        # before prepare opens it; the copy goes on with the rest.
        for kind in ("link", "pipe", "file"):
            with self.subTest(kind=kind):
                pod = Pod(self, "1", "intermediate")
                pod.write("intermediate/data/urls.json", "{}")
                pod.write("intermediate/zz.txt", "copied")
                outside = pod.root / "outside"
                outside.mkdir()
                (outside / "not-the-groups.txt").write_text("not the group's file")
                folder = pod.folder / "intermediate/data"
                real_open, real_scandir = os.open, os.scandir

                def swap():
                    if not os.path.lexists(folder.with_name("data.old")):
                        folder.rename(folder.with_name("data.old"))
                        if kind == "link":
                            folder.symlink_to(outside)
                        elif kind == "pipe":
                            os.mkfifo(folder)
                        else:
                            folder.write_text("now a file")

                def opened(path, flags, *arguments, **keywords):  # each folder opened by name in its parent
                    if path == "data" and keywords.get("dir_fd") is not None:
                        swap()
                    return real_open(path, flags, *arguments, **keywords)

                def listed(path="."):  # os.walk lists each folder by path
                    if str(path) == str(folder):
                        swap()
                    return real_scandir(path)

                os.open, os.scandir = opened, listed
                try:
                    copied, skipped = self.copy_in_time(pod, pipe=str(folder) if kind == "pipe" else None)
                finally:
                    os.open, os.scandir = real_open, real_scandir
                self.assertTrue(os.path.lexists(folder.with_name("data.old")))  # the swap happened
                self.assertEqual(sorted(path.name for path in (pod.root / "home/copy").rglob("*")),
                                 ["intermediate", "zz.txt"])
                self.assertEqual([entry.split(":")[0] for entry in skipped], ["intermediate/data"])
                self.assertEqual(copied, {"files": 1, "bytes": 6})

    def test_the_graded_code_is_kept_from_the_copy_but_no_link(self):
        pod = Pod(self, "2", "intermediate")
        pod.deliver(solution=True)
        self.assertEqual(pod.prepare()["work"], "solution")
        for code in ("auth_service/auth.py", "shortener_service/shortener.py"):
            self.assertEqual((pod.root / "source/code" / code).read_bytes(),
                             (pod.root / "home/Cloud-Computing-SOA/Module-2/intermediate" / code).read_bytes())
        # A link is copied as a link, and its target is not kept.
        pod = Pod(self, "1", "intermediate")
        pod.deliver()
        (pod.root / "outside.py").write_text("print('not the group's file')\n")
        (pod.folder / "intermediate/app.py").unlink()
        os.symlink(pod.root / "outside.py", pod.folder / "intermediate/app.py")
        self.assertEqual(pod.prepare()["work"], "changed")
        self.assertFalse((pod.root / "source/code").exists())

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
        # Also when prepare examines the copy again: no checksums of an earlier look are left.
        self.assertEqual((record["work"], record["files"]), ("too large", {}))

    def test_the_grader_reports_work_it_cannot_grade_without_waiting(self):
        pod = Pod(self, "1", "intermediate")
        pod.prepare()
        started = time.monotonic()
        summary = pod.grade(wait=60)
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual((summary["work"], summary["outcome"]), ("missing", "not graded"))
        self.assertNotIn("tests.txt", pod.block["files"])
        self.assertEqual(pod.block["code"], {})
        (pod.root / "source/prepare.json").unlink()
        self.assertEqual(pod.grade()["work"], "error")


class NetworkHookTests(unittest.TestCase):
    """The hook that writes down network use, in a plain Python process, and how the grader counts its lines."""

    def folder(self):
        temporary = tempfile.TemporaryDirectory(prefix="grading-network-")
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def python(self, code, log):
        hook = self.folder()
        (hook / "sitecustomize.py").write_text(pod_module.HOOK, encoding="utf-8")
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, PYTHONPATH=str(hook), GRADING_NETWORK_LOG=str(log)))
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        return result.stdout

    def test_each_process_writes_at_most_1000_lines_and_a_child_its_own(self):
        log = self.folder()
        self.python("import os, sys\n"
                    "for number in range(1500):\n"
                    "    sys.audit('socket.getaddrinfo', 'host%d.example' % number, 80, 0, 0, 0)\n"
                    "child = os.fork()\n"
                    "if child == 0:\n"
                    "    sys.audit('socket.getaddrinfo', 'child.example', 80, 0, 0, 0)\n"
                    "    os._exit(0)\n"
                    "os.waitpid(child, 0)\n", log)
        self.assertEqual(len(list(log.iterdir())), 2)
        use = pod_module.network_use(log, self.folder())
        self.assertEqual((use["attempts"], use["hosts"], use["cut"], len(use["targets"])), (1001, 1001, True, 20))

    def test_the_grader_reads_only_regular_files_and_hook_lines_within_limits(self):
        # The group's code can write into the folder too.
        log, elsewhere = self.folder(), self.folder()
        (log / "1.log").write_text("lookup ok.example\nconnect\nlookup two words\n" + "x" * 300 + "\n")
        (elsewhere / "secret.log").write_text("lookup leaked.example\n")
        os.symlink(elsewhere / "secret.log", log / "link.log")  # not followed
        os.mkfifo(log / "pipe.log")  # not opened for reading: that would wait for a writer
        use = pod_module.network_use(log, self.folder())
        self.assertEqual((use["attempts"], use["cut"], use["targets"]),
                         (1, False, [{"kind": "lookup", "target": "ok.example", "count": 1}]))
        # More files, longer files or more hosts than the limits: the rest is left out, and that is said.
        for name, text in (("many", None), ("long", "lookup a.example\n" * 20000), ("hosts", None)):
            with self.subTest(name):
                log = self.folder()
                if name == "many":
                    for number in range(pod_module.NETWORK_FILES + 1):
                        (log / f"{number}.log").write_text("lookup a.example\n")
                elif name == "long":
                    (log / "1.log").write_text(text)
                else:
                    for number in range(6):
                        (log / f"{number}.log").write_text("".join(
                            f"lookup h{number}-{line}.example\n" for line in range(1000)))
                use = pod_module.network_use(log, self.folder())
                self.assertTrue(use["cut"])
                self.assertLessEqual(use["hosts"], pod_module.NETWORK_HOSTS)

    def test_lookups_that_python_does_not_report_come_from_the_dns_container(self):
        log, queries = self.folder(), self.folder()
        (log / "7.log").write_text("lookup en.wikipedia.org\nconnect 192.0.2.1:443\n")
        # glibc asks for A and AAAA; dnspython or a C library asks without Python's lookup event.
        (queries / "queries.log").write_text("query en.wikipedia.org\nquery EN.wikipedia.org.\n"
                                             + "query cluster0.mongodb.net\n" * 3 + "query bad name\n")
        use = pod_module.network_use(log, queries)
        self.assertEqual(use["targets"], [
            {"kind": "query", "target": "cluster0.mongodb.net", "count": 3},
            {"kind": "connect", "target": "192.0.2.1:443", "count": 1},
            {"kind": "lookup", "target": "en.wikipedia.org", "count": 1}])
        self.assertEqual(local.network_note({"network": use}),
                         "looked up en.wikipedia.org (1); asked the DNS for cluster0.mongodb.net (3); "
                         "connected to 192.0.2.1:443 (1)")

    def test_the_hook_never_gets_in_the_way(self):
        # A folder that cannot be written: the process goes on as if there were no hook.
        output = self.python("import sys\nsys.audit('socket.getaddrinfo', 'example.com', 80, 0, 0, 0)\n"
                             "print('still running')\n", Path("/nonexistent/folder"))
        self.assertEqual(output, "still running\n")
        self.assertEqual(pod_module.network_use(Path("/nonexistent/folder"), Path("/nonexistent"))["attempts"], 0)
        self.assertEqual(pod_module.network_hook(Path("/nonexistent/folder")), {})


class DnsTests(unittest.TestCase):
    """The dns step: every query refused at once, and its name written down."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="grading-dns-")
        self.addCleanup(temporary.cleanup)
        self.queries = Path(temporary.name)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]

    def start(self):
        process = subprocess.Popen([sys.executable, "-s", "-E", "-B", str(POD_SCRIPT), "dns", "--module", "1",
                                    "--track", "intermediate", "--queries", str(self.queries),
                                    "--dns-port", str(self.port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.addCleanup(lambda: (process.terminate(), process.wait(10), process.stdout.close()))
        deadline = time.monotonic() + 20
        while not (self.queries / "ready").exists():
            self.assertLess(time.monotonic(), deadline, "dns did not get ready")
            time.sleep(0.1)
        return process

    @staticmethod
    def query(name, ident=0x1234, kind=1):
        labels = b"".join(bytes([len(label)]) + label.encode() for label in name.split("."))
        return ident.to_bytes(2, "big") + b"\x01\x00\x00\x01" + bytes(6) + labels + b"\x00" + \
            kind.to_bytes(2, "big") + b"\x00\x01"

    def test_queries_are_refused_at_once_and_written_down(self):
        self.start()
        question = self.query("db.example.com")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.settimeout(2)
            udp.sendto(question, ("127.0.0.1", self.port))
            answer = udp.recv(512)
            # Not queries: an answer, and a message too short; nothing is sent back.
            udp.sendto(b"\x12\x34\x81\x80" + question[4:], ("127.0.0.1", self.port))
            udp.sendto(b"\x00", ("127.0.0.1", self.port))
            udp.sendto(self.query("cluster0.mongodb.net", ident=7, kind=33), ("127.0.0.1", self.port))  # SRV
            self.assertEqual(udp.recv(512)[:2], b"\x00\x07")
        # The same identifier and question; QR, RD and REFUSED; one question and no answer.
        self.assertEqual(answer, b"\x12\x34\x81\x05\x00\x01" + bytes(6) + question[12:])
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as tcp:
            message = self.query("over.tcp.example", ident=9)
            tcp.sendall(len(message).to_bytes(2, "big") + message)
            size = int.from_bytes(tcp.recv(2), "big")
            self.assertEqual(tcp.recv(size)[:4], b"\x00\x09\x81\x05")
        log = (self.queries / "queries.log").read_text().splitlines()
        self.assertEqual(log, ["query db.example.com", "query cluster0.mongodb.net", "query over.tcp.example"])

    def test_a_port_it_cannot_open_leaves_lookups_unanswered_but_the_pod_goes_on(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as taken:
            taken.bind(("127.0.0.1", 0))
            taken.settimeout(5)
            self.port = taken.getsockname()[1]
            process = self.start()
            time.sleep(1)
            self.assertIsNone(process.poll())  # still running, so that the pod is not held up
            # Lookups go to what holds the port instead, and dns writes nothing down.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.sendto(self.query("db.example.com"), ("127.0.0.1", self.port))
            self.assertEqual(taken.recv(512), self.query("db.example.com"))
            time.sleep(0.5)
            self.assertIsNone(process.poll())
        self.assertFalse((self.queries / "queries.log").exists())
        process.terminate()
        output = process.communicate(timeout=10)[0].decode()
        self.assertIn(f"cannot answer name lookups on 127.0.0.1:{self.port}", output)


class SetupTests(unittest.TestCase):
    """Module 2's setup script runs before the services, nothing that it starts keeps running, and the
    grader waits for the services that serve starts."""

    # Holds a port, as a service started by the script would, and writes on.
    LISTENER = ("import socket, time\nserver = socket.socket()\nserver.bind(('127.0.0.1', 0))\nserver.listen()\n"
                "open('port', 'w').write(str(server.getsockname()[1]))\n"
                "while True:\n    print('serving', flush=True)\n    time.sleep(0.2)\n")

    def run_setup(self, script, seconds):
        temporary = tempfile.TemporaryDirectory(prefix="grading-setup-")
        self.addCleanup(temporary.cleanup)
        track = Path(temporary.name)
        (track / "listener.py").write_text(self.LISTENER)
        script = script.replace("LISTENER", f"{shlex.quote(sys.executable)} listener.py")
        (track / "setup_local_keys.sh").write_text(script)
        output = io.StringIO()
        started = time.monotonic()
        with contextlib.redirect_stdout(output):
            pod_module.run_setup("setup_local_keys.sh", track, dict(os.environ), seconds, [])
        port = int((track / "port").read_text()) if (track / "port").exists() else None
        return output.getvalue(), time.monotonic() - started, port

    def assert_closed(self, port):
        deadline = time.monotonic() + 5
        while True:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) != 0:
                    return
            self.assertLess(time.monotonic(), deadline, f"port {port} is still open")
            time.sleep(0.1)

    def test_what_the_script_leaves_running_is_stopped(self):
        for started in ("LISTENER &", "LISTENER >/dev/null 2>&1 &"):
            with self.subTest(started=started):
                log, seconds, port = self.run_setup(
                    f"echo generating keys\n{started}\nwhile [ ! -s port ]; do sleep 0.1; done\necho done\n", 30)
                self.assertLess(seconds, 10)  # the script ended: no waiting for the 30 s limit
                self.assertIn("[setup] generating keys\n", log)
                self.assertIn("[setup] done\n", log)
                self.assertTrue(log.endswith("[runner] setup_local_keys.sh exited with code 0; "
                                             "stopped what it left running\n"), log)
                self.assert_closed(port)

    def test_a_script_that_does_not_end_is_stopped_and_its_output_kept(self):
        # As "import auth" in setup_local_keys.sh, when auth.py has no __main__ guard.
        log, seconds, port = self.run_setup("echo importing auth\nLISTENER\n", 3)
        self.assertLess(seconds, 10)
        self.assertIn("[setup] importing auth\n[setup] serving\n", log)
        self.assertTrue(log.endswith("[runner] setup_local_keys.sh did not finish within 3 s; stopped it\n"), log)
        self.assert_closed(port)

    def test_a_script_that_leaves_nothing_running(self):
        log, seconds, port = self.run_setup("echo keys ready\nexit 3\n", 30)
        self.assertLess(seconds, 10)
        self.assertEqual(log, "[runner] bash setup_local_keys.sh\n[setup] keys ready\n"
                              "[runner] setup_local_keys.sh exited with code 3\n")
        self.assertIsNone(port)

    def test_in_the_pod_every_other_process_of_the_container_is_stopped(self):
        # There serve is the container's first process, so also what left the script's process group
        # is stopped (seen in the end-to-end test). kill(-1) is faked: here it would stop every
        # process of the user who runs the tests.
        calls = []

        def kill(pid, number):
            calls.append(("kill", pid, number))

        def waitpid(pid, options):
            calls.append(("waitpid", pid))
            raise ChildProcessError  # no process left

        # getpid last in, first out: it never says 1 while the real kill is in place.
        with mock.patch.object(pod_module.os, "kill", kill), \
                mock.patch.object(pod_module.os, "killpg", side_effect=AssertionError("killpg")), \
                mock.patch.object(pod_module.os, "waitpid", waitpid), \
                mock.patch.object(pod_module.os, "getpid", return_value=1):
            self.assertTrue(pod_module.stop_left(4321))
        self.assertEqual(calls, [("waitpid", -1), ("kill", -1, 0), ("kill", -1, signal.SIGKILL), ("waitpid", -1)])

    def test_the_grader_waits_until_serve_has_started_the_services(self):
        # Until then, a port can answer from what the setup script left, which serve stops.
        with socket.socket() as server, tempfile.TemporaryDirectory(prefix="grading-wait-") as folder:
            server.bind(("127.0.0.1", 0))
            server.listen(50)
            port, started = server.getsockname()[1], Path(folder, pod_module.STARTED)
            waiting, waited = pod_module.wait_for_ports([port], 2, started)
            self.assertEqual(waiting, [])
            self.assertGreaterEqual(waited, 2)
            started.touch()
            waiting, waited = pod_module.wait_for_ports([port], 30, started)
            self.assertEqual(waiting, [])
            self.assertLess(waited, 1)


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
                self.assertEqual(summary["network"]["attempts"], 0)
                # The graded code comes back with the results.
                self.assertEqual(base64.b64decode(pod.block["code"]["app.py"]),
                                 (pod.folder / track / "app.py").read_bytes())
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

    def test_the_hosts_that_the_group_s_code_tries_to_reach_are_written_down(self):
        # Audit events as name lookups and connections raise them, without any traffic.
        probe = (
            "import socket, sys\n"
            "for _ in range(3):\n"
            "    sys.audit('socket.getaddrinfo', 'en.wikipedia.org', 443, 0, 0, 0)\n"
            "sys.audit('socket.gethostbyname', 'example.com')\n"
            "tcp, udp = socket.socket(), socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            "sys.audit('socket.connect', tcp, ('192.0.2.1', 443))\n"
            "sys.audit('socket.connect', tcp, ('2001:db8::1', 443, 0, 0))\n"
            "# Not counted: the pod itself, an address that needs no lookup, and a UDP socket's connect().\n"
            "sys.audit('socket.getaddrinfo', 'localhost', 5001, 0, 0, 0)\n"
            "sys.audit('socket.getaddrinfo', socket.gethostname(), 5001, 0, 0, 0)\n"
            "sys.audit('socket.getaddrinfo', '192.0.2.1', 443, 0, 0, 0)\n"
            "sys.audit('socket.connect', tcp, ('127.0.0.1', 5001))\n"
            "sys.audit('socket.connect', udp, ('10.253.155.219', 58162))\n"
            "tcp.close()\n"
            "udp.close()\n"
        )
        pod = Pod(self, "1", "intermediate")
        pod.deliver()
        pod.write("intermediate/app.py", probe + (ASSETS["1"] / "solutions/app.py").read_text())
        _, summary = pod.run()
        self.assertEqual(pod.points(), (12, 12))
        self.assertEqual(summary["network"], {"attempts": 6, "hosts": 4, "cut": False, "targets": [
            {"kind": "lookup", "target": "en.wikipedia.org", "count": 3},
            {"kind": "connect", "target": "192.0.2.1:443", "count": 1},
            {"kind": "connect", "target": "[2001:db8::1]:443", "count": 1},
            {"kind": "lookup", "target": "example.com", "count": 1}]})
        self.assertEqual(local.network_note(summary),
                         "looked up en.wikipedia.org (3), example.com (1); connected to 192.0.2.1:443 (1), "
                         "[2001:db8::1]:443 (1)")
        # Every line was written by a process of the group's code: the files are named after them.
        # serve's note that the services are started is the only other file.
        names = {path.name for path in (pod.root / "network").iterdir()} - {pod_module.STARTED}
        self.assertTrue(names and all(name.endswith(".log") and name[:-4].isdigit() for name in names), names)

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
                self.assertLess(summary["waited"], 30)  # serve told the grader that the services are started
                self.assertEqual(summary["network"]["attempts"], 0)  # the services talk over the pod's loopback
                self.assertEqual({code: base64.b64decode(data) for code, data in pod.block["code"].items()},
                                 {code: (pod.folder / track / code).read_bytes()
                                  for code in ("auth_service/auth.py", "shortener_service/shortener.py")})
                log = pod.service_log()
                self.assertIn("setup_local_keys.sh exited with code 0\n", log)
                self.assertIn("[auth]", log)
                self.assertIn("[shortener]", log)

    def test_module2_setup_script_that_starts_the_auth_service(self):
        # The group made its keys, then dropped auth.py's __main__ guard: the setup
        # script's "import auth" now serves on port 5001 and never ends.
        pod = Pod(self, "2", "intermediate")
        pod.deliver(solution=True)
        track = pod.folder / "intermediate"
        subprocess.run(["bash", "setup_local_keys.sh"], cwd=track, check=True, capture_output=True, timeout=60,
                       env=dict(os.environ, PATH=f"{pod.root / 'bin'}:{os.environ.get('PATH', '')}"))
        auth = track / "auth_service/auth.py"
        code = auth.read_text()
        for old, new in (('if __name__ == "__main__":', "if True:"),
                         ("def login_user():\n", "def login_user():\n    print('login request')\n")):
            self.assertIn(old, code)
            code = code.replace(old, new)
        auth.write_text(code)
        pod.prepare()
        pod.serve("--setup-timeout", "5")
        pod.grade()
        pod.stop()
        self.assertEqual(pod.points(), (11, 11))
        log = pod.service_log()
        self.assertIn("setup_local_keys.sh did not finish within 5 s; stopped it\n", log)
        self.assertIn("[auth] login request\n", log)  # the service that serve started answered

    def test_the_grader_tests_the_services_that_serve_starts(self):
        # The setup script holds both ports for a while with servers that are not the group's
        # services; serve stops them and starts the services. Its note from before a restart
        # of the container does not count.
        pod = Pod(self, "2", "intermediate")
        pod.deliver(solution=True)
        setup = pod.folder / "intermediate/setup_local_keys.sh"
        setup.write_text(setup.read_text() + "".join(
            f"python -m http.server {port} --bind 127.0.0.1 >/dev/null 2>&1 &\n" for port in (5000, 5001))
            + "sleep 4\n")
        pod.prepare()
        (pod.root / "network" / pod_module.STARTED).touch()
        pod.serve()
        pod.grade()
        pod.stop()
        self.assertEqual(pod.points(), (11, 11))
        self.assertIn("setup_local_keys.sh exited with code 0; stopped what it left running\n", pod.service_log())

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
