"""Secure host-local evidence directory and cooperating-run lock."""
from contextlib import contextmanager
import fcntl
import os
import stat

from teardown_evidence import check_directory

NAME = "digitafrica-spark-teardown"
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def check_ancestor(fd):
    info = os.fstat(fd)
    if not (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == 0
        and not (stat.S_IMODE(info.st_mode) & 0o022)
    ):
        raise ValueError("Evidence ancestor must be root-owned and not writable by others.")


@contextmanager
def locked_evidence_directory():
    """Open /var/lib/digitafrica-spark-teardown without following symlinks.

    The directory must never be removed/replaced during cooperating runs:
    its inode is also the lock identity. This does not lock other Docker users.
    """
    if os.geteuid() != 0:
        raise PermissionError("Spark teardown requires root privileges.")

    descriptors = []
    try:
        fd = os.open("/", FLAGS)
        descriptors.append(fd)
        check_ancestor(fd)
        for component in ("var", "lib"):
            fd = os.open(component, FLAGS, dir_fd=fd)
            descriptors.append(fd)
            check_ancestor(fd)

        parent_fd = fd
        try:
            os.mkdir(NAME, mode=0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass

        fd = os.open(NAME, FLAGS, dir_fd=parent_fd)
        descriptors.append(fd)
        check_directory(fd)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another Spark teardown holds the evidence lock.") from error

        yield fd
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
