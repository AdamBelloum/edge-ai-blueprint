"""Protected baseline read and read-only Compose normalization.

The caller must hold the shared submission lock and exclude other writers.
No files are created and no image or container operations are performed.
"""
import json
import os
import stat
import subprocess

from livy_candidate_assets import ROOT

MAX_COMPOSE_BYTES = 1048576


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_baseline(runtime_fd, *, owner_uid=0):
    name = "compose.yaml"
    before = os.stat(name, dir_fd=runtime_fd, follow_symlinks=False)
    require(stat.S_ISREG(before.st_mode) and before.st_uid == owner_uid
            and before.st_nlink == 1
            and stat.S_IMODE(before.st_mode) == 0o640
            and 0 < before.st_size <= MAX_COMPOSE_BYTES,
            "Existing Compose file must be a bounded, protected, unlinked regular file.")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                 | os.O_NONBLOCK, dir_fd=runtime_fd)
    try:
        def fingerprint(info):
            return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                    info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        require(fingerprint(os.fstat(fd)) == fingerprint(before),
                "Compose identity changed before reading.")
        chunks, size = [], 0
        while True:
            chunk = os.read(fd, min(65536, MAX_COMPOSE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= MAX_COMPOSE_BYTES, "Compose file exceeded its size bound.")
        require(size == before.st_size
                and fingerprint(os.fstat(fd)) == fingerprint(before)
                and fingerprint(os.stat(name, dir_fd=runtime_fd,
                                        follow_symlinks=False)) == fingerprint(before),
                "Compose identity or content metadata changed during reading.")
        return b"".join(chunks)
    finally:
        os.close(fd)


def compose_config(document, *, run=subprocess.run):
    require(isinstance(document, bytes)
            and 0 < len(document) <= MAX_COMPOSE_BYTES,
            "Bounded Compose text is required.")
    text = document.decode("utf-8")
    result = run([
        "docker", "compose",
        "--project-name", "digitafrica-spark",
        "--project-directory", ROOT,
        "--env-file", "/dev/null",
        "--profile", "participant-direct",
        "--profile", "participant-livy",
        "--file", "-",
        "config", "--format", "json",
    ], input=text, text=True, stdout=subprocess.PIPE,
       stderr=subprocess.PIPE, timeout=30, check=False)
    require(result.returncode == 0 and isinstance(result.stdout, str),
            "Docker Compose normalization failed.")
    parsed = json.loads(result.stdout)
    require(isinstance(parsed, dict), "Docker Compose returned an invalid configuration.")
    return parsed
