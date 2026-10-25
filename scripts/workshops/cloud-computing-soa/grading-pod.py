"""Grading pod: copy a group's work, start its services, grade them.

The organiser's grading entries (grading-main.sh) start one pod per group with
the participants' notebook image. This script runs in its three containers,
as the participant (uid 1000):

    prepare  (init container) waits until the pod's network rules are in
             force, copies Cloud-Computing-SOA/Module-N from the group's
             volume, which is mounted read-only, into an empty home at the same
             path as in JupyterHub, and compares the track's code with the
             files the group received and with the reference solution.
    serve    (sidecar) starts the group's services in that copy as the
             participant instructions do, with the group's ~/.local packages,
             and logs their output. A service that stops is not restarted.
    grade    (main container) waits for the services, runs the grading script
             or the TA audit against them, and prints the results as one block
             that the organiser collects with kubectl logs.

Only the grade container sees the grading scripts, the audit and the results;
the group's code runs in the serve container and cannot read or change them.
The script needs Python 3.8 or newer and the standard library; the grading
script and the audit also need requests, which the notebook image has.
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

MODULES = {
    "1": {
        "folder": "Module-1",
        "code": ["app.py"],
        "services": [("shortener", ".", "app.py", 5000)],
        "tests": ["test_api.py", "--url", "http://127.0.0.1:5000"],
        "audit": ["audit_a1.py", "--url", "http://127.0.0.1:5000"],
    },
    "2": {
        "folder": "Module-2",
        "code": ["auth_service/auth.py", "shortener_service/shortener.py"],
        "setup": "setup_local_keys.sh",
        # The authentication service starts first: the shortener may need its public key.
        "services": [("auth", "auth_service", "auth.py", 5001),
                     ("shortener", "shortener_service", "shortener.py", 5000)],
        "tests": ["test_microservices.py", "--assignment", "2",
                  "--url", "http://127.0.0.1:5000", "--auth-url", "http://127.0.0.1:5001"],
        "audit": ["audit_a2.py", "--url", "http://127.0.0.1:5000", "--auth-url", "http://127.0.0.1:5001"],
    },
}
TRACKS = ("beginner", "intermediate", "advanced", "solutions")
COPY_LIMIT = 400 * 2**20   # bytes of a Module folder that are copied at most
COPY_FILES = 20000         # files of a Module folder that are copied at most
SOURCE_LIMIT = 20 * 2**20  # bytes of the track's source kept for the audit
NOT_SOURCE = {".git", ".venv", "venv", "env", "__pycache__", "node_modules", "site-packages",
              ".ipynb_checkpoints"}
FILE_LIMIT = 2 * 2**20     # bytes of one result file returned to the organiser
KUBELET = 10250            # the kubelet's port on every node
BEGIN = "===== GRADING RESULTS BEGIN ====="
END = "===== GRADING RESULTS END ====="


def say(text):
    print(f"[runner] {text}", flush=True)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------- prepare

def measure(folder):
    """Number of entries and bytes of regular files below folder, without following links."""
    count = size = 0
    for root, dirs, files in os.walk(folder):
        for name in dirs + files:
            count += 1
            try:
                info = os.lstat(os.path.join(root, name))
            except OSError:  # removed meanwhile by the group's running server
                continue
            if stat.S_ISREG(info.st_mode):
                size += info.st_size
    return count, size


def examine(found, track, module, manifest):
    """What the group did with the track: missing, unchanged, solution or changed."""
    if not found.is_dir():
        return {"work": "missing", "reason": f"no {module['folder']} folder"}
    tracks = [name for name in TRACKS if (found / name).is_dir()]
    count, size = measure(found)
    if count > COPY_FILES or size > COPY_LIMIT:
        return {"work": "too large", "tracks": tracks,
                "reason": f"{module['folder']} holds {count} files and folders, {size / 2**20:.0f} MB"}
    files = {}
    for relative in module["code"]:
        path = found / track / relative
        if not path.is_file():
            files[relative] = {"state": "missing"}
            continue
        digest = sha256(path)
        if digest == manifest["delivered"].get(track, {}).get(relative):
            state = "delivered"
        elif digest == manifest["solution"].get(relative):
            state = "solution"
        else:
            state = "changed"
        files[relative] = {"state": state, "sha256": digest, "bytes": path.stat().st_size}
    states = {item["state"] for item in files.values()}
    missing = [relative for relative, item in files.items() if item["state"] == "missing"]
    if missing:
        work, reason = "missing", f"no {track}/{missing[0]}"
    elif states == {"delivered"}:
        work, reason = "unchanged", "the files the group received, unchanged"
    elif states == {"solution"}:
        work, reason = "solution", "the reference solution"
    else:
        work, reason = "changed", ""
    return {"work": work, "reason": reason, "files": files, "tracks": tracks}


def copy_tree(source, destination):
    """Copy files, folders and symbolic links; skip other entries and unreadable files.

    Nothing is written through a link: the group's running server may change
    the workspace while it is copied.
    """
    copied = {"files": 0, "bytes": 0}
    skipped = []
    for root, dirs, files in os.walk(source):
        relative = Path(root).relative_to(source)
        target = destination / relative
        if target.is_symlink():
            dirs[:] = []
            continue
        target.mkdir(parents=True, exist_ok=True)
        for name in dirs + files:
            path, into = Path(root, name), target / name
            try:
                if os.path.lexists(into):
                    continue
                info = os.lstat(path)
                if stat.S_ISLNK(info.st_mode):
                    os.symlink(os.readlink(path), into)
                elif stat.S_ISREG(info.st_mode):
                    shutil.copyfile(path, into, follow_symlinks=False)
                    os.chmod(into, stat.S_IMODE(info.st_mode) | stat.S_IRUSR | stat.S_IWUSR)
                    copied["files"] += 1
                    copied["bytes"] += info.st_size
                elif not stat.S_ISDIR(info.st_mode):
                    skipped.append(f"{(relative / name).as_posix()}: not a regular file")
            except OSError as error:
                skipped.append(f"{(relative / name).as_posix()}: {error.strerror or error}")
    return copied, skipped


def keep_source(track, destination):
    """The track's source files for the audit: no links, environments or caches."""
    kept = 0
    for root, dirs, files in os.walk(track):
        dirs[:] = sorted(name for name in dirs if name not in NOT_SOURCE)
        for name in sorted(files):
            path = Path(root, name)
            into = destination / path.relative_to(track)
            try:
                info = os.lstat(path)
                if not stat.S_ISREG(info.st_mode) or kept + info.st_size > SOURCE_LIMIT:
                    continue
                into.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, into, follow_symlinks=False)
            except OSError:
                continue
            kept += info.st_size


