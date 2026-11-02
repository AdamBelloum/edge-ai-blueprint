#!/usr/bin/env python3
"""Organiser-approved probe using this participant's existing managed identity.

No credentials are staged, no workspace is published, and no containers are
managed. Requires a submission-free maintenance window; this client neither
reserves resources nor acquires the remote Docker host's submission lock.
One successful probe does not establish cohort capacity or full activity readiness.
"""
import argparse
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
from urllib.parse import urlsplit
import uuid

ASSET_SHA256 = {'02_spark_via_livy.py': '3c6f363f76b49ce46f724c27ea4f26f9064f20667a807882a57717a24d6e4b82', 'spark_livy_access.py': '6332271400def883056b4e49b88410f38ff9417c7baa3994269d31d240b7e552'}
MARKER = "DIGITAFRICA_PARTICIPANT_PROBE:"
EXPECTED = {
    "sum": 499500, "partitions": 2, "worker_hosts": ["spark-worker-1"],
    "master": "spark://spark-master:7077", "spark_version": "3.5.3",
    "driver_host": "spark-livy", "driver_memory": "512m",
    "executor_memory": "512m", "cores_max": "1",
}
PAYLOAD = {
    "kind": "pyspark", "driverMemory": "512m", "executorMemory": "512m",
    "executorCores": 1, "numExecutors": 1,
    "conf": {"spark.cores.max": "1", "spark.dynamicAllocation.enabled": "false",
             "spark.default.parallelism": "2", "spark.sql.shuffle.partitions": "2",
             "spark.driver.maxResultSize": "64m", "spark.ui.enabled": "false"},
}
CODE = "\n".join([
    "import json, socket",
    "conf = sc.getConf()",
    "rows = sc.parallelize(range(1000), 2).mapPartitions("
    "lambda values: [(socket.gethostname(), sum(values))]).collect()",
    "print(" + repr(MARKER) + " + json.dumps({"
    "'sum': sum(row[1] for row in rows), "
    "'partitions': len(rows), "
    "'worker_hosts': sorted(set(row[0] for row in rows)), "
    "'application_id': sc.applicationId, 'master': sc.master, "
    "'spark_version': sc.version, "
    "'driver_host': conf.get('spark.driver.host', 'unset'), "
    "'driver_memory': conf.get('spark.driver.memory', 'unset').lower(), "
    "'executor_memory': conf.get('spark.executor.memory', 'unset').lower(), "
    "'cores_max': conf.get('spark.cores.max', 'unset')}))",
])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def error_type(error):
    name = type(error).__name__
    return name if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,100}", name) else "Exception"


def snapshot(path, bound, *, participant_owned=False):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            and 0 < before.st_size <= bound, "Invalid bounded input file.")
    if participant_owned:
        require(before.st_uid == os.getuid(), "Input is not participant-owned.")
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        require(identity(os.fstat(fd)) == identity(before), "Input changed.")
        digest, size = hashlib.sha256(), 0
        while True:
            data = os.read(fd, min(65536, bound + 1 - size))
            if not data:
                break
            size += len(data)
            require(size <= bound, "Input exceeded bound.")
            digest.update(data)
        require(size == before.st_size
                and identity(os.fstat(fd)) == identity(before)
                and identity(path.lstat()) == identity(before),
                "Input changed while reading.")
        return identity(before), digest.hexdigest()
    finally:
        os.close(fd)


