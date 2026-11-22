#!/usr/bin/env python3
"""Fail-closed staging directory guard (scratch version, not installed)."""
import argparse
import hashlib
import os
import re
import stat
import sys

NAME_RE = re.compile(r"digitafrica-exam-[0-9a-f]{32}")
FILE_NAME = "exam.ipynb"
MAX_BYTES = 100000
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def fail(message, code=1):
    sys.stderr.write("stage-guard: %s\n" % message)
    sys.exit(code)


def require_platform():
    for func in (os.open, os.mkdir, os.unlink, os.rmdir, os.stat):
        if func not in os.supports_dir_fd:
            fail("platform lacks dir_fd support; refusing")
    if os.stat not in os.supports_follow_symlinks:
        fail("platform lacks no-follow stat; refusing")
    if os.listdir not in os.supports_fd:
        fail("platform lacks fd-based listdir; refusing")


def machine_host_id(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read(256).strip()
    except OSError as exc:
        fail("cannot read machine id: %s" % exc)
    if not data:
        fail("machine id is empty")
    return hashlib.sha256(data).hexdigest()


def open_parent(args):
    try:
        fd = os.open(args.parent, DIR_FLAGS)
    except OSError as exc:
        fail("cannot open parent %s: %s" % (args.parent, exc))
    st = os.fstat(fd)
    if st.st_uid != args.uid:
        fail("parent directory is not owned by the expected user")
    if not st.st_mode & stat.S_ISVTX:
        fail("parent directory is not sticky; refusing")
    return fd


def open_stage(args, parent_fd):
    """Open the staging dir and verify identity. Return None if absent."""
    try:
        fd = os.open(args.name, DIR_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        fail("cannot open staging directory without following links: %s" % exc)
    st = os.fstat(fd)
    if (st.st_dev, st.st_ino) != (args.dev, args.ino):
        os.close(fd)
        fail("staging directory is not the one this run created")
    if st.st_uid != args.uid or stat.S_IMODE(st.st_mode) != 0o700:
        os.close(fd)
        fail("staging directory owner or mode is unexpected")
    if [e for e in os.listdir(fd) if e != FILE_NAME]:
        os.close(fd)
        fail("unexpected entries in staging directory")
    return fd


def stat_file(stage_fd):
    try:
        return os.stat(FILE_NAME, dir_fd=stage_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def cmd_create(args):
    host_id = machine_host_id(args.machine_id_file)
    parent_fd = open_parent(args)
    try:
        os.mkdir(args.name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        fail("path already exists; refusing to reuse it", 3)
    except OSError as exc:
        fail("mkdir failed: %s" % exc)
    try:
        fd = os.open(args.name, DIR_FLAGS, dir_fd=parent_fd)
        os.fchmod(fd, 0o700)
        st = os.fstat(fd)
        if st.st_uid != args.uid or os.listdir(fd):
            raise OSError("created directory has unexpected owner or contents")
    except OSError as exc:
        try:
            os.rmdir(args.name, dir_fd=parent_fd)
        except OSError:
            pass
        fail("post-create verification failed: %s" % exc)
    print("STAGE_ID=%d:%d" % (st.st_dev, st.st_ino))
    print("STAGE_HOST=%s" % host_id)


def check_host(args):
    if machine_host_id(args.machine_id_file) != args.host_id:
        fail("host identity differs from the host that created the stage")


def cmd_check(args):
    check_host(args)
    parent_fd = open_parent(args)
    stage_fd = open_stage(args, parent_fd)
    if stage_fd is None:
        fail("staging directory is missing")
    st = stat_file(stage_fd)
    if st is None:
        fail("staged exam is missing")
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != args.uid
            or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1):
        fail("staged exam is not a plain private file owned by the expected user")
    if st.st_size < 1 or st.st_size > MAX_BYTES:
        fail("staged exam size is outside the allowed range")
    try:
        file_fd = os.open(FILE_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=stage_fd)
    except OSError as exc:
        fail("cannot open staged exam without following links: %s" % exc)
    fst = os.fstat(file_fd)
    if (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
        fail("staged exam changed while being checked")
    with os.fdopen(file_fd, "rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) != fst.st_size:
        fail("staged exam size changed while being read")
    print("FILE_SHA256=%s" % hashlib.sha256(data).hexdigest())
    print("FILE_SIZE=%d" % len(data))


def cmd_remove(args):
    check_host(args)
    parent_fd = open_parent(args)
    stage_fd = open_stage(args, parent_fd)
    if stage_fd is None:
        print("STAGE_ABSENT=1")
        return
    st = stat_file(stage_fd)
    if st is not None:
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != args.uid
                or st.st_nlink != 1):
            fail("staged exam is not a plain single-link file owned by the "
                 "expected user; refusing to remove")
        os.unlink(FILE_NAME, dir_fd=stage_fd)
    os.rmdir(args.name, dir_fd=parent_fd)
    print("STAGE_REMOVED=1")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    for name, func in (("create", cmd_create), ("check", cmd_check),
                       ("remove", cmd_remove)):
        p = sub.add_parser(name)
        p.set_defaults(func=func)
        p.add_argument("--name", required=True)
        p.add_argument("--parent", default="/var/tmp")
        p.add_argument("--uid", type=int, default=0)
        p.add_argument("--machine-id-file", default="/etc/machine-id")
        if name != "create":
            p.add_argument("--dev", type=int, required=True)
            p.add_argument("--ino", type=int, required=True)
            p.add_argument("--host-id", required=True)
    return parser


def main():
    args = build_parser().parse_args()
    if not NAME_RE.fullmatch(args.name):
        fail("invalid staging name")
    require_platform()
    args.func(args)


if __name__ == "__main__":
    main()
