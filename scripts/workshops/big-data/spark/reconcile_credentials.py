#!/usr/bin/env python3
"""Reconcile independently validated credentials; never log stdin.

The controller must validate worker/group assignment and active identities.
Checksums detect transport changes, not source authenticity. Defaults to plan.
"""
import base64
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid

NAMES = ("login_key", "known_hosts")
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK

class Blocked(Exception):
    pass

def require(condition, reason):
    if not condition:
        raise Blocked(reason)

MARKER = ".organiser-managed.json"

def read_marker(cred_fd, uid):
    """Return digests recorded by the last organiser write; {} if absent or unsafe."""
    try:
        fd = os.open(MARKER, FILE_FLAGS, dir_fd=cred_fd)
    except OSError:
        return {}
    try:
        info = os.fstat(fd)
        if not (stat.S_ISREG(info.st_mode) and info.st_uid == uid
                and info.st_nlink == 1 and info.st_size <= 4096):
            return {}
        with os.fdopen(os.dup(fd), "rb") as stream:
            data = json.loads(stream.read(4097))
        if not isinstance(data, dict) or data.get("version") != 1:
            return {}
        digests = data.get("sha256")
        if not isinstance(digests, dict):
            return {}
        return {n: digests[n] for n in NAMES if isinstance(digests.get(n), str)}
    except ValueError:
        return {}
    finally:
        os.close(fd)