def load_modules():
    import types
    script = Path(__file__).resolve()
    base = script.parent
    if not all((base / name).is_file() for name in ASSET_SHA256):
        require(len(script.parents) > 4, "Reviewed participant assets are missing.")
        base = script.parents[4] / "workshop_assets/big-data/spark/beginner"
    modules = []
    for name, filename in [
        ("_participant_probe_exercise", "02_spark_via_livy.py"),
        ("_participant_probe_access", "spark_livy_access.py"),
    ]:
        path = base / filename
        before = snapshot(path, 1048576)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            chunks, size = [], 0
            while True:
                chunk = os.read(fd, min(65536, 1048577 - size))
                if not chunk:
                    break
                size += len(chunk)
                require(size <= 1048576, "Asset exceeded its bound.")
                chunks.append(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(fd)
        require(hashlib.sha256(raw).hexdigest() == ASSET_SHA256[filename]
                and snapshot(path, 1048576) == before,
                "Participant asset differs from the reviewed source.")
        module = types.ModuleType(name)
        module.__file__ = str(path)
        exec(compile(raw, str(path), "exec"), module.__dict__)
        modules.append(module)
    return tuple(modules)


@contextmanager
def managed_connection(access, expected_host, expected_port):
    require(not any(name in os.environ for name in ("LIVY_URL", "LIVY_DATA_PATH")),
            "Explicit endpoint overrides are forbidden for participant verification.")
    home = Path.home()
    credentials = home / ".ssh" / "spark-direct"
    for directory in (home / ".ssh", credentials):
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and not (stat.S_IMODE(info.st_mode) & 0o022),
                "Unprotected managed credential directory.")
    paths = [credentials / "login_key", credentials / "known_hosts"]
    before = []
    for index, path in enumerate(paths):
        access._credential_file(path, private=index == 0)
        before.append(snapshot(path, 65536, participant_owned=True))
    import paramiko
    pins = paramiko.HostKeys()
    pins.load(str(paths[1]))
    require(access.pinned_endpoint(pins) == (expected_host, expected_port),
            "Managed pin does not match the organiser-selected endpoint.")
    def refuse_explicit():
        raise ValueError("Explicit connection settings are forbidden.")
    with access.managed_connection(refuse_explicit) as settings:
        require([snapshot(path, 65536, participant_owned=True) for path in paths]
                == before, "Managed credential identities changed.")
        require(settings.get("VERIFY_DATASET") is True
                and settings.get("LIVY_DATA_PATH") == access.DATA_CANDIDATE,
                "Connection is not the managed participant path.")
        parsed = urlsplit(settings.get("LIVY_URL", ""))
        require(parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.port is not None and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path in ("", "/"), "Expected loopback-only forwarding.")
        yield settings


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.fd = self.directory_fd = None
        self.evidence_id = uuid.uuid4().hex

    def __enter__(self):
        before = self.directory.lstat()
        require(stat.S_ISDIR(before.st_mode) and before.st_uid == os.getuid()
                and stat.S_IMODE(before.st_mode) == 0o700,
                "An existing participant-owned mode-0700 evidence directory is required.")
        self.directory_fd = os.open(
            self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            current = os.fstat(self.directory_fd)
            require((current.st_dev, current.st_ino) == (before.st_dev, before.st_ino),
                    "Evidence directory changed.")
            self.fd = os.open(self.evidence_id + ".jsonl",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=self.directory_fd)
            os.fchmod(self.fd, 0o600)
            os.fsync(self.directory_fd)
            return self
        except BaseException:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            os.close(self.directory_fd)
            self.directory_fd = None
            raise

    def record(self, event, payload):
        current, opened = self.directory.lstat(), os.fstat(self.directory_fd)
        require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino),
                "Evidence directory identity changed.")
        data = dict(payload, event=event, recorded_at_unix=time.time())
        view = memoryview((json.dumps(data, sort_keys=True) + "\n").encode())
        while view:
            count = os.write(self.fd, view)
            require(count > 0, "Evidence write stalled.")
            view = view[count:]
        os.fsync(self.fd)

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
        if self.directory_fd is not None:
            os.close(self.directory_fd)


def empty_inventory(request, base):
    for kind in ("sessions", "batches"):
        value = request(base, "GET", f"/{kind}?from=0&size=1")
        require(isinstance(value, dict) and type(value.get("total")) is int
                and value["total"] == 0 and value.get("sessions") == [],
                "Fresh empty session and batch inventories required.")


