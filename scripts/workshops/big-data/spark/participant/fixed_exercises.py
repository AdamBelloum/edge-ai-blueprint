#!/usr/bin/env python3
"""Protected-source approval checks for the fixed-exercise Spark pilot.

The sole wire protocol is submission/protocol.py. This module checks the
organiser-approved source snapshot; it does not parse participant requests,
grant group access, start a subprocess or contact Spark/Livy. The service must
handle status separately and call load_approved_exercise only for a validated
run operation. Approval hashes and source paths are never supplied by clients.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType

MAX_SOURCE_BYTES = 131072
MAX_MANIFEST_BYTES = 16384
_SOURCE_ROOT = Path('/opt/digitafrica/big-data/spark')
_APPROVAL_ROOT = Path('/opt/digitafrica/big-data/runtime/spark/participant')
_ROOT_UID = 0
_ROOT_GID = 0
_FILES = MappingProxyType({
    'direct': ('01_spark_basics.py', 'filtered_preview.csv'),
    'livy': ('02_spark_via_livy.py', '02_filtered_preview.csv'),
})




class ApprovalError(RuntimeError):
    pass




@dataclass(frozen=True)
class ApprovedExercise:
    action: str
    source_name: str
    preview_name: str
    source_sha256: str
    source: bytes


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _decode_object(raw, limit, error_type):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise error_type('Expected nonempty bytes within the size limit')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise error_type('Invalid UTF-8 JSON: ' + str(exc)) from exc
    if type(value) is not dict:
        raise error_type('Expected a JSON object')
    return value


def _exercise_files(action, error_type):
    if type(action) is not str or action not in _FILES:
        raise error_type('Action must be direct or livy')
    return _FILES[action]




def parse_approval_manifest(raw):
    value = _decode_object(raw, MAX_MANIFEST_BYTES, ApprovalError)
    if set(value) != {'version', 'exercises'}:
        raise ApprovalError('Unexpected approval manifest fields')
    if type(value['version']) is not int or value['version'] != 1:
        raise ApprovalError('Unsupported approval manifest version')
    hashes = value['exercises']
    if type(hashes) is not dict or set(hashes) != set(_FILES):
        raise ApprovalError('Approval must cover exactly direct and livy')
    for digest in hashes.values():
        if type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
            raise ApprovalError('Expected lowercase SHA-256 approval hashes')
    return MappingProxyType(dict(hashes))


def _require_protected(info, directory=False):
    kind_ok = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not kind_ok or info.st_uid != _ROOT_UID or info.st_gid != _ROOT_GID:
        raise ApprovalError('Expected a root-owned protected directory or regular file')
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ApprovalError('Group/world-writable approval material is forbidden')
    if not directory and info.st_nlink != 1:
        raise ApprovalError('Hard-linked approval material is forbidden')


def _open_protected_directory(path):
    # Walk from / using directory descriptors: no symlinked ancestors, and no
    # writable ancestor through which a non-root user could replace the tree.
    if not path.is_absolute() or '..' in path.parts:
        raise ApprovalError('Expected a fixed absolute protected directory')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = None
    try:
        fd = os.open('/', flags)
        _require_protected(os.fstat(fd), directory=True)
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            _require_protected(os.fstat(fd), directory=True)
        result, fd = fd, None
        return result
    except OSError as exc:
        raise ApprovalError('Protected directory unavailable: ' + str(exc)) from exc
    finally:
        if fd is not None:
            os.close(fd)


def _read_protected_file(directory_fd, name, limit):
    if '/' in name or name in ('', '.', '..'):
        raise ApprovalError('Internal filename must be a basename')
    _require_protected(os.fstat(directory_fd), directory=True)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    fd = None
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
        before = os.fstat(fd)
        _require_protected(before)
        if not 0 < before.st_size <= limit:
            raise ApprovalError('Protected file is empty or exceeds its size limit')
        with os.fdopen(fd, 'rb') as handle:
            fd = None
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        fingerprint = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if fingerprint(before) != fingerprint(after) or len(raw) != before.st_size:
            raise ApprovalError('Protected file changed while being read')
        return raw
    except OSError as exc:
        raise ApprovalError('Protected file unavailable: ' + str(exc)) from exc
    finally:
        if fd is not None:
            os.close(fd)


def load_approved_exercise(action):
    source_name, preview_name = _exercise_files(action, ApprovalError)
    approval_fd = _open_protected_directory(_APPROVAL_ROOT)
    try:
        hashes = parse_approval_manifest(_read_protected_file(
            approval_fd, 'approved-exercises.json', MAX_MANIFEST_BYTES))
    finally:
        os.close(approval_fd)
    source_fd = _open_protected_directory(_SOURCE_ROOT)
    try:
        source = _read_protected_file(source_fd, source_name, MAX_SOURCE_BYTES)
    finally:
        os.close(source_fd)
    digest = hashlib.sha256(source).hexdigest()
    if not hmac.compare_digest(digest, hashes[action]):
        raise ApprovalError('Exercise source differs from the organiser-approved version')
    try:
        compile(source.decode('utf-8'), source_name, 'exec')
    except (UnicodeError, SyntaxError, ValueError) as exc:
        raise ApprovalError('Approved source is not valid Python: ' + str(exc)) from exc
    # Compilation validates syntax but never executes the source.
    return ApprovedExercise(action, source_name, preview_name, digest, source)
