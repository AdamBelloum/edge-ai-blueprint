"""Read protected, temporary organiser delivery inputs; no staging entry point.

A future playbook renders actual files and a separate reference manifest from
reviewed repository templates. This reader verifies transfer consistency, not
template authority. Archive verification is performed by the staging gate.
"""
from contextlib import ExitStack
import json
import os
import stat

from livy_candidate_assets import FILES, FLAGS
from livy_candidate_verify import ARCHIVE

MANIFEST = "reviewed-assets.json"
TEXT_LIMIT = 1048576
ARCHIVE_LIMIT = 512 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def protected_directory(info, owner_uid):
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == owner_uid
            and stat.S_IMODE(info.st_mode) == 0o700,
            "Delivery directory must be organiser-owned with mode 0700.")


def read_delivery_file(bundle_fd, relative, *, owner_uid, limit):
    # Only fixed reviewed names are accepted; no arbitrary path traversal.
    require(relative in FILES or relative == MANIFEST,
            "Unknown delivery input path.")
    root_info = os.fstat(bundle_fd)
    protected_directory(root_info, owner_uid)
    with ExitStack() as stack:
        parent = bundle_fd
        parts = relative.split("/")
        for component in parts[:-1]:
            before = os.stat(component, dir_fd=parent, follow_symlinks=False)
            protected_directory(before, owner_uid)
            require(before.st_dev == root_info.st_dev, "Cross-device delivery refused.")
            child = os.open(component, FLAGS, dir_fd=parent)
            stack.callback(os.close, child)
            require(fingerprint(os.fstat(child)) == fingerprint(before),
                    "Delivery directory identity changed.")
            parent = child
        name = parts[-1]
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == owner_uid
                and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_nlink == 1 and before.st_dev == root_info.st_dev
                and 0 < before.st_size <= limit,
                "Delivery file must be bounded, protected and unlinked.")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                     | os.O_NONBLOCK, dir_fd=parent)
        stack.callback(os.close, fd)
        require(fingerprint(os.fstat(fd)) == fingerprint(before),
                "Delivery file identity changed before reading.")
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(1048576, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= limit, "Delivery file exceeded its size bound.")
        require(size == before.st_size
                and fingerprint(os.fstat(fd)) == fingerprint(before)
                and fingerprint(os.stat(name, dir_fd=parent,
                                        follow_symlinks=False)) == fingerprint(before),
                "Delivery file changed during reading.")
        return b"".join(chunks)


def read_delivery(bundle_fd, *, owner_uid=0):
    raw = read_delivery_file(
        bundle_fd, MANIFEST, owner_uid=owner_uid, limit=TEXT_LIMIT)
    reviewed = json.loads(raw.decode("utf-8"))
    require(isinstance(reviewed, dict)
            and set(reviewed) == set(FILES) - {ARCHIVE}
            and all(isinstance(value, str) and value for value in reviewed.values()),
            "Exactly five nonempty independently rendered reference texts are required.")
    reviewed = {name: value.encode("utf-8") for name, value in reviewed.items()}
    files = {}
    # Reject text transfer mismatches before reading the large archive.
    for name, expected in reviewed.items():
        files[name] = read_delivery_file(
            bundle_fd, name, owner_uid=owner_uid, limit=TEXT_LIMIT)
        require(files[name] == expected,
                "Transferred asset differs from reviewed rendering: " + name)
    files[ARCHIVE] = read_delivery_file(
        bundle_fd, ARCHIVE, owner_uid=owner_uid, limit=ARCHIVE_LIMIT)
    return files, reviewed
