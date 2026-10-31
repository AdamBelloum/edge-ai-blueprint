#!/usr/bin/env python3
"""Remove matching installed HPC files only; preserve directories and other files.

The caller supplies a trusted manifest generated from repository installation
allowlists. Requires exclusive administrator maintenance: no concurrent staging,
publication, reconciliation, spawning, or filesystem administration.
The CLI supports only the two standard staging roots; overrides are not accepted.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

ROOTS = {
    "workspace": "/opt/digitafrica/hpc",
    "runtime": "/opt/digitafrica/hpc-runtime",
}


class CleanupError(RuntimeError):
    pass


def validate_entries(entries):
    if not isinstance(entries, list) or not entries:
        raise CleanupError("Missing installation file allowlist")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "mode"}:
            raise CleanupError("Invalid manifest entry")
        name = entry["path"]
        if not isinstance(name, str) or not name or "\x00" in name:
            raise CleanupError("Invalid relative installation path")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or str(relative) != name:
            raise CleanupError("Unsafe or noncanonical relative installation path")
        if name == "." or name in seen:
            raise CleanupError("Duplicate or empty installation path")
        if not isinstance(entry["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
            raise CleanupError("Invalid expected SHA-256")
        if type(entry["mode"]) is not int or entry["mode"] not in (0o644, 0o755):
            raise CleanupError("Invalid expected installation mode")
        seen.add(name)
    # A manifest cannot describe a file and also treat it as a parent directory.
    for name in seen:
        if any(str(parent) in seen for parent in PurePosixPath(name).parents):
            raise CleanupError("Conflicting manifest file paths")


def open_parent(root, relative, uid, gid):
    """Open parent via no-follow directory descriptors; return None if absent."""
    root = Path(root)
    if not root.is_absolute() or ".." in root.parts or root == Path("/"):
        raise CleanupError("Unsafe staging root")
    components = root.parts[1:] + PurePosixPath(relative).parts[:-1]
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, component in enumerate(components):
            try:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                os.close(fd)
                return None
            except OSError as error:
                raise CleanupError("Unsafe/non-directory staging ancestor") from error
            os.close(fd)
            fd = child
            # Standard installation directories are root-owned and mode 0755.
            # Test callers explicitly supply their own uid/gid for temporary roots.
            if index >= len(root.parts) - 2:
                metadata = os.fstat(fd)
                if (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) != (uid, gid, 0o755):
                    raise CleanupError("Staging directory ownership/mode conflict")
        return fd
    except BaseException:
        os.close(fd)
        raise


def verify_file(parent, entry, uid, gid):
    name = PurePosixPath(entry["path"]).name
    try:
        metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise CleanupError("Non-regular, symlink or hard-linked target: " + entry["path"])
    if (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) != (uid, gid, entry["mode"]):
        raise CleanupError("Installation ownership/mode conflict: " + entry["path"])
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise CleanupError("Target changed during inspection")
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != entry["sha256"]:
        raise CleanupError("Modified or unrecognised installation file: " + entry["path"])
    return True


def preflight(root, entries, uid=0, gid=0):
    validate_entries(entries)
    present = []
    for entry in entries:
        parent = open_parent(root, entry["path"], uid, gid)
        if parent is None:
            continue
        try:
            if verify_file(parent, entry, uid, gid):
                present.append(entry)
        finally:
            os.close(parent)
    return present


def execute(root, entries, uid=0, gid=0):
    # Validate every target before the first unlink, including on retries.
    present = preflight(root, entries, uid, gid)
    removed = 0
    for entry in present:
        parent = open_parent(root, entry["path"], uid, gid)
        if parent is None:
            continue
        try:
            # Recheck each file immediately before deleting through its parent fd.
            if verify_file(parent, entry, uid, gid):
                os.unlink(PurePosixPath(entry["path"]).name, dir_fd=parent)
                removed += 1
        finally:
            os.close(parent)
    if preflight(root, entries, uid, gid):
        raise CleanupError("Installation files remain or were recreated")
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, choices=tuple(ROOTS))
    parser.add_argument("--manifest-base64", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        document = json.loads(base64.b64decode(args.manifest_base64, validate=True))
        if not isinstance(document, dict) or set(document) != {"scope", "files"} or document["scope"] != args.scope:
            raise CleanupError("Manifest scope mismatch")
        root = ROOTS[args.scope]
        if args.check:
            count = len(preflight(root, document["files"]))
            print(f"HPC {args.scope} preflight passed: {count} matching installed files; no deletion.")
        else:
            count = execute(root, document["files"])
            print(f"HPC {args.scope}: removed {count} matching installed files; allowlisted files absent.")
            print("Directories and unrelated content preserved; participant homes not targeted.")
    except (CleanupError, OSError, ValueError, TypeError) as error:
        parser.exit(1, f"ERROR: HPC staging cleanup refused/failed: {error}\n")


if __name__ == "__main__":
    main()