def rules_in_force(seconds):
    """Seconds until the pod's NetworkPolicy is in force, or None if it is not after `seconds`.

    A new pod has no network rules for a moment. They are in force once neither
    the Kubernetes API nor the kubelet on the pod's node answers, which both
    egress settings block: twice in a row, so that one lost connection attempt
    does not count. The kubelet answers whenever the pod runs, also while the API
    is down.
    """
    targets = [(os.environ.get("KUBERNETES_SERVICE_HOST"), os.environ.get("KUBERNETES_SERVICE_PORT", "")),
               (os.environ.get("HOST_IP"), str(KUBELET))]
    if not all(host and port.isdigit() for host, port in targets):
        raise RuntimeError("cannot check the network rules: KUBERNETES_SERVICE_HOST, _PORT or HOST_IP is not set")

    def answers(host, port):
        try:
            with socket.create_connection((host, int(port)), timeout=2):
                return True
        except OSError:
            return False

    started, blocked = time.monotonic(), 0
    while True:
        blocked = 0 if any(answers(host, port) for host, port in targets) else blocked + 1
        if blocked == 2:
            return round(time.monotonic() - started, 1)
        if time.monotonic() - started > seconds:
            return None
        time.sleep(0.5)


def prepare(args):
    module = MODULES[args.module]
    found = Path(args.workspace, "Cloud-Computing-SOA", module["folder"])
    record = {"module": args.module, "track": args.track, "work": "error", "reason": "",
              "files": {}, "tracks": [], "copied": {"files": 0, "bytes": 0}, "skipped": []}
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        record.update(examine(found, args.track, module, manifest))
        if record["work"] in ("unchanged", "solution", "changed") and args.policy_wait:
            # The group's code starts only from the copy, so the rules must be in force before it is made.
            waited = rules_in_force(args.policy_wait)
            record["network_rules"] = "not in force" if waited is None else f"in force after {waited} s"
            say(f"network rules {record['network_rules']}")
            if waited is None:
                record["work"], record["reason"] = "error", (
                    f"the pod's network rules were not in force after {args.policy_wait} s, so the group's code "
                    "was not run; does the cluster enforce NetworkPolicies?")
        if record["work"] in ("unchanged", "solution", "changed"):
            keep_source(found / args.track, Path(args.source, "track"))
            copy = Path(args.home, "Cloud-Computing-SOA", module["folder"])
            record["copied"], skipped = copy_tree(found, copy)
            record["skipped"] = skipped[:50] + ([f"... {len(skipped) - 50} more"] if len(skipped) > 50 else [])
    except Exception as error:  # the grader reports it; the pod goes on
        record["work"], record["reason"] = "error", f"prepare: {type(error).__name__}: {error}"
    Path(args.source, "prepare.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    say(f"work: {record['work']}{': ' + record['reason'] if record['reason'] else ''}")


# ---------------------------------------------------------------- serve

def interpreter(track):
    """A virtual environment in the track or Module folder, else the image's python."""
    for folder in (track, track.parent):
        for name in (".venv", "venv", "env"):
            python = folder / name / "bin" / "python"
            if (folder / name / "pyvenv.cfg").is_file() and os.access(python, os.X_OK):
                return folder / name
    return None


def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def relay(process, name):
    """Copy a process's output to the container log, line by line, and report its end."""
    def copy():
        for line in iter(process.stdout.readline, b""):
            print(f"[{name}] {line.decode('utf-8', 'replace').rstrip()}", flush=True)
        say(f"{name} stopped with exit code {process.wait()}")
    threading.Thread(target=copy, daemon=True).start()


def end(process):
    for signal_number, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 3)):
        try:
            os.killpg(process.pid, signal_number)
        except OSError:
            return
        try:
            process.wait(wait)
            return
        except subprocess.TimeoutExpired:
            continue


