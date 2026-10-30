#!/usr/bin/env python3
"""Validate exports against public active-client evidence.

--produce outputs PRIVATE credential JSON: invoke only in a no_log task.
Input evidence must come from organiser-controlled Docker inspection, including
keys read from /etc/ssh/workshop_host_key and /etc/ssh/workshop_authorized_keys.
The caller derives group/node assignment from the ordered workshop inventory.
"""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import sys
import tempfile

IMAGE = "digitafrica/spark-client:3.5.3-ssh-v1"

class Blocked(Exception):
    pass

def require(value, reason):
    if not value:
        raise Blocked(reason)

def public(value):
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    require(len(lines) == 1, "expected_one_public_key")
    fields = lines[0].split()
    require(len(fields) >= 2 and fields[0] == "ssh-ed25519", "expected_ed25519_key")
    base64.b64decode(fields[1], validate=True)
    return tuple(fields[:2])

def bind(contents, login_public, evidence, worker, group, node, image=IMAGE):
    require(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", worker), "unsafe_worker_alias")
    require(re.fullmatch(r"group_[0-9]{2,}", group), "invalid_group_id")
    require(evidence["worker_node"] == node, "worker_node_mismatch")
    require(evidence["running_client_count"] == 1, "expected_one_running_client")
    require(evidence["managed_by"] == "organiser", "unmanaged_client")
    require(evidence["image"] == image, "unexpected_client_image")
    require(evidence["mounts_verified"] is True, "unverified_active_key_mounts")
    records = [s.strip() for s in contents["known_hosts"].decode().splitlines()
               if s.strip() and not s.lstrip().startswith("#")]
    require(len(records) == 1, "expected_one_pinned_host")
    fields = records[0].split()
    require(len(fields) >= 3, "invalid_pinned_host")
    require(fields[0] == "[" + evidence["host"] + "]:" + str(int(evidence["port"])),
            "export_endpoint_mismatch")
    require(public(" ".join(fields[1:3])) == public(evidence["host_public"]),
            "export_host_identity_mismatch")
    require(public(login_public) == public(evidence["authorized_public"]),
            "export_login_identity_mismatch")
    return {
        "operation": "apply", "worker": worker, "group_id": group, "worker_node": node,
        "credentials": {name: {
            "content_b64": base64.b64encode(contents[name]).decode(),
            "sha256": hashlib.sha256(contents[name]).hexdigest(),
        } for name in ("login_key", "known_hosts")},
    }

def read_checked(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not stat.S_IMODE(info.st_mode) & 0o077,
                "unsafe_export_file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            data = stream.read(16385)
        require(0 < len(data) <= 16384, "invalid_export_size")
        return data
    finally:
        os.close(fd)

def produce(args):
    root = Path(__file__).resolve().parents[4]
    os.chdir(root)
    verifier = runpy.run_path(str(Path(__file__).with_name("verify_worker_ssh_auth.py")))
    export = verifier["load"](root, args.worker)
    contents = {name: read_checked(export["key" if name == "login_key" else "known"])
                for name in ("login_key", "known_hosts")}
    # Validate the exact captured private-key bytes using a protected temporary
    # copy under this worker's already-validated, ignored export directory.
    with tempfile.TemporaryDirectory(prefix=".identity-check-", dir=export["key"].parent) as temp:
        copied = Path(temp) / "key"
        fd = os.open(copied, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents["login_key"])
        result = subprocess.run(["ssh-keygen", "-y", "-P", "", "-f", str(copied)],
                                stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=15, check=False)
        require(result.returncode == 0, "captured_login_key_invalid")
        login_public = result.stdout
    raw = sys.stdin.read(65537)
    require(len(raw) <= 65536, "evidence_too_large")
    return bind(contents, login_public, json.loads(raw), args.worker, args.group,
                args.node, args.expected_image)

def self_test():
    import unittest
    class Tests(unittest.TestCase):
        def setUp(self):
            self.contents = {"login_key": b"fixture-key", "known_hosts":
                b"[145.100.135.172]:2222 ssh-ed25519 aG9zdA==\n"}
            self.login = "ssh-ed25519 bG9naW4="
            self.evidence = dict(worker_node="worker.example", running_client_count=1,
                managed_by="organiser", image=IMAGE, mounts_verified=True,
                host="145.100.135.172", port=2222,
                host_public="ssh-ed25519 aG9zdA==", authorized_public=self.login)
        def go(self, evidence=None):
            return bind(self.contents, self.login, evidence or self.evidence,
                        "worker-a", "group_01", "worker.example")
        def test_valid_binding(self):
            result = self.go()
            self.assertEqual(result["group_id"], "group_01")
            self.assertEqual(result["worker_node"], "worker.example")
        def test_exact_content_and_checksums(self):
            result = self.go()
            for name, value in self.contents.items():
                entry = result["credentials"][name]
                self.assertEqual(base64.b64decode(entry["content_b64"]), value)
                self.assertEqual(entry["sha256"], hashlib.sha256(value).hexdigest())
        def test_rejects_mismatched_active_evidence(self):
            for field, value in (
                ("worker_node", "other.example"), ("running_client_count", 2),
                ("managed_by", "other"), ("image", "other-image"),
                ("mounts_verified", False), ("host", "145.100.135.241"),
                ("port", 2223), ("host_public", "ssh-ed25519 b3RoZXI="),
                ("authorized_public", "ssh-ed25519 b3RoZXI="),
                ("authorized_public", self.login + "\n" + self.login),
            ):
                with self.subTest(field=field):
                    evidence = deepcopy(self.evidence)
                    evidence[field] = value
                    with self.assertRaises(Blocked): self.go(evidence)
        def test_rejects_multiple_pins(self):
            self.contents["known_hosts"] *= 2
            with self.assertRaises(Blocked): self.go()
        def test_rejects_unsafe_alias(self):
            with self.assertRaises(Blocked):
                bind(self.contents, self.login, self.evidence,
                     "../worker", "group_01", "worker.example")
        def test_rejects_invalid_group(self):
            with self.assertRaises(Blocked):
                bind(self.contents, self.login, self.evidence,
                     "worker-a", "invalid", "worker.example")
    return unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Tests)).wasSuccessful()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--produce", action="store_true")
    parser.add_argument("--worker")
    parser.add_argument("--group")
    parser.add_argument("--node")
    parser.add_argument("--expected-image", default=IMAGE)
    args = parser.parse_args()
    if args.self_test:
        return 0 if self_test() else 1
    require(all((args.worker, args.group, args.node)), "missing_binding_arguments")
    require(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", args.worker), "unsafe_worker_alias")
    print(json.dumps(produce(args)))
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Blocked, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        reason = str(exc) if isinstance(exc, Blocked) else "source_validation_error_" + type(exc).__name__
        print(json.dumps({"status": "blocked", "reason": reason}))
        sys.exit(2)
