"""Scoped image-reference removal under both locks and exclusive admin control.

No force, no prune, no build-cache deletion, no removal of unrelated image
references. Shared image objects/layers can remain under unrelated references.
Any remaining container using a target image or descendant blocks cleanup.
"""
import json
import re
from teardown_docker import full_id

SPARK = 'apache/spark@sha256:d0f5d63bfbbffdbec08debb4911554ba671a2fa7398374db8db314d80328f576'
LIVY = 'digitafrica/livy:0.9.0-incubating-spark3.5.3'
ARCHIVE_SHA512 = '50151be834bba3011fccbb564c3c9d6bf7a08af468c2082604f3c5b40ba95705a4c2e925e835bd58a58abcbeb18f3ab7bf588e01fa4f778ff9e82a4b91b9d2de'
DOCKERFILE_SHA512 = 'b2c6bd9f9e95b90e534aadc0cba9acd0af0e17beec5c6455d70bba99add05630ac1ee4e44311067674e1475843fa33b44e015a02cb58c5baafd5412cba6915ad'
SSH_CLIENT = 'digitafrica/spark-client:3.5.3-ssh-v1'
SSH_LABELS = {
    'org.digitafrica.workshop': 'big-data',
    'org.digitafrica.module': 'spark',
    'org.digitafrica.managed-by': 'organiser',
}
SSH_CMD = ['/usr/sbin/sshd', '-D', '-e', '-f', '/etc/ssh/workshop_sshd_config']
ORDER = (SSH_CLIENT, LIVY, SPARK)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def image_id(value):
    require(isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value),
            "Expected full Docker image ID.")
    return value


class ImageCleanup:
    def __init__(self, docker):
        self.docker = docker
        # Verify all reviewed references before destructive resource teardown starts.
        self.initial = self.snapshot()

    def _metadata(self, reference, identifier):
        rows = json.loads(self.docker.command("image", "inspect", reference))
        require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict),
                "Invalid image inspection response.")
        info = rows[0]
        require(image_id(info.get("Id")) == identifier, "Image inspection ID mismatch.")
        require(info.get("Os") == "linux" and info.get("Architecture") == "amd64",
                "Workshop image platform mismatch.")
        if reference == SPARK:
            digests = info.get("RepoDigests")
            require(isinstance(digests, list) and SPARK in digests,
                    "Pinned Spark repository digest mismatch.")
        elif reference == SSH_CLIENT:
            tags = info.get("RepoTags")
            require(isinstance(tags, list) and SSH_CLIENT in tags,
                    "Participant client repository tag mismatch.")
            config = info.get("Config")
            require(isinstance(config, dict), "Invalid participant client image configuration.")
            labels, env = config.get("Labels"), config.get("Env")
            require(isinstance(labels, dict) and isinstance(env, list)
                    and all(labels.get(k) == v for k, v in SSH_LABELS.items()),
                    "Participant client image ownership mismatch.")
            require(config.get("User") == "root" and config.get("Cmd") == SSH_CMD
                    and config.get("WorkingDir") == "/home/workshop/work"
                    and "SPARK_HOME=/opt/spark" in env
                    and "SPARK_DRIVER_HOST=spark-client" in env
                    and "SPARK_MASTER_URL=spark://spark-master:7077" in env,
                    "Participant client image runtime configuration mismatch.")
        else:
            tags = info.get("RepoTags")
            require(isinstance(tags, list) and LIVY in tags, "Livy repository tag mismatch.")
            config = info.get("Config")
            require(isinstance(config, dict), "Invalid Livy image configuration.")
            env, labels = config.get("Env"), config.get("Labels")
            require(isinstance(env, list) and isinstance(labels, dict),
                    "Missing Livy environment or provenance labels.")
            require(config.get("User") == "185:0"
                    and config.get("Cmd") == ["/opt/livy/bin/livy-server"]
                    and "LIVY_SERVER_START_MODE=foreground" in env,
                    "Livy runtime configuration mismatch.")
            require(labels.get("org.digitafrica.livy.archive-sha512") == ARCHIVE_SHA512
                    and labels.get("org.digitafrica.livy.dockerfile-sha512") == DOCKERFILE_SHA512
                    and labels.get("org.digitafrica.livy.spark-base") == SPARK,
                    "Livy provenance mismatch; image cleanup refused.")
        return identifier

    def snapshot(self):
        # Listing succeeds with an empty daemon. Do not reinterpret inspect,
        # permission or connection failures as an already-absent reference.
        output = self.docker.command("image", "ls", "--all", "--no-trunc",
                                     "--digests", "--format", "{{json .}}")
        found = {}
        for line in output.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            require(isinstance(row, dict), "Invalid image listing response.")
            reference = None
            if (row.get("Repository") == "apache/spark"
                    and row.get("Digest") == SPARK.split("@", 1)[1]):
                reference = SPARK
            elif row.get("Repository") == "digitafrica/livy" and row.get("Tag") == LIVY.split(":", 1)[1]:
                reference = LIVY
            elif row.get("Repository") == "digitafrica/spark-client" and row.get("Tag") == SSH_CLIENT.split(":", 1)[1]:
                reference = SSH_CLIENT
            if reference is not None:
                identifier = image_id(row.get("ID"))
                require(reference not in found or found[reference] == identifier,
                        "Conflicting image listing identities.")
                found[reference] = identifier
        for reference, identifier in found.items():
            self._metadata(reference, identifier)
        return found

    def remove(self):
        current = self.snapshot()
        require(current == self.initial, "Workshop image identities changed during teardown.")
        # Check every target before the first image removal. Include stopped
        # containers and descendants; preserve shared users by failing closed.
        for identifier in set(current.values()):
            users = self.docker.command("container", "ls", "--all", "--quiet", "--no-trunc",
                                        "--filter", "ancestor=" + identifier).split()
            for user in users:
                full_id(user)
            if users:
                raise RuntimeError("Workshop image still used by a container or descendant; "
                                   "image cleanup refused: " + identifier)
        removed = []
        for reference in ORDER:
            if reference not in current:
                continue
            self._metadata(reference, current[reference])
            self.docker.command("image", "rm", reference)
            removed.append(reference)
        require(not self.snapshot(), "Workshop image references remain or were recreated.")
        return removed
