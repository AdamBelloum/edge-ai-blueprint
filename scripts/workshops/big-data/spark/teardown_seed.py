"""Delete the reviewed worker-side Spark seed/data bundle under both locks.

Global reset must first stop selected participant servers. No participant
workspaces, identities, repository sources, other workshop seeds or shared
services are modified here. Unknown files fail closed; no archives.
"""
from contextlib import contextmanager
import os
import stat
from teardown_assets import Assets, identity, mount_paths, require
from teardown_directory import FLAGS, check_ancestor

COMPONENTS = ("opt", "digitafrica", "big-data", "spark")
ROOT = "/" + "/".join(COMPONENTS)
FILES = {
    "README.md", "01_spark_basics.ipynb", "01_spark_basics.py",
    "02_spark_via_livy.ipynb", "02_spark_via_livy.py", "participants-instructions.md",
    "data/Bank_Personal_Loan_Modelling.csv", "docs/spark-DA.pdf",
}
# Extra root-owned paths observed on both Tier-2 workers during live reset.
# These are cleanup-only compatibility paths, NOT current publication inputs.
# The fixed protected seed root and all existing safety checks still apply.
LEGACY_FILES = {"01-spark-beginner.ipynb", "data-analytics.py"}
FILES |= LEGACY_FILES
DIRECTORIES = {"data", "docs"}


class SeedAssets(Assets):
    def __init__(self, fd, root=ROOT, owner_uid=0, mounts=mount_paths, parent_fd=None):
        self.parent_fd = parent_fd
        super().__init__(fd, root, owner_uid, mounts)

    def _tree(self, parent, name, device, path, mounts):
        relative = path[len(self.root) + 1:]
        require(relative in FILES or relative in DIRECTORIES,
                "Unknown staged Spark seed entry: " + relative)
        info = self._stat(parent, name)
        self._protected(info)
        if relative in FILES:
            require(stat.S_ISREG(info.st_mode), "Seed file must be regular: " + relative)
        else:
            require(stat.S_ISDIR(info.st_mode), "Seed directory must be real: " + relative)
        super()._tree(parent, name, device, path, mounts)

    def scan(self):
        if self.fd is None:
            return {}
        root_info = os.fstat(self.fd)
        self._protected(root_info)
        mounts = self.mounts()
        require(self.root not in mounts, "Mounted seed root refused.")
        result = {}
        for name in sorted(os.listdir(self.fd)):
            self._tree(self.fd, name, root_info.st_dev, self.root + "/" + name, mounts)
            result[name] = identity(self._stat(self.fd, name))
        return result

    def remove(self):
        removed = super().remove()
        if self.fd is None:
            return removed
        require(self.parent_fd is not None, "Seed parent descriptor required.")
        name = self.root.rsplit("/", 1)[1]
        require(identity(self._stat(self.parent_fd, name)) == identity(os.fstat(self.fd)),
                "Seed root replaced during removal.")
        os.rmdir(name, dir_fd=self.parent_fd)
        os.fsync(self.parent_fd)
        try:
            self._stat(self.parent_fd, name)
        except FileNotFoundError:
            return removed + [self.root]
        raise RuntimeError("Seed root remains or was recreated.")


@contextmanager
def validated_seed_assets():
    """Open the fixed seed root without following links or creating paths."""
    if os.geteuid() != 0:
        raise PermissionError("Seed cleanup requires root.")
    descriptors = []
    try:
        fd = os.open("/", FLAGS)
        descriptors.append(fd)
        check_ancestor(fd)
        parent_fd = None
        for component in COMPONENTS:
            parent_fd = fd
            try:
                fd = os.open(component, FLAGS, dir_fd=fd)
            except FileNotFoundError:
                yield SeedAssets(None)
                return
            descriptors.append(fd)
            check_ancestor(fd)
        yield SeedAssets(fd, parent_fd=parent_fd)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