def serve(args):
    module = MODULES[args.module]
    track = Path(args.home, "Cloud-Computing-SOA", module["folder"], args.track)
    running = []

    def stop(signal_number, frame):
        say("the pod ends: stopping the services")
        for _, process in running:
            end(process)
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    if all((track / relative).is_file() for relative in module["code"]):
        # As in the participant's terminal, plus the packages in the group's ~/.local.
        environment = dict(os.environ, HOME=args.home, PYTHONUNBUFFERED="1",
                           PYTHONUSERBASE=str(Path(args.workspace, ".local")))
        python = "python"
        venv = interpreter(track)
        if venv:
            environment.update(VIRTUAL_ENV=str(venv), PATH=f"{venv}/bin:{environment.get('PATH', '')}")
            python = str(venv / "bin" / "python")
            say(f"using the virtual environment {venv}")
        setup = module.get("setup")
        if setup and (track / setup).is_file():
            say(f"bash {setup}")
            try:
                result = subprocess.run(["bash", setup], cwd=track, env=environment, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, timeout=60)
                for line in result.stdout.decode("utf-8", "replace").splitlines():
                    print(f"[setup] {line}", flush=True)
                say(f"{setup} exited with code {result.returncode}")
            except subprocess.TimeoutExpired:
                say(f"{setup} did not finish within 60 s")
        for name, folder, script, port in module["services"]:
            say(f"cd {Path(folder, script).parent.as_posix()} && python {script}")
            try:
                process = subprocess.Popen([python, script], cwd=track / folder, env=environment,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           start_new_session=True)
            except OSError as error:
                say(f"{name}: cannot start: {error}")
                continue
            relay(process, name)
            running.append((name, process))
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and process.poll() is None and not port_open(port):
                time.sleep(0.5)
    else:
        say(f"nothing to start: {track} lacks {', '.join(module['code'])}")
    while True:  # the pod stops this container when the grader is done
        time.sleep(3600)


# ---------------------------------------------------------------- grade

def listening_ports():
    """TCP ports that something in the pod listens on (the containers share the network)."""
    ports = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) > 3 and fields[3] == "0A":
                ports.add(int(fields[1].rsplit(":", 1)[1], 16))
    return sorted(ports)


def wait_for_ports(ports, seconds):
    started = time.monotonic()
    while True:
        waiting = [port for port in ports if not port_open(port)]
        if not waiting or time.monotonic() - started > seconds:
            return waiting, round(time.monotonic() - started, 1)
        time.sleep(1)


