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


# Keep this lock inode in place: both organiser runners use this exact file.
SUBMISSION_COMPONENTS = ("opt", "digitafrica", "big-data", "runtime", "spark")


@contextmanager
def locked_submission_runtime():
    """Exclude cooperating Step 1/Step 2 runners throughout teardown.

    Missing runtime ancestors are not created. A runner cannot use a missing
    runtime directory. Concurrent runtime provisioning and other Docker users
    remain outside this cooperative lock and require administrator control.
    """
    if os.geteuid() != 0:
        raise PermissionError("Spark teardown requires root privileges.")
    descriptors = []
    try:
        fd = os.open("/", FLAGS)
        descriptors.append(fd)
        check_ancestor(fd)
        for component in SUBMISSION_COMPONENTS:
            try:
                fd = os.open(component, FLAGS, dir_fd=fd)
            except FileNotFoundError:
                yield None
                return
            descriptors.append(fd)
            check_ancestor(fd)

        lock_fd = os.open(
            ".direct-run.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=fd,
        )
        descriptors.append(lock_fd)
        info = os.fstat(lock_fd)
        if not (
            stat.S_ISREG(info.st_mode) and info.st_uid == 0
            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
        ):
            raise ValueError("Invalid organiser submission lock file.")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "An organiser Spark submission holds .direct-run.lock; "
                "finish the submission before resetting."
            ) from error
        yield lock_fd
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
