"""Reviewed runtime file deletion under both locks and admin-controlled Docker.

No archives. Unknown assets, links, special files and mounted trees fail closed.
The runtime directory and shared lock inode remain coordination infrastructure.
"""
from contextlib import contextmanager
import os
import re
import stat
from teardown_directory import FLAGS, SUBMISSION_COMPONENTS, check_ancestor

ROOT = "/" + "/".join(SUBMISSION_COMPONENTS)
FILES = {"compose.yaml", "livy.conf", "livy-spark-defaults.conf"}
# Fixed candidate layout. No credential contents or archives are read.
TRANSITION_FILES = {
    "compose.livy-transition.yaml": 0o640,
    "livy-transition/livy.conf": 0o644,
    "livy-transition/livy-spark-defaults.conf": 0o644,
    "livy-transition/livy-build/Dockerfile": 0o600,
    "livy-transition/livy-build/.dockerignore": 0o600,
    "livy-transition/livy-build/livy.zip": 0o600,
}
TRANSITION_DIRECTORIES = {
    "livy-transition": 0o750,
    "livy-transition/livy-build": 0o750,
}
TRANSITION_TOP = {"compose.livy-transition.yaml", "livy-transition"}
CLIENT_FILES = {
    "client-build": {"Dockerfile": 0o600, ".dockerignore": 0o600},
    "client-access": {
        "host_key": 0o600, "host_key.pub": 0o644,
        "login_key": 0o600, "login_key.pub": 0o644,
    },
}
LOCK = ".direct-run.lock"
RUN = re.compile(r"(?:direct-run-|livy-client-run-)[a-z0-9_]{8}")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def mount_paths():
    with open("/proc/self/mountinfo", encoding="utf-8") as stream:
        result = set()
        for line in stream:
            fields = line.split()
            require(len(fields) >= 10 and "-" in fields, "Malformed mount information.")
            result.add(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4]))
        return result


def identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