def validate_observed(text):
    payloads = [line[len(MARKER):] for line in text.splitlines()
                if line.startswith(MARKER)]
    require(len(payloads) == 1, "Expected one computation payload.")
    result = json.loads(payloads[0])
    require(isinstance(result, dict)
            and set(result) == set(EXPECTED) | {"application_id"},
            "Unexpected computation fields.")
    require(all(result[key] == value for key, value in EXPECTED.items()),
            "Worker, computation or resource settings differ.")
    require(type(result["sum"]) is int and type(result["partitions"]) is int,
            "Invalid computation result types.")
    application = result["application_id"]
    require(isinstance(application, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", application),
            "Invalid application identity.")
    return result


def verify(*, workspace, exercise, access, connection, emit,
           maintenance_confirmed, submissions_paused, clock=time.monotonic):
    require(maintenance_confirmed is True and submissions_paused is True,
            "Explicit maintenance and submission-pause acknowledgements required.")
    require(not any(name in os.environ for name in ("LIVY_URL", "LIVY_DATA_PATH")),
            "Explicit endpoint overrides are forbidden.")
    report = {"status": "FAILED", "session_request_sent": False, "session_id": None,
              "cleanup": "not-required", "forwarding_closed": False,
              "scope": "one managed participant identity; not cohort or full-activity readiness"}
    started, original_request = clock(), exercise.livy_request
    deadline, phase, failure = started + 240, "input-validation", None
    cleanup_failure = None
    def request(*args, **kwargs):
        if clock() >= deadline:
            raise TimeoutError("Participant probe request budget exhausted.")
        return original_request(*args, **kwargs)
    exercise.livy_request = request
    try:
        dataset = Path(workspace) / "data" / "Bank_Personal_Loan_Modelling.csv"
        before = snapshot(dataset, 64 * 1024 * 1024)
        emit("verification-requested", {"scope": report["scope"]})
        phase = "managed-forwarding"
        with connection() as settings:
            base = settings["LIVY_URL"]
            try:
                phase = "fresh-inventory"
                empty_inventory(request, base)
                phase = "session-creation"
                payload = json.loads(json.dumps(PAYLOAD))
                payload["name"] = "participant-verification-" + uuid.uuid4().hex
                emit("session-create-requested", {"creation_outcome": "unknown-until-owned-id"})
                report["session_request_sent"] = True
                created = request(base, "POST", "/sessions", payload)
                report["session_id"] = exercise.response_id(created)
                emit("owned-session-created", {"session_id": report["session_id"]})
                phase = "session-readiness"
                exercise.wait_for_session(base, report["session_id"])
                phase = "dataset-verification"
                verified = access.verify_dataset(
                    exercise.run_statement, base, report["session_id"],
                    settings["LIVY_DATA_PATH"], dataset)
                require(verified == access.DATA_CANDIDATE
                        and snapshot(dataset, 64 * 1024 * 1024) == before,
                        "Dataset path or local input identity changed.")
                phase = "worker-computation"
                report["observed"] = validate_observed(exercise.run_statement(
                    base, report["session_id"], CODE))
                report["dataset_sha256"] = before[1]
            except BaseException as error:
                failure = error
                report["failure_phase"] = phase
            finally:
                if report["session_id"] is not None:
                    deadline = clock() + 60
                    try:
                        access.delete_owned_session(request, base, report["session_id"], timeout=60)
                        report["cleanup"] = "owned-session-http-404-confirmed"
                        emit("owned-session-cleanup-confirmed",
                             {"session_id": report["session_id"]})
                    except BaseException as error:
                        cleanup_failure = error
                        report["cleanup"] = "unconfirmed-inspect-owned-id-before-retry"
                        if failure is None:
                            failure = error
                            report["failure_phase"] = "owned-session-cleanup"
                elif report["session_request_sent"]:
                    report["cleanup"] = "creation-outcome-unknown-no-id-do-not-retry"
            if failure is None:
                phase = "post-cleanup-inventory"
                empty_inventory(request, base)
                report["post_cleanup_inventory"] = "empty-sessions-and-batches"
            phase = "close-managed-forwarding"
        report["forwarding_closed"] = True
        if failure is None:
            require(clock() - started <= 330, "Probe exceeded its bounded duration.")
            report["status"] = "PASSED"
    except BaseException as error:
        if failure is None:
            failure = error
            report["failure_phase"] = phase
    finally:
        exercise.livy_request = original_request
    if failure is not None:
        report["error_type"] = error_type(failure)
    if cleanup_failure is not None:
        report["cleanup_error_type"] = error_type(cleanup_failure)
    report["elapsed_seconds"] = round(clock() - started, 3)
    try:
        emit("verification-finished", report)
    except BaseException as error:
        report["status"] = "FAILED"
        report["evidence_error_type"] = error_type(error)
        if failure is None:
            report["error_type"] = error_type(error)
            report["failure_phase"] = "final-evidence-recording"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--expected-ssh-host", required=True)
    parser.add_argument("--expected-ssh-port", required=True, type=int)
    parser.add_argument("--maintenance-window-confirmed", required=True, action="store_true")
    parser.add_argument("--submissions-paused-confirmed", required=True, action="store_true")
    args = parser.parse_args(argv)
    previous = None
    try:
        require(args.expected_ssh_host and not any(
            ord(c) <= 32 or ord(c) == 127 for c in args.expected_ssh_host)
            and 1 <= args.expected_ssh_port <= 65535, "Invalid expected endpoint.")
        require(not any(n in os.environ for n in ("LIVY_URL", "LIVY_DATA_PATH")),
                "Explicit endpoint overrides are forbidden.")
        exercise, access = load_modules()
        def interrupted(signum, frame):
            raise InterruptedError("Participant verification interrupted.")
        previous = signal.signal(signal.SIGTERM, interrupted)
        with Journal(args.evidence_dir) as journal:
            with open(os.devnull, "w") as quiet:
                with redirect_stdout(quiet), redirect_stderr(quiet):
                    report = verify(
                        workspace=args.workspace, exercise=exercise, access=access,
                        connection=lambda: managed_connection(
                            access, args.expected_ssh_host, args.expected_ssh_port),
                        emit=journal.record,
                        maintenance_confirmed=args.maintenance_window_confirmed,
                        submissions_paused=args.submissions_paused_confirmed)
            report["evidence_id"] = journal.evidence_id
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "PASSED" else 1
    except BaseException as error:
        print(json.dumps({"status": "FAILED", "error_type": error_type(error)}),
              file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    raise SystemExit(main())
