"""Protected create-only candidate storage; no Docker commands or live entry point.

Inputs must be trusted, rendered organiser assets with a verified Livy archive.
The live caller must exclude non-cooperating filesystem and Docker writers.
Partial failures retain evidence; no rollback or deletion is performed.
"""
from contextlib import ExitStack
import os
import stat

ROOT = "/opt/digitafrica/big-data/runtime/spark"
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILES = {
    "compose.livy-transition.yaml": 0o640,
    "livy-transition/livy.conf": 0o644,
    "livy-transition/livy-spark-defaults.conf": 0o644,
    "livy-transition/livy-build/Dockerfile": 0o600,
    "livy-transition/livy-build/.dockerignore": 0o600,
    "livy-transition/livy-build/livy.zip": 0o600,
}
DIRECTORIES = ("livy-transition", "livy-transition/livy-build")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


class CandidateAssets:
    """Descriptor-relative storage; injected root/owner support disposable tests."""

    def __init__(self, fd, *, root=ROOT, owner_uid=0):
        self.fd, self.root, self.owner_uid = fd, root, owner_uid
        self._directory(os.fstat(fd))

    def _directory(self, info):
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == self.owner_uid
                and not (stat.S_IMODE(info.st_mode) & 0o022),
                "Candidate ancestor must be organiser-owned and protected.")

    def _open_parent(self, stack, relative):
        parts = relative.split("/")
        fd = self.fd
        for component in parts[:-1]:
            child = os.open(component, FLAGS, dir_fd=fd)
            stack.callback(os.close, child)
            self._directory(os.fstat(child))
            fd = child
        return fd, parts[-1]

    def check_mounts(self, observation):
        require(isinstance(observation, dict)
                and set(observation) == {"docker_sources", "host_mounts"},
                "Fresh Docker-source and host-mount observations are required.")
        for values in observation.values():
            require(isinstance(values, (list, tuple, set))
                    and all(isinstance(value, str) and value.startswith("/")
                            for value in values),
                    "Invalid mounted-path observation.")
        targets = [self.root + "/livy-transition",
                   self.root + "/compose.livy-transition.yaml"]
        for source in observation["docker_sources"]:
            source = source.rstrip("/") or "/"
            require(not any(
                source == target or source.startswith(target + "/")
                or target.startswith(source.rstrip("/") + "/")
                for target in targets),
                "Candidate assets intersect a Docker bind source.")
        for mount in observation["host_mounts"]:
            mount = mount.rstrip("/") or "/"
            require(not any(mount == target or mount.startswith(target + "/")
                            for target in targets),
                    "Candidate asset is a host mount or contains one.")

    def scan(self, files):
        """Validate every existing candidate asset before creating anything."""
        found = {}
        for directory in DIRECTORIES:
            with ExitStack() as stack:
                try:
                    parent, name = self._open_parent(stack, directory)
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                self._directory(info)
                child = os.open(name, FLAGS, dir_fd=parent)
                stack.callback(os.close, child)
                require(identity(os.fstat(child)) == identity(info),
                        "Candidate directory identity changed.")
                allowed = {path[len(directory) + 1:].split("/")[0]
                           for path in (*FILES, *DIRECTORIES)
                           if path.startswith(directory + "/")}
                require(set(os.listdir(child)) <= allowed,
                        "Unknown candidate directory entry.")
                found[directory] = identity(info)
        for relative, mode in FILES.items():
            with ExitStack() as stack:
                try:
                    parent, name = self._open_parent(stack, relative)
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                        and info.st_uid == self.owner_uid
                        and stat.S_IMODE(info.st_mode) == mode,
                        "Linked, special or unprotected candidate file.")
                require(info.st_size == len(files[relative]),
                        "Existing candidate content differs; replacement refused.")
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                             | os.O_NONBLOCK, dir_fd=parent)
                stack.callback(os.close, fd)
                require(identity(os.fstat(fd)) == identity(info),
                        "Candidate file identity changed.")
                offset = 0
                while offset < len(files[relative]):
                    chunk = os.read(fd, min(1048576, len(files[relative]) - offset))
                    require(chunk and chunk == files[relative][offset:offset + len(chunk)],
                            "Existing candidate content differs; replacement refused.")
                    offset += len(chunk)
                require(os.read(fd, 1) == b"", "Candidate file grew during inspection.")
                found[relative] = identity(info)
        return found

    def stage(self, files, observe_mounts):
        require(isinstance(files, dict) and set(files) == set(FILES)
                and all(isinstance(value, bytes) and value for value in files.values()),
                "Exactly the six nonempty trusted candidate assets are required.")
        self.check_mounts(observe_mounts())
        initial = self.scan(files)
        self.check_mounts(observe_mounts())
        require(self.scan(files) == initial, "Candidate identities changed before staging.")
        created = []
        for relative in DIRECTORIES:
            if relative in initial:
                continue
            with ExitStack() as stack:
                parent, name = self._open_parent(stack, relative)
                os.mkdir(name, mode=0o750, dir_fd=parent)
                child = os.open(name, FLAGS, dir_fd=parent)
                try:
                    os.fchmod(child, 0o750)
                    self._directory(os.fstat(child))
                finally:
                    os.close(child)
                os.fsync(parent)
        # Publish the candidate definition only after its referenced assets.
        ordered_files = sorted(
            FILES, key=lambda name: name == "compose.livy-transition.yaml")
        for relative in ordered_files:
            mode = FILES[relative]
            if relative in initial:
                continue
            with ExitStack() as stack:
                parent, name = self._open_parent(stack, relative)
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=parent)
                stack.callback(os.close, fd)
                os.fchmod(fd, mode)
                view = memoryview(files[relative])
                while view:
                    count = os.write(fd, view)
                    require(count > 0, "Candidate write made no progress.")
                    view = view[count:]
                os.fsync(fd)
                os.fsync(parent)
                created.append(relative)
        final = self.scan(files)
        require(set(final) == set(FILES) | set(DIRECTORIES),
                "Candidate staging is incomplete.")
        require(all(final[name] == value for name, value in initial.items()),
                "Existing candidate identity changed during staging.")
        return created


def stage_candidate(files, *, submission_lock, open_runtime, observe_mounts):
    """Adapters supply the real shared lock, protected runtime FD and observations."""
    with submission_lock() as lock_fd:
        require(lock_fd is not None, "Existing submission runtime is required.")
        with open_runtime() as runtime_fd:
            return CandidateAssets(runtime_fd).stage(files, observe_mounts)