def readable(path):
    """The file as text, cut at 2 MB; None for a JSON file that is larger (cut, it would not parse)."""
    data = path.read_bytes()
    if len(data) > FILE_LIMIT:
        if path.suffix == ".json":
            return None
        data = data[:FILE_LIMIT] + b"\n[cut at 2 MB]\n"
    return data.decode("utf-8", "replace")


def grade(args):
    module = MODULES[args.module]
    results, bundle, source = Path(args.results), Path(args.bundle), Path(args.source)
    summary = {"module": args.module, "kind": args.kind, "track": args.track}
    files = {}
    started = time.monotonic()
    try:
        try:
            record = json.loads((source / "prepare.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {"work": "error", "reason": "prepare left no record"}
        files["prepare.json"] = json.dumps(record, indent=2) + "\n"
        summary.update(work=record.get("work"), reason=record.get("reason", ""))
        if record.get("work") in ("missing", "too large", "error"):
            summary["outcome"] = "not graded"
        else:
            ports = [port for *_, port in module["services"]]
            waiting, waited = wait_for_ports(ports, args.wait)
            summary.update(waited=waited, closed=waiting, listening=listening_ports())
            script, *options = module[args.kind]
            command = [sys.executable, "-s", "-E", "-B", str(bundle / script), *options]
            if args.kind == "tests":
                command += ["--json", str(results / "tests.json")]
            else:
                for flag, folder in (("--auth-source", "auth_service"), ("--shortener-source", "shortener_service")):
                    if args.module == "2" and (source / "track" / folder).is_dir():
                        command += [flag, str(source / "track" / folder)]
                command += ["--report", str(results / "audit.md"), "--json", str(results / "audit.json")]
            try:
                run = subprocess.run(command, cwd=results, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     timeout=args.timeout)
                output, summary["exit"] = run.stdout, run.returncode
                summary["outcome"] = "graded"
            except subprocess.TimeoutExpired as error:
                output = error.stdout or b""
                summary["outcome"] = "timed out"
                output += f"\n[stopped after {args.timeout} s]\n".encode()
            (results / f"{args.kind}.txt").write_bytes(output)
    except Exception as error:  # report what happened instead of failing the pod
        summary.update(outcome="error", error=f"{type(error).__name__}: {error}")
    summary["seconds"] = round(time.monotonic() - started, 1)
    for name in ("tests.txt", "tests.json", "audit.txt", "audit.md", "audit.json"):
        if (results / name).is_file():
            text = readable(results / name)
            if text is None:
                summary.setdefault("dropped", []).append(f"{name}: larger than 2 MB")
            else:
                files[name] = text
    files["grade.json"] = json.dumps(summary, indent=2) + "\n"
    say(f"{summary.get('work')}, {summary.get('outcome')}")
    block = base64.b64encode(gzip.compress(json.dumps({"summary": summary, "files": files}).encode())).decode()
    print(BEGIN)
    for start in range(0, len(block), 76):
        print(block[start:start + 76])
    print(END, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("step", choices=("prepare", "serve", "grade"))
    parser.add_argument("--module", choices=sorted(MODULES), required=True)
    parser.add_argument("--track", choices=TRACKS[:3], required=True)
    parser.add_argument("--kind", choices=("tests", "audit"), default="tests")
    parser.add_argument("--workspace", default="/workspace", help="the group's volume, read-only")
    parser.add_argument("--home", default="/home/jovyan", help="the empty home for the copy")
    parser.add_argument("--source", default="/source", help="what prepare leaves for the grader")
    parser.add_argument("--manifest", default="/runner/manifest.json")
    parser.add_argument("--bundle", default="/grading", help="the grading script or the audit")
    parser.add_argument("--results", default="/results")
    parser.add_argument("--policy-wait", type=int, default=0,
                        help="seconds prepare waits for the pod's network rules (0: no check, outside Kubernetes)")
    parser.add_argument("--wait", type=int, default=150, help="seconds to wait for the services")
    parser.add_argument("--timeout", type=int, default=600, help="seconds for the grading script or audit")
    args = parser.parse_args()
    for name in ("workspace", "home", "source", "manifest", "bundle", "results"):
        setattr(args, name, os.path.abspath(getattr(args, name)))
    {"prepare": prepare, "serve": serve, "grade": grade}[args.step](args)


if __name__ == "__main__":
    main()