class Assets:
    """Fixed production root; owner_uid/mounts injection supports offline tests."""
    def __init__(self, fd, root=ROOT, owner_uid=0, mounts=mount_paths):
        self.fd, self.root, self.owner_uid, self.mounts = fd, root, owner_uid, mounts
        self.initial = self.scan()

    def _stat(self, fd, name):
        return os.stat(name, dir_fd=fd, follow_symlinks=False)

    def _protected(self, info):
        require(info.st_uid == self.owner_uid and not (stat.S_IMODE(info.st_mode) & 0o022),
                "Runtime asset must be organiser-owned and protected.")

    def _tree(self, parent, name, device, path, mounts):
        require(not any(m == path or m.startswith(path + "/") for m in mounts),
                "Refusing mounted runtime asset: " + path)
        info = self._stat(parent, name)
        require(info.st_dev == device, "Cross-device runtime cleanup refused.")
        if stat.S_ISREG(info.st_mode):
            require(info.st_nlink == 1, "Hard-linked runtime file refused.")
            return
        require(stat.S_ISDIR(info.st_mode), "Symlink or special runtime file refused.")
        fd = os.open(name, FLAGS, dir_fd=parent)
        try:
            require(identity(os.fstat(fd)) == identity(info), "Runtime identity changed.")
            for child in sorted(os.listdir(fd)):
                self._tree(fd, child, device, path + "/" + child, mounts)
        finally:
            os.close(fd)


    def _client_inventory(self, name, entry):
        """Validate approved client files without reading credential contents.

        Partial preparation is supported; unknown entries remain prohibited.
        Capture child identities so replacement also blocks removal.
        """
        require(stat.S_ISDIR(entry.st_mode)
                and stat.S_IMODE(entry.st_mode) == 0o700,
                "Participant client directory must have mode 0700.")
        fd = os.open(name, FLAGS, dir_fd=self.fd)
        try:
            require(identity(os.fstat(fd)) == identity(entry),
                    "Participant client directory identity changed.")
            children = sorted(os.listdir(fd))
            require(set(children) <= set(CLIENT_FILES[name]),
                    "Unknown participant client asset; cleanup refused: " + name)
            result = []
            for child in children:
                info = self._stat(fd, child)
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                        "Linked or special participant client file refused.")
                self._protected(info)
                require(stat.S_IMODE(info.st_mode) == CLIENT_FILES[name][child],
                        "Unexpected participant client permissions: " + child)
                result.append((child, identity(info)))
            return tuple(result)
        finally:
            os.close(fd)

    def _candidate_inventory(self, name):
        """Exact partial layout; capture every candidate inode and metadata.

        Partial staging/removal is allowed. Unknown entries, wrong modes,
        foreign owners, links and cross-device entries remain prohibited.
        """
        device = os.fstat(self.fd).st_dev
        result = []

        def fingerprint(info):
            return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                    info.st_gid, info.st_nlink, info.st_size,
                    info.st_mtime_ns, info.st_ctime_ns)

        def visit(parent, child, relative):
            info = self._stat(parent, child)
            require(info.st_dev == device, "Cross-device candidate cleanup refused.")
            self._protected(info)
            directory = relative in TRANSITION_DIRECTORIES
            mode = (TRANSITION_DIRECTORIES[relative] if directory
                    else TRANSITION_FILES[relative])
            require(stat.S_IMODE(info.st_mode) == mode,
                    "Unexpected candidate permissions: " + relative)
            if not directory:
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                        "Linked or special candidate file refused.")
                result.append((relative, fingerprint(info)))
                return
            require(stat.S_ISDIR(info.st_mode), "Expected protected candidate directory.")
            fd = os.open(child, FLAGS, dir_fd=parent)
            try:
                require(fingerprint(os.fstat(fd)) == fingerprint(info),
                        "Candidate directory changed before inspection.")
                children = sorted(os.listdir(fd))
                allowed = {
                    path[len(relative) + 1:].split("/")[0]
                    for path in (*TRANSITION_FILES, *TRANSITION_DIRECTORIES)
                    if path.startswith(relative + "/")
                }
                require(set(children) <= allowed,
                        "Unknown candidate entry; cleanup refused: " + relative)
                result.append((relative, fingerprint(info)))
                for entry in children:
                    visit(fd, entry, relative + "/" + entry)
                require(fingerprint(os.fstat(fd)) == fingerprint(info)
                        and fingerprint(self._stat(parent, child)) == fingerprint(info),
                        "Candidate directory changed during inspection.")
            finally:
                os.close(fd)

        visit(self.fd, name, name)
        return tuple(result)

    def check_remaining_docker_sources(self, sources):
        """Inspection-only guard after owned resources stop, under both locks.

        Any remaining container, including stopped or unrelated containers,
        blocks removal if a bind source overlaps a removable runtime asset.
        The preserved submission lock alone is not a removal target.
        """
        require(isinstance(sources, (list, tuple, set))
                and all(isinstance(source, str) and source.startswith("/")
                        and "\x00" not in source
                        and not any(part in {".", ".."} for part in source.split("/"))
                        for source in sources),
                "Fresh absolute Docker bind sources are required.")
        targets = [self.root.rstrip("/") + "/" + name for name in self.initial]
        for source in sources:
            source = "/" + "/".join(part for part in source.split("/") if part)
            require(not any(
                source == target
                or source.startswith(target + "/")
                or target.startswith(source.rstrip("/") + "/")
                for target in targets),
                "Remaining Docker bind source intersects removable runtime assets.")

    def scan(self):
        if self.fd is None:
            return {}
        info = os.fstat(self.fd)
        self._protected(info)
        mounts, result = self.mounts(), {}
        for name in sorted(os.listdir(self.fd)):
            entry = self._stat(self.fd, name)
            if name == LOCK:
                require(stat.S_ISREG(entry.st_mode) and entry.st_uid == self.owner_uid
                        and stat.S_IMODE(entry.st_mode) == 0o600 and entry.st_nlink == 1,
                        "Invalid preserved submission lock.")
                continue
            self._protected(entry)
            if name in FILES or name == 'compose.livy-transition.yaml':
                require(stat.S_ISREG(entry.st_mode), "Expected generated configuration file.")
            elif name in {"livy-build", "livy-transition"} or name in CLIENT_FILES or RUN.fullmatch(name):
                require(stat.S_ISDIR(entry.st_mode), "Expected generated runtime directory.")
            else:
                raise ValueError("Unknown runtime asset; cleanup refused: " + name)
            candidate = self._candidate_inventory(name) if name in TRANSITION_TOP else None
            self._tree(self.fd, name, info.st_dev, self.root + "/" + name, mounts)
            result[name] = candidate if candidate is not None else identity(entry)
            if name in CLIENT_FILES:
                result[name] = (identity(entry), self._client_inventory(name, entry))
        return result

    def _delete(self, parent, name, device):
        info = self._stat(parent, name)
        require(info.st_dev == device, "Cross-device cleanup refused.")
        if stat.S_ISREG(info.st_mode):
            require(info.st_nlink == 1, "Hard-linked runtime file refused.")
            os.unlink(name, dir_fd=parent)
            return
        require(stat.S_ISDIR(info.st_mode), "Symlink or special runtime file refused.")
        fd = os.open(name, FLAGS, dir_fd=parent)
        try:
            require(identity(os.fstat(fd)) == identity(info), "Runtime identity changed.")
            for child in sorted(os.listdir(fd)):
                self._delete(fd, child, device)
            os.fsync(fd)
            require(identity(self._stat(parent, name)) == identity(info),
                    "Runtime directory replaced during removal.")
            os.rmdir(name, dir_fd=parent)
        finally:
            os.close(fd)

    def remove(self):
        # Orphans can finish writing before shutdown: revalidate current trees,
        # requiring protected top-level inodes (not all output files) to match.
        current = self.scan()
        require(current == self.initial, "Runtime asset identities changed.")
        if self.fd is None:
            return []
        for name in sorted(current):
            self._delete(self.fd, name, os.fstat(self.fd).st_dev)
        os.fsync(self.fd)
        require(not self.scan(), "Runtime assets remain or appeared.")
        return [self.root + "/" + name for name in sorted(current)]


@contextmanager
def validated_runtime_assets():
    if os.geteuid() != 0:
        raise PermissionError("Runtime asset cleanup requires root.")
    descriptors = []
    try:
        fd = os.open("/", FLAGS)
        descriptors.append(fd)
        check_ancestor(fd)
        for component in SUBMISSION_COMPONENTS:
            try:
                fd = os.open(component, FLAGS, dir_fd=fd)
            except FileNotFoundError:
                yield Assets(None)
                return
            descriptors.append(fd)
            check_ancestor(fd)
        yield Assets(fd)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