def write_atomic(cred_fd, name, payload):
    """Write a complete file in the credential directory and rename it into place."""
    staging = ".spark-credential-" + uuid.uuid4().hex
    fd = os.open(
        staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600, dir_fd=cred_fd,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(staging, name, src_dir_fd=cred_fd, dst_dir_fd=cred_fd)
    except BaseException:
        try:
            os.unlink(staging, dir_fd=cred_fd)
        except FileNotFoundError:
            pass
        raise

def reconcile(home, uid, contents, apply=False):
    require(uid == os.getuid(), "unexpected_process_uid")
    require(set(contents) == set(NAMES), "incomplete_source_credentials")
    require(all(isinstance(b, bytes) and 0 < len(b) <= 16384
                for b in contents.values()), "invalid_source_content")
    with ExitStack() as stack:
        def track(fd):
            stack.callback(os.close, fd)
            return fd

        def directory(parent, name):
            try:
                fd = track(os.open(name, DIR_FLAGS, dir_fd=parent))
            except FileNotFoundError:
                return None
            require(os.fstat(fd).st_uid == uid, "unexpected_directory_owner")
            return fd

        home_fd = track(os.open(str(home), DIR_FLAGS))
        require(os.fstat(home_fd).st_uid == uid, "unexpected_home_owner")
        # Serialises cooperating reconcilers, not arbitrary participant processes.
        fcntl.flock(home_fd, fcntl.LOCK_EX if apply else fcntl.LOCK_SH)
        ssh_fd = directory(home_fd, ".ssh")
        cred_fd = directory(ssh_fd, "spark-direct") if ssh_fd is not None else None
        present = {}
        stale = {}

        # Validate BOTH existing credentials before making any changes.
        for name in NAMES:
            if cred_fd is None:
                continue
            try:
                fd = track(os.open(name, FILE_FLAGS, dir_fd=cred_fd))
            except FileNotFoundError:
                continue
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == uid
                    and info.st_nlink == 1, "unsafe_existing_credential")
            with os.fdopen(os.dup(fd), "rb") as stream:
                data = stream.read(16385)
            if data != contents[name]:
                stale[name] = hashlib.sha256(data).hexdigest()
            present[name] = (fd, info)

        if stale:
            recorded = read_marker(cred_fd, uid)
            require(all(recorded.get(n) == d for n, d in stale.items()),
                    "conflicting_existing_credential")

        created, repaired = [], []
        for name, fd in ((".ssh", ssh_fd), ("spark-direct", cred_fd)):
            if fd is None:
                created.append(name)
            elif stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
                repaired.append(name)
        for name in NAMES:
            if name not in present:
                created.append(name)
            elif stat.S_IMODE(present[name][1].st_mode) != 0o600:
                repaired.append(name)
        report = {"status": "planned", "create": created, "repair_modes": repaired}
        if stale:
            report["replace"] = sorted(stale)
        if not apply:
            return report

        if ssh_fd is None:
            os.mkdir(".ssh", 0o700, dir_fd=home_fd)
            ssh_fd = directory(home_fd, ".ssh")
        if cred_fd is None:
            os.mkdir("spark-direct", 0o700, dir_fd=ssh_fd)
            cred_fd = directory(ssh_fd, "spark-direct")

        for parent, name, fd in (
            (home_fd, ".ssh", ssh_fd), (ssh_fd, "spark-direct", cred_fd),
        ):
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            opened = os.fstat(fd)
            require(
                stat.S_ISDIR(current.st_mode)
                and (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino),
                "directory_changed_during_reconciliation",
            )
        os.fchmod(ssh_fd, 0o700)
        os.fchmod(cred_fd, 0o700)

        for name in NAMES:
            if name in present:
                fd, original = present[name]
                current = os.stat(name, dir_fd=cred_fd, follow_symlinks=False)
                require(
                    stat.S_ISREG(current.st_mode) and os.fstat(fd).st_nlink == 1
                    and (current.st_dev, current.st_ino) ==
                    (original.st_dev, original.st_ino),
                    "credential_changed_during_reconciliation",
                )
                if name in stale:
                    write_atomic(cred_fd, name, contents[name])
                else:
                    os.fchmod(fd, 0o600)
                continue

            staging = ".spark-credential-" + uuid.uuid4().hex
            fd = os.open(
                staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=cred_fd,
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(contents[name])
                    stream.flush()
                    os.fsync(stream.fileno())
                # Publish each complete file atomically; never replace a file.
                os.link(staging, name, src_dir_fd=cred_fd, dst_dir_fd=cred_fd,
                        follow_symlinks=False)
            finally:
                os.unlink(staging, dir_fd=cred_fd)

        desired = {n: hashlib.sha256(contents[n]).hexdigest() for n in NAMES}
        if read_marker(cred_fd, uid) != desired:
            write_atomic(cred_fd, MARKER, json.dumps(
                {"version": 1, "sha256": desired}, sort_keys=True).encode())
        os.fsync(cred_fd)
        report["status"] = "reconciled"
        return report

def self_test():
    import tempfile
    import unittest

    class Tests(unittest.TestCase):
        def setUp(self):
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            self.home = Path(tmp.name) / "home"
            self.home.mkdir()
            self.uid = os.getuid()
            self.source = {
                "login_key": b"fixture-key\n", "known_hosts": b"fixture-pin\n",
            }

        def go(self, apply=True):
            return reconcile(self.home, self.uid, self.source, apply)

        def prepare(self):
            self.go()
            return self.home / ".ssh/spark-direct"

        def test_dry_run(self):
            self.assertEqual(self.go(False)["status"], "planned")
            self.assertFalse((self.home / ".ssh").exists())

        def test_create_and_repeat(self):
            d = self.prepare()
            inodes = {n: (d / n).stat().st_ino for n in NAMES}
            self.assertEqual(self.go()["create"], [])
            for n in NAMES:
                self.assertEqual((d / n).read_bytes(), self.source[n])
                self.assertEqual((d / n).stat().st_ino, inodes[n])
                self.assertEqual(stat.S_IMODE((d / n).stat().st_mode), 0o600)

        def test_mode_repair(self):
            d = self.prepare()
            for p in (d.parent, d):
                p.chmod(0o2770)
            for n in NAMES:
                (d / n).chmod(0o660)
            self.go()
            for p in (d.parent, d):
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o700)
            for n in NAMES:
                self.assertEqual(stat.S_IMODE((d / n).stat().st_mode), 0o600)

        def test_conflict_blocks_mode_changes(self):
            d = self.prepare()
            d.chmod(0o2770)
            (d / "known_hosts").write_bytes(b"conflict")
            with self.assertRaises(Blocked):
                self.go()
            self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o2770)
            self.assertEqual((d / "known_hosts").read_bytes(), b"conflict")

        def test_conflict_blocks_missing_partner(self):
            d = self.prepare()
            (d / "login_key").unlink()
            (d / "known_hosts").write_bytes(b"conflict")
            with self.assertRaises(Blocked):
                self.go()
            self.assertFalse((d / "login_key").exists())

        def test_missing_matching_partner(self):
            d = self.prepare()
            (d / "known_hosts").unlink()
            self.go()
            self.assertEqual((d / "known_hosts").read_bytes(),
                             self.source["known_hosts"])

        def test_file_symlink(self):
            d = self.prepare()
            external = self.home / "external"
            external.write_bytes(self.source["login_key"])
            (d / "login_key").unlink()
            (d / "login_key").symlink_to(external)
            with self.assertRaises(OSError):
                self.go()

        def test_directory_symlink(self):
            external = self.home / "external"
            external.mkdir()
            (self.home / ".ssh").symlink_to(external)
            with self.assertRaises(OSError):
                self.go()

        def test_hardlink(self):
            d = self.prepare()
            os.link(d / "login_key", self.home / "linked")
            with self.assertRaises(Blocked):
                self.go()

        def test_wrong_uid(self):
            with self.assertRaises(Blocked):
                reconcile(self.home, self.uid + 1, self.source, True)

        def test_incomplete_source(self):
            with self.assertRaises(Blocked):
                reconcile(self.home, self.uid, {"login_key": b"x"}, True)
            self.assertFalse((self.home / ".ssh").exists())

        def test_unrelated_files(self):
            d = self.prepare()
            other = d.parent / "unrelated-key"
            other.write_bytes(b"preserve")
            other.chmod(0o640)
            self.go()
            self.assertEqual(other.read_bytes(), b"preserve")
            self.assertEqual(stat.S_IMODE(other.stat().st_mode), 0o640)

        def rotated(self):
            self.source = {
                "login_key": b"rotated-key\n", "known_hosts": b"rotated-pin\n",
            }

        def digests(self, source):
            return {n: hashlib.sha256(source[n]).hexdigest() for n in NAMES}

        def test_rotation_replaces_unmodified_organiser_files(self):
            d = self.prepare()
            self.assertEqual(json.loads((d / MARKER).read_text()),
                             {"version": 1, "sha256": self.digests(self.source)})
            old = dict(self.source)
            self.rotated()
            plan = self.go(False)
            self.assertEqual(plan["status"], "planned")
            self.assertEqual(plan["replace"], ["known_hosts", "login_key"])
            for n in NAMES:
                self.assertEqual((d / n).read_bytes(), old[n])
            self.assertEqual(self.go()["status"], "reconciled")
            inodes = {}
            for n in NAMES:
                self.assertEqual((d / n).read_bytes(), self.source[n])
                self.assertEqual(stat.S_IMODE((d / n).stat().st_mode), 0o600)
                inodes[n] = (d / n).stat().st_ino
            self.assertEqual(json.loads((d / MARKER).read_text())["sha256"],
                             self.digests(self.source))
            again = self.go()
            self.assertEqual(again["create"], [])
            self.assertNotIn("replace", again)
            for n in NAMES:
                self.assertEqual((d / n).stat().st_ino, inodes[n])
            self.assertEqual([p.name for p in d.iterdir()
                              if p.name.startswith(".spark-credential-")], [])

        def test_matching_files_without_marker_are_adopted(self):
            d = self.prepare()
            (d / MARKER).unlink()
            self.go()
            self.assertEqual(json.loads((d / MARKER).read_text())["sha256"],
                             self.digests(self.source))
            self.rotated()
            self.go()
            self.assertEqual((d / "login_key").read_bytes(), self.source["login_key"])

        def test_rotation_blocks_without_marker(self):
            d = self.prepare()
            old = dict(self.source)
            (d / MARKER).unlink()
            self.rotated()
            with self.assertRaisesRegex(Blocked, "conflicting_existing_credential"):
                self.go()
            for n in NAMES:
                self.assertEqual((d / n).read_bytes(), old[n])
            self.assertFalse((d / MARKER).exists())

        def test_rotation_blocks_modified_file(self):
            d = self.prepare()
            old_pin = self.source["known_hosts"]
            (d / "login_key").write_bytes(b"participant-edit")
            self.rotated()
            with self.assertRaisesRegex(Blocked, "conflicting_existing_credential"):
                self.go()
            self.assertEqual((d / "login_key").read_bytes(), b"participant-edit")
            self.assertEqual((d / "known_hosts").read_bytes(), old_pin)

        def test_rotation_blocks_marker_for_other_content(self):
            d = self.prepare()
            (d / "login_key").write_bytes(b"participant-edit")
            (d / MARKER).write_text(json.dumps({"version": 1, "sha256": self.digests(
                {"login_key": b"other", "known_hosts": b"other"})}))
            self.rotated()
            with self.assertRaisesRegex(Blocked, "conflicting_existing_credential"):
                self.go()
            self.assertEqual((d / "login_key").read_bytes(), b"participant-edit")

        def test_rotation_blocks_malformed_marker(self):
            d = self.prepare()
            old = dict(self.source)
            self.rotated()
            for payload in (b"{not json", b"[]", b"\xff\xfe",
                            b"{\"version\": 2, \"sha256\": {}}"):
                with self.subTest(payload=payload):
                    (d / MARKER).write_bytes(payload)
                    with self.assertRaisesRegex(Blocked, "conflicting_existing_credential"):
                        self.go()
                    for n in NAMES:
                        self.assertEqual((d / n).read_bytes(), old[n])

        def test_rotation_ignores_symlinked_marker(self):
            d = self.prepare()
            external = self.home / "external-marker"
            external.write_bytes((d / MARKER).read_bytes())
            (d / MARKER).unlink()
            (d / MARKER).symlink_to(external)
            self.rotated()
            with self.assertRaisesRegex(Blocked, "conflicting_existing_credential"):
                self.go()

        def test_rotation_ignores_hardlinked_marker(self):
            d = self.prepare()
            os.link(d / MARKER, self.home / "linked-marker")
            self.rotated()
            with self.assertRaisesRegex(Blocked, "conflicting_existing_credential"):
                self.go()

        def test_rotation_still_rejects_hardlinked_credential(self):
            d = self.prepare()
            os.link(d / "login_key", self.home / "linked")
            self.rotated()
            with self.assertRaisesRegex(Blocked, "unsafe_existing_credential"):
                self.go()

        def test_rotation_recovers_after_interrupted_replace(self):
            d = self.prepare()
            self.rotated()
            (d / "login_key").write_bytes(self.source["login_key"])
            self.assertEqual(self.go()["status"], "reconciled")
            for n in NAMES:
                self.assertEqual((d / n).read_bytes(), self.source[n])
            self.assertEqual(json.loads((d / MARKER).read_text())["sha256"],
                             self.digests(self.source))

        def test_forged_marker_only_yields_organiser_credentials(self):
            d = self.prepare()
            (d / "login_key").write_bytes(b"participant-edit")
            (d / MARKER).write_text(json.dumps({"version": 1, "sha256": {
                "login_key": hashlib.sha256(b"participant-edit").hexdigest(),
                "known_hosts": self.digests(self.source)["known_hosts"]}}))
            self.rotated()
            self.go()
            self.assertEqual((d / "login_key").read_bytes(), self.source["login_key"])

    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    )
    return result.wasSuccessful()

def main():
    if sys.argv[1:] == ["--self-test"]:
        return 0 if self_test() else 1
    require(not sys.argv[1:], "unsupported_arguments")
    raw = sys.stdin.read(131073)
    require(len(raw) <= 131072, "request_too_large")
    request = json.loads(raw)
    operation = request.get("operation", "plan")
    require(operation in ("plan", "apply"), "invalid_operation")
    contents = {}
    for name in NAMES:
        entry = request["credentials"][name]
        value = base64.b64decode(entry["content_b64"], validate=True)
        require(hashlib.sha256(value).hexdigest() == entry["sha256"],
                "source_checksum_mismatch")
        contents[name] = value
    print(json.dumps(reconcile(
        Path("/home/jovyan"), 1000, contents, operation == "apply",
    )))
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Blocked, OSError, ValueError, KeyError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, Blocked) else "invalid_request_or_filesystem_error"
        print(json.dumps({"status": "blocked", "reason": reason}))
        sys.exit(2)
