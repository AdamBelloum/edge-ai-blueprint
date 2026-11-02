#!/usr/bin/env python3
"""Protected warm transition; participant computation remains unverified."""
import argparse
from contextlib import contextmanager
import json
import os
import re
import stat
import sys
import uuid

from livy_candidate_assets import CandidateAssets, FILES, DIRECTORIES
from livy_candidate_compose import read_baseline
from livy_candidate_deliver import open_bundle
from livy_candidate_delivery import read_delivery
from livy_candidate_observe import open_runtime
from livy_candidate_verify import verify_asset_inputs
from livy_transition_docker import transition_with_docker
from teardown_directory import FLAGS, check_ancestor, locked_submission_runtime

EVENTS = {"planned", "stopping-direct-client", "starting-livy-services",
          "runtime-transition-verified", "failed"}
SERVICES = {"spark-master", "spark-worker-1", "spark-client",
            "spark-livy", "spark-livy-access"}
ID = re.compile(r"[0-9a-f]{64}")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,100}")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def directory_identity(fd):
    info = os.fstat(fd)
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid


def read_protected(fd, relative, mode, bound, *, owner_uid=0, private=False):
    descriptors = []
    device = os.fstat(fd).st_dev
    try:
        parts = relative.split("/")
        require(all(p and p not in {".", ".."} for p in parts),
                "Invalid relative asset.")
        parent = fd
        for component in parts[:-1]:
            parent = os.open(component, FLAGS, dir_fd=parent)
            descriptors.append(parent)
            info = os.fstat(parent)
            require(info.st_uid == owner_uid and info.st_dev == device
                    and not (stat.S_IMODE(info.st_mode) & 0o022)
                    and (not private or stat.S_IMODE(info.st_mode) == 0o700),
                    "Unprotected asset directory.")
        name = parts[-1]
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid == owner_uid and before.st_dev == device
                and stat.S_IMODE(before.st_mode) == mode
                and 0 < before.st_size <= bound, "Invalid protected asset.")
        child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                        | os.O_NONBLOCK, dir_fd=parent)
        descriptors.append(child)
        require(fingerprint(os.fstat(child)) == fingerprint(before),
                "Asset changed before reading.")
        chunks, size = [], 0
        while True:
            chunk = os.read(child, min(1048576, bound + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            require(size <= bound, "Asset exceeded its bound.")
            chunks.append(chunk)
        require(size == before.st_size
                and fingerprint(os.fstat(child)) == fingerprint(before)
                and fingerprint(os.stat(name, dir_fd=parent,
                                        follow_symlinks=False))
                    == fingerprint(before), "Asset changed during reading.")
        return b"".join(chunks), fingerprint(before)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def staged_inputs(fd, files, *, owner_uid=0):
    # Deliberately no staging mount-overlap checks: retries may have live Livy.
    assets = CandidateAssets(fd, owner_uid=owner_uid)
    before = assets.scan(files)
    require(set(before) == set(FILES) | set(DIRECTORIES),
            "Incomplete candidate assets.")
    metadata, values = {}, {}
    for name, mode in FILES.items():
        value, info = read_protected(fd, name, mode, len(files[name]),
                                     owner_uid=owner_uid)
        require(value == files[name], "Staged asset differs from delivery.")
        values[name], metadata[name] = value, info
    require(assets.scan(files) == before, "Candidate identities changed.")
    return values, (before, metadata)


def bundle_metadata(fd, *, owner_uid=0):
    result = {}
    for name in [*FILES, "reviewed-assets.json"]:
        bound = 512 * 1024 * 1024 if name.endswith("/livy.zip") else 1048576
        _, result[name] = read_protected(fd, name, 0o600, bound,
                                        owner_uid=owner_uid, private=True)
    return result


class Evidence:
    """Exclusive private records containing only reviewed non-secret fields."""
    def __init__(self, fd, evidence_id):
        self.fd, self.evidence_id, self.sequence = fd, evidence_id, 0
        self.changed = False

    def record(self, event, payload):
        require(event in EVENTS and isinstance(payload, dict),
                "Invalid evidence event.")
        data = {"event": event}
        for key in ("phase", "error_type"):
            if key in payload:
                value = payload[key]
                require(isinstance(value, str) and WORD.fullmatch(value),
                        "Invalid evidence word.")
                data[key] = value
        for key in ("container_id", "stop_client_id"):
            if payload.get(key) is not None:
                value = payload[key]
                require(isinstance(value, str) and ID.fullmatch(value),
                        "Invalid evidence ID.")
                data[key] = value
        for key in ("service_ids", "preserve_service_ids",
                    "preserved_shared_ids", "existing_start_service_ids"):
            if key in payload:
                mapping = payload[key]
                require(isinstance(mapping, dict) and set(mapping) <= SERVICES
                        and all(isinstance(v, str) and ID.fullmatch(v)
                                for v in mapping.values()),
                        "Invalid evidence service IDs.")
                data[key] = dict(mapping)
        for key in ("services", "start_services"):
            if key in payload:
                values = payload[key]
                require(isinstance(values, (list, tuple))
                        and all(isinstance(v, str) and v in SERVICES
                                for v in values), "Invalid evidence services.")
                data[key] = list(values)
        if event == "runtime-transition-verified":
            data["participant_readiness"] = "not-established-by-this-executor"
        raw = (json.dumps(data, sort_keys=True) + "\n").encode()
        name = f"{self.sequence:04d}-{event}.json"
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.fd)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(raw)
            while view:
                count = os.write(fd, view)
                require(count > 0, "Evidence write stalled.")
                view = view[count:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self.fd)
        self.sequence += 1
        self.changed |= event in {
            "stopping-direct-client", "starting-livy-services"}


@contextmanager
def open_evidence():
    require(os.geteuid() == 0, "Root required.")
    descriptors = []
    try:
        fd = os.open("/", FLAGS)
        descriptors.append(fd)
        check_ancestor(fd)
        for name in ("var", "lib"):
            fd = os.open(name, FLAGS, dir_fd=fd)
            descriptors.append(fd)
            check_ancestor(fd)
        name = "digitafrica-spark-livy-transition"
        try:
            os.mkdir(name, 0o700, dir_fd=fd)
            os.fsync(fd)
        except FileExistsError:
            pass
        fd = os.open(name, FLAGS, dir_fd=fd)
        descriptors.append(fd)
        info = os.fstat(fd)
        require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o700,
                "Unprotected evidence directory.")
        evidence_id = uuid.uuid4().hex
        os.mkdir(evidence_id, 0o700, dir_fd=fd)
        os.fsync(fd)
        fd = os.open(evidence_id, FLAGS, dir_fd=fd)
        descriptors.append(fd)
        os.fchmod(fd, 0o700)
        yield Evidence(fd, evidence_id)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def run_transition(bundle, *, maintenance_confirmed, submissions_paused,
                   bundle_context=open_bundle, delivery_reader=read_delivery,
                   runtime_context=open_runtime,
                   submission_lock=locked_submission_runtime,
                   evidence_context=open_evidence,
                   engine=transition_with_docker, owner_uid=0):
    require(maintenance_confirmed is True and submissions_paused is True,
            "Explicit maintenance and submission-pause acknowledgements required.")
    require(os.geteuid() == 0, "Root required.")
    state = {}

    @contextmanager
    def maintenance():
        # Organiser attestation, not an enforced Docker-wide writer lock.
        require(maintenance_confirmed is True and submissions_paused is True,
                "Maintenance acknowledgement lost.")
        yield

    @contextmanager
    def locked():
        with submission_lock() as lock_fd:
            require(lock_fd is not None,
                    "Existing shared submission runtime required.")
            with bundle_context(bundle) as bfd, runtime_context() as rfd:
                delivered, reviewed = delivery_reader(bfd)
                delivered, reviewed = dict(delivered), dict(reviewed)
                verify_asset_inputs(delivered, reviewed_text_files=reviewed)
                state.update(
                    files=delivered, reviewed=reviewed,
                    bundle_id=directory_identity(bfd),
                    runtime_id=directory_identity(rfd),
                    bundle_metadata=bundle_metadata(bfd, owner_uid=owner_uid))
                baseline = read_baseline(rfd, owner_uid=owner_uid)
                check, metadata = read_protected(
                    rfd, "compose.yaml", 0o640, 1048576, owner_uid=owner_uid)
                require(check == baseline, "Baseline changed before observation.")
                state.update(baseline=baseline, baseline_metadata=metadata)
                _, state["staged_metadata"] = staged_inputs(
                    rfd, delivered, owner_uid=owner_uid)
            yield lock_fd

    def read_inputs():
        with bundle_context(bundle) as bfd, runtime_context() as rfd:
            require(directory_identity(bfd) == state["bundle_id"]
                    and directory_identity(rfd) == state["runtime_id"],
                    "Protected directory identity changed.")
            delivered, reviewed = delivery_reader(bfd)
            require(delivered == state["files"] and reviewed == state["reviewed"],
                    "Trusted delivery references changed.")
            require(bundle_metadata(bfd, owner_uid=owner_uid)
                    == state["bundle_metadata"], "Delivery identities changed.")
            verify_asset_inputs(delivered, reviewed_text_files=reviewed)
            baseline = read_baseline(rfd, owner_uid=owner_uid)
            check, metadata = read_protected(
                rfd, "compose.yaml", 0o640, 1048576, owner_uid=owner_uid)
            require(baseline == check == state["baseline"]
                    and metadata == state["baseline_metadata"],
                    "Baseline content or identity changed.")
            staged, metadata = staged_inputs(rfd, delivered, owner_uid=owner_uid)
            require(metadata == state["staged_metadata"],
                    "Staged identities changed.")
            return {
                "baseline": baseline,
                "candidate": staged["compose.livy-transition.yaml"],
                "dockerfile": staged["livy-transition/livy-build/Dockerfile"],
            }

    with evidence_context() as evidence:
        result = engine(
            maintenance_window=maintenance, submission_lock=locked,
            read_inputs=read_inputs, record_event=evidence.record)
        return dict(result, changed=evidence.changed,
                    evidence_id=evidence.evidence_id)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument("--maintenance-window-confirmed",
                        action="store_true", required=True)
    parser.add_argument("--submissions-paused-confirmed",
                        action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        result = run_transition(
            args.bundle,
            maintenance_confirmed=args.maintenance_window_confirmed,
            submissions_paused=args.submissions_paused_confirmed)
    except Exception as error:
        name = type(error).__name__
        print(json.dumps({
            "status": "failed", "phase": "entry-or-runtime-transition",
            "error_type": name if WORD.fullmatch(name) else "Exception",
        }), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
