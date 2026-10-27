"""Protected evidence I/O using an already securely opened directory descriptor."""
import json
import os
import re
import secrets
import stat

NAME = "verified-legacy-networks.json"


def check_directory(directory_fd):
    info = os.fstat(directory_fd)
    if not (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == 0
        and stat.S_IMODE(info.st_mode) == 0o700
    ):
        raise ValueError("Evidence directory must be root-owned and mode 0700.")


def check_record(record, daemon_id):
    if not isinstance(daemon_id, str) or not daemon_id:
        raise ValueError("Docker daemon identity is required.")
    if not isinstance(record, dict) or record.get("schema") != 1:
        raise ValueError("Invalid evidence schema.")
    if record.get("daemon_id") != daemon_id:
        raise ValueError("Evidence belongs to a different Docker daemon.")
    ids = record.get("legacy_network_ids")
    if not isinstance(ids, list) or not all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        for value in ids
    ):
        raise ValueError("Invalid legacy network IDs.")
    return set(ids)


def load_evidence(directory_fd, daemon_id):
    check_directory(directory_fd)
    if not isinstance(daemon_id, str) or not daemon_id:
        raise ValueError("Docker daemon identity is required.")
    try:
        fd = os.open(
            NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return set()
    with os.fdopen(fd, "r") as stream:
        info = os.fstat(stream.fileno())
        if not (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == 0
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_nlink == 1
            and info.st_size <= 65536
        ):
            raise ValueError("Unsafe evidence file.")
        return check_record(json.load(stream), daemon_id)


def save_evidence(directory_fd, daemon_id, network_ids):
    check_directory(directory_fd)
    record = {
        "schema": 1,
        "daemon_id": daemon_id,
        "legacy_network_ids": sorted(set(network_ids)),
    }
    check_record(record, daemon_id)
    # A clean reset must not manufacture a retry record solely to delete it.
    # Existing records are still updated to empty after network verification.
    if not record["legacy_network_ids"]:
        try:
            os.stat(NAME, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
    temporary = ".evidence-" + secrets.token_hex(16)
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600, dir_fd=directory_fd,
    )
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(record, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary, NAME,
            src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def clear_evidence(directory_fd, daemon_id):
    """Delete an empty, validated retry record; retain the lock directory."""
    if load_evidence(directory_fd, daemon_id):
        raise ValueError("Cannot discard unresolved legacy-network evidence.")
    try:
        os.unlink(NAME, dir_fd=directory_fd)
    except FileNotFoundError:
        return False
    os.fsync(directory_fd)
    return True
