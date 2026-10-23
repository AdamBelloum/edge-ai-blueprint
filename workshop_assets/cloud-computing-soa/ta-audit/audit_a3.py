"""TA audit for Assignment 3 (containers and Kubernetes).

Part 3.1, on the Docker host, with the students' Compose project running:

    python audit_a3.py --part 3.1 --compose-dir DIR [--url URL --auth-url URL] [--allow-restart]

Part 3.2, with kubectl access to the students' cluster (on the control-plane
VM, or from another computer with --kubectl "ssh USER@VM kubectl"):

    python audit_a3.py --part 3.2 --namespace NS --url http://NODE_IP:PORT \\
        --auth-url http://NODE_IP:PORT [--allow-restart]

This is not the students' grading script. It inspects the containers, the
images, the cluster objects and the running services, and reports each
problem with its evidence. --allow-restart lets it restart the services to
check that the data survives (docker compose restart, down and up -d; kubectl
rollout restart); without it, those checks are skipped. For the API itself,
run audit_a2.py against the same URLs. FAIL is a violation of the assignment
or a bug, WARN a questionable choice to discuss in the oral exam, INFO an
observation. See README.md.

The audit tells the shortener from the authentication service by the ports of
--url and --auth-url, or else by their names; --shortener-service and
--auth-service name them when that is not enough (behind a proxy, for
example). It creates accounts and mappings, and deletes the mappings it made.
"""
import argparse
import base64
import collections
import concurrent.futures
import json
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

import requests

from audit_a2 import A2Context
from audit_common import (
    PEM_PRIVATE_KEY, ServiceUnreachable, gives_url, holds_private_key, print_report, registry, returned_id,
    run_checks, shorten, wait_for, write_markdown,
)

CHECKS_31, check_31 = registry()
CHECKS_32, check_32 = registry()

# Folders of the operating system and of installed packages, where files
# that look like clutter (a .git folder, a cache) are not the students' doing.
SYSTEM_FOLDERS = ("bin/", "boot/", "dev/", "etc/ssl/", "lib/", "lib32/", "lib64/", "libx32/", "proc/", "run/",
                  "sbin/", "sys/", "usr/bin/", "usr/include/", "usr/lib/", "usr/lib64/", "usr/libexec/",
                  "usr/local/bin/", "usr/local/include/", "usr/local/lib/", "usr/local/share/", "usr/sbin/",
                  "usr/share/", "var/cache/", "var/lib/", "var/log/")
# Files the search for private keys skips: installed packages and the Python
# test suite ship test keys, and nobody keeps a signing key there.
NOT_KEY_FILES = re.compile(r"^/(?:proc|sys|dev)/|^/usr/share/doc/|/(?:site|dist)-packages/"
                           r"|/lib/python[0-9.]*/test/|snakeoil")
# Files a service does not need in its image: (pattern whose group is the
# folder to report, what it is, whether to look in SYSTEM_FOLDERS too).
CLUTTER = [
    (re.compile(r"(.*?/\.git)/"), "a Git repository", False),
    (re.compile(r"(.*?)/pyvenv\.cfg$"), "a virtual environment that the image does not use", False),
    (re.compile(r"(.*?/\.pytest_cache)/"), "pytest caches", False),
    (re.compile(r"(.*?/\.(?:idea|vscode))/"), "editor settings", False),
    (re.compile(r"(.*/\.DS_Store)$"), "macOS folder files", False),
    (re.compile(r"(/root/\.cache/pip)/"), "pip's download cache (use pip install --no-cache-dir)", False),
    (re.compile(r"(/var/lib/apt/lists)/[^/]*_(?:Packages|Sources|Translation|Contents)"),
     "apt package lists (delete them in the RUN that installs the packages)", True),
]
ANONYMOUS_VOLUME = re.compile(r"[0-9a-f]{64}")
READ_ONLY_VOLUMES = {"configMap", "secret", "projected", "downwardAPI"}
SCRATCH_FOLDERS = ("/tmp", "/var/tmp", "/run", "/var/run", "/dev/shm")
SYSTEM_NAMESPACES = re.compile(r"^kube-|calico|tigera|flannel|cilium|weave|metallb|ingress|traefik")
# Words in the name of a service or Deployment.
AUXILIARY_WORDS = {"db", "database", "redis", "postgres", "postgresql", "mongo", "mongodb", "mysql", "mariadb",
                   "sqlite", "cache", "memcached", "nginx", "proxy", "gateway", "ingress", "traefik", "haproxy",
                   "lb", "nfs", "storage", "store", "init", "setup", "keygen", "keys", "migrate"}
AUTH_WORDS = {"auth", "authentication", "login", "users", "user", "accounts", "account", "identity", "jwt"}
SHORTENER_WORDS = {"shortener", "short", "shorten", "url", "urls", "link", "links", "shorturl", "urlshortener"}
# Run with python inside a pod: print the files under the given folders that hold a private key.
SCAN_SCRIPT = (
    "import os, re, sys\n"
    f"pattern = re.compile({PEM_PRIVATE_KEY.pattern!r})\n"
    "for top in sys.argv[1:]:\n"
    "    for folder, _, names in os.walk(top):\n"
    "        for name in names:\n"
    "            path = os.path.join(folder, name)\n"
    "            try:\n"
    "                if os.path.getsize(path) < 2000000 and pattern.search(open(path, 'rb').read()):\n"
    "                    print(path)\n"
    "            except OSError:\n"
    "                pass\n")


class A3Context(A2Context):
    def __init__(self, args, token_style):
        super().__init__(args.url, args.auth_url, token_style)
        self.part = args.part
        self.compose_dir = Path(args.compose_dir).resolve() if args.compose_dir else None
        self.project = args.project
        self.namespace = args.namespace
        self.kubectl = shlex.split(args.kubectl)
        self.allow_restart = args.allow_restart
        self.named = {"shortener": args.shortener_service, "auth": args.auth_service}
        self.unreachable = None  # why the services do not answer, if they do not

    def execute(self, command, timeout=300, cwd=None):
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        except FileNotFoundError:
            self.skip(f"{command[0]} not found")

    def need_services(self):
        if self.unreachable:
            self.skip(f"the services do not answer ({self.unreachable}); see COMPOSE-03 or K8S-09")

    def roles(self):
        """Compose service (3.1) or Deployment (3.2) name -> "shortener" or "auth"."""
        if "roles" not in self.shared:
            targets = {"shortener": url_key(self.public.base_url), "auth": url_key(self.auth.base_url)}
            self.shared["roles"] = assign_roles(self.named, self.endpoints(), targets)
        return self.shared["roles"]

    def endpoints(self):
        """Name -> the (host, port) pairs that reach it from outside; host None means any address."""
        found = {}
        if self.part == "3.1":
            for name, service in self.compose_config().get("services", {}).items():
                found[name] = {(None, int(port["published"])) for port in service.get("ports", [])
                               if str(port.get("published", "")).isdigit()}
            return found
        for deployment in deployments(self):
            reached = set()
            for service in services_for(self, deployment):
                kind = service["spec"].get("type")
                for port in service["spec"].get("ports", []):
                    if kind in ("NodePort", "LoadBalancer") and port.get("nodePort"):
                        reached.add((None, port["nodePort"]))
                    if kind == "LoadBalancer":
                        for ingress in service.get("status", {}).get("loadBalancer", {}).get("ingress") or []:
                            reached.add((ingress.get("ip") or ingress.get("hostname"), port.get("port")))
            found[deployment["metadata"]["name"]] = reached
        return found

    def shortener_names(self):
        names = [name for name, role in self.roles().items() if role == "shortener"]
        if not names:
            self.skip("cannot tell which service is the shortener; pass --shortener-service NAME")
        return names

    # Docker Compose (Part 3.1)

    def compose(self, *arguments, timeout=300):
        if not self.compose_dir:
            self.skip("pass --compose-dir")
        project = ["-p", self.project] if self.project else []
        return self.execute(["docker", "compose", *project, *arguments], timeout=timeout, cwd=self.compose_dir)

    def compose_ps(self):
        """docker compose ps for every container of the project, cached until a restart."""
        if "ps" not in self.shared:
            result = self.compose("ps", "--all", "--format", "json")
            if result.returncode != 0:
                self.skip(f"docker compose ps failed: {shorten(result.stderr, 200)}")
            text = result.stdout.strip()
            if not text.startswith("["):  # one object per line in newer versions
                text = "[" + ",".join(line for line in text.splitlines() if line.strip()) + "]"
            self.shared["ps"] = json.loads(text)
        return self.shared["ps"]

    def compose_config(self):
        if "config" not in self.shared:
            result = self.compose("config", "--format", "json")
            if result.returncode != 0:
                self.skip(f"docker compose config failed: {shorten(result.stderr, 200)}")
            self.shared["config"] = json.loads(result.stdout)
        return self.shared["config"]

    def inspect(self, *names):
        result = self.execute(["docker", "inspect", *names])
        if result.returncode != 0:
            self.skip(f"docker inspect failed: {shorten(result.stderr, 200)}")
        return json.loads(result.stdout)

    def containers(self):
        """Service name -> docker inspect of its container, for the running services."""
        if "containers" not in self.shared:
            running = [entry for entry in self.compose_ps() if entry.get("State") == "running"]
            details = self.inspect(*[entry["ID"] for entry in running]) if running else []
            self.shared["containers"] = {entry["Service"]: detail for entry, detail in zip(running, details)}
        return self.shared["containers"]

    def student_containers(self):
        """The running containers of the services that the students built, or that the audit recognised."""
        built = {name for name, service in self.compose_config().get("services", {}).items() if service.get("build")}
        return {service: container for service, container in self.containers().items()
                if service in built or service in self.roles()}

    # Kubernetes (Part 3.2)

    def kubectl_args(self, *arguments):
        """The kubectl command line; through ssh, the remote shell needs the arguments quoted."""
        if Path(self.kubectl[0]).name == "ssh":
            return self.kubectl + [shlex.quote(argument) for argument in arguments]
        return self.kubectl + list(arguments)

    def kube(self, *arguments, namespaced=True):
        """kubectl ARGUMENTS -o json, in the namespace unless namespaced is False."""
        if namespaced and not self.namespace:
            self.skip("pass --namespace")
        result = self.execute(self.kubectl_args(*arguments, *(["-n", self.namespace] if namespaced else []),
                                                "-o", "json"), timeout=120)
        if result.returncode != 0:
            self.skip(f"kubectl {' '.join(arguments)} failed: {shorten(result.stderr, 200)}")
        return json.loads(result.stdout)

    def items(self, kind, namespaced=True):
        """The objects of one kind, cached until a restart."""
        key = ("items", kind, namespaced)
        if key not in self.shared:
            self.shared[key] = self.kube("get", kind, namespaced=namespaced).get("items", [])
        return self.shared[key]

    def logs(self, pod, *options):
        result = self.execute(self.kubectl_args("logs", pod, "-n", self.namespace, "--all-containers", *options),
                              timeout=120)
        return result.stdout if result.returncode == 0 else ""

    def wait_until_up(self, seconds=180):
        """Wait until both services answer five times in a row after a restart.

        A proxy or load balancer answers 502, 503 or 504 while the service
        behind it starts; those answers do not count.
        """
        deadline = time.monotonic() + seconds
        for url in (self.auth.base_url + "/users/login", self.public.base_url + "/"):
            answers = 0
            while answers < 5:
                try:
                    up = requests.get(url, timeout=(5, 10)).status_code not in (502, 503, 504)
                except requests.RequestException:
                    up = False
                if up:
                    answers += 1
                    continue
                answers = 0
                if time.monotonic() > deadline:
                    self.problem(f"{url} did not answer within {seconds} s after the restart")
                    return False
                time.sleep(2)
        return True


def port_of(url):
    parts = urlsplit(url)
    return parts.port or (443 if parts.scheme == "https" else 80)


def url_key(url):
    return urlsplit(url).hostname, port_of(url)


def name_words(name):
    return set(re.split(r"[^a-z0-9]+", name.lower())) - {""}


def role_from_name(name):
    words = name_words(name)
    if words & AUXILIARY_WORDS:
        return None
    if words & AUTH_WORDS or any(word.startswith("auth") for word in words):
        return "auth"
    if words & SHORTENER_WORDS or any(word.startswith("short") for word in words):
        return "shortener"
    return None


def reaches(endpoints, target):
    host, port = target
    return (host, port) in endpoints or (None, port) in endpoints


def assign_roles(named, endpoints, targets):
    """Name -> role: as named on the command line, else by the URL that reaches it, else by its name.

    The URLs decide only when they differ, and not for something that both
    reach (a proxy in front of both services).
    """
    roles = {name: role for role, name in named.items() if name}
    if targets["shortener"] != targets["auth"]:
        for role, target in targets.items():
            if role in roles.values():
                continue
            owners = [name for name, reached in endpoints.items() if name not in roles and reaches(reached, target)
                      and not all(reaches(reached, other) for other in targets.values())]
            if len(owners) == 1:
                roles[owners[0]] = role
    for name in endpoints:
        role = role_from_name(name)
        if name not in roles and role and role not in roles.values():
            roles[name] = role
    return roles


def inside(path, folder):
    path, folder = PurePosixPath("/" + path), PurePosixPath("/" + folder)
    return path == folder or folder in path.parents


def overlapping(first, second):
    """Whether two places (kind, volume, folder) share files: same volume, one folder inside the other."""
    return first[:2] == second[:2] and (inside(first[2], second[2]) or inside(second[2], first[2]))


def shared_places(places):
    """(owner, other owner, place) for each place that two owners can both write."""
    found = []
    for index, (owner, place) in enumerate(places):
        for other, other_place in places[index + 1:]:
            if owner != other and overlapping(place, other_place):
                found.append((owner, other, min(place, other_place, key=lambda item: len(item[2]))))
    return found


def register_and_login(ctx, label, setup=False):
    """A user with a token, or None after recording the problem.

    With setup=True, the check only needs the user to test something else:
    it is skipped instead, and COMPOSE-03 or K8S-09 reports the problem.
    """
    report = ctx.skip if setup else ctx.problem
    user = ctx.new_user(label)
    response = ctx.register(user)
    if response.status not in (200, 201):
        report(f"POST /users: expected 201, got {response.status}: {shorten(response.exchange, 200)}")
        return None
    response, token = ctx.login(user)
    if not token:
        report(f"POST /users/login: expected 200 and a token, got {response.status}: {shorten(response.exchange, 200)}")
        return None
    try:
        ctx.detect_token_style(token)
    except Exception:
        response = ctx.public.get("/", headers=ctx.headers(token))
        if setup:
            ctx.skip(f"the shortener refuses a fresh token: {shorten(response.exchange, 200)}")
        ctx.problem("the shortener refuses a fresh token in every usual header: does it have the public key "
                    "that belongs to the authentication service's private key? (If it expects another header, "
                    "pass --token-header.)", response)
        return None
    return user


def services_work(ctx):
    """Accounts, tokens and mappings through the given URLs."""
    alice = register_and_login(ctx, "alice")
    bob = alice and register_and_login(ctx, "bob")
    if not bob:
        return
    url = ctx.url("works")
    response = ctx.client(alice).post("/", {"value": url})
    short_id = returned_id(response) if response.status == 201 else None
    if not short_id:
        ctx.problem(f"POST /: expected 201 and an id, got {response.status}", response)
        return
    path = "/" + quote(short_id, safe="")
    response = ctx.follow(short_id, alice)
    if not gives_url(response, url):
        ctx.problem(f"GET /:id: expected 301 to the URL, got {response.status}", response)
    new_url = ctx.url("works-updated")
    response = ctx.client(alice).put(path, {"url": new_url})
    if response.status != 200 or not gives_url(ctx.follow(short_id, alice), new_url):
        ctx.problem(f"PUT /:id: expected 200 and the new URL, got {response.status}", response)
    keys, response = ctx.listed_for(alice)
    if short_id not in keys:
        ctx.problem("GET / does not list the user's mapping", response)
    response = ctx.client(bob).delete(path)
    if response.ok:
        ctx.problem("another user deleted the mapping", response)
    response = ctx.client(alice).delete(path)
    if response.status != 204:
        ctx.problem(f"DELETE /:id: expected 204, got {response.status}", response)


def survives(ctx, restart, label):
    """Create an account and a mapping, restart with restart(), check that both still work."""
    if not ctx.allow_restart:
        ctx.skip("pass --allow-restart to let the audit restart the services")
    ctx.need_services()
    user = register_and_login(ctx, "persist", setup=True)
    url = ctx.url("persist-" + uuid.uuid4().hex[:6])
    response = ctx.client(user).post("/", {"value": url})
    short_id = returned_id(response) if response.status == 201 else None
    if not short_id:
        ctx.skip(f"POST / did not create a mapping: {shorten(response.exchange, 200)}")
    if not restart() or not ctx.wait_until_up():
        return
    response = ctx.follow(short_id, user)
    if not gives_url(response, url):
        ctx.problem(f"after {label}, GET /:id no longer leads to the URL ({response.status})", response)
    response, token = ctx.login(user)
    if not token:
        ctx.problem(f"after {label}, the account no longer logs in ({response.status})", response)
        return
    keys, response = ctx.listed_for(user)
    if response.status != 200:
        ctx.problem(f"after {label}, the shortener refuses a new token ({response.status}): "
                    "do both services still use the same key pair?", response)
    elif short_id not in keys:
        ctx.problem(f"after {label}, GET / no longer lists the user's mapping", response)


# Images and containers


def new_scan():
    return {"keys": set(), "clutter": {}, "bytes": 0}


def scan_tar(tar, scan):
    """Add to scan the files of a tar archive that hold a private key, unneeded folders and the bytes."""
    for entry in tar:
        name = re.sub(r"^(\./|/)+", "", entry.name)
        if not entry.isfile() or PurePosixPath(name).name.startswith(".wh."):  # .wh. files mark deletions
            continue
        scan["bytes"] += entry.size
        system = name.startswith(SYSTEM_FOLDERS)
        for pattern, label, in_system_folders in CLUTTER:
            match = pattern.match("/" + name)
            if match and (in_system_folders or not system):
                scan["clutter"].setdefault(label, set()).add(match.group(1))
        if entry.size > 2000000 or NOT_KEY_FILES.search("/" + name):
            continue
        stream = tar.extractfile(entry)
        if stream is not None and holds_private_key(stream.read()):
            scan["keys"].add("/" + name)


def image_of(container):
    """The image name of a container, for the report (the scans use its id)."""
    return container["Config"].get("Image") or container["Image"]


def scan_image(ctx, image):
    """{"keys": files, "clutter": {what: folders}, "bytes": size of all files} over all layers of an image.

    Every layer counts: a file that a later layer deletes is still in the
    image that docker push uploads.
    """
    scans = ctx.shared.setdefault("image scans", {})
    if image not in scans:
        scan = new_scan()
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "image.tar"
            result = ctx.execute(["docker", "save", "-o", str(archive), image], timeout=900)
            if result.returncode != 0:
                ctx.skip(f"docker save {image} failed: {shorten(result.stderr, 200)}")
            with tarfile.open(archive) as outer:
                for member in outer:
                    if not member.isfile() or member.size < 512:
                        continue
                    try:
                        with tarfile.open(fileobj=outer.extractfile(member), mode="r:*") as layer:
                            scan_tar(layer, scan)
                    except (tarfile.TarError, EOFError, OSError):
                        continue  # not a layer: a manifest or a configuration
        scan["keys"] = sorted(scan["keys"])
        scans[image] = scan
    return scans[image]


def keys_in_container(container, path):
    """Files under path in a running container, volumes included, that hold a private key."""
    scan = new_scan()
    with tempfile.TemporaryDirectory() as folder:
        archive = Path(folder) / "files.tar"
        with open(archive, "wb") as stream:
            result = subprocess.run(["docker", "cp", f"{container}:{path}", "-"], stdout=stream,
                                    stderr=subprocess.PIPE, timeout=300)
        if result.returncode != 0:
            return set()
        with tarfile.open(archive) as tar:
            scan_tar(tar, scan)
    parent = str(PurePosixPath(path).parent).rstrip("/")
    return {parent + name for name in scan["keys"]}


def dockerfiles(ctx):
    """Service name -> (path, instructions) of each service built from a Dockerfile."""
    found = {}
    for name, service in ctx.compose_config().get("services", {}).items():
        build = service.get("build")
        if not build:
            continue
        if isinstance(build, str):
            build = {"context": build}
        context = Path(build.get("context", "."))
        if not context.is_absolute():
            context = ctx.compose_dir / context
        path = context / build.get("dockerfile", "Dockerfile")
        if path.is_file():
            found[name] = (path, instructions(path.read_text(encoding="utf-8-sig", errors="replace")))
    if not found:
        ctx.skip("no service of the project is built from a Dockerfile")
    return found


def instructions(text):
    """The instructions of a Dockerfile, one per line, without comments or line continuations."""
    lines = [line for line in text.splitlines() if not line.strip().startswith("#")]
    joined = re.sub(r"\\[ \t]*\n", " ", "\n".join(lines))
    return [" ".join(line.split()) for line in joined.splitlines() if line.strip()]


def stages(lines):
    """The instructions split into build stages, each starting with FROM."""
    stage = []
    for line in lines:
        if line.split()[0].upper() == "FROM" and stage:
            yield stage
            stage = []
        stage.append(line)
    if stage:
        yield stage


def final_base(lines):
    """The image the last stage starts from, following stage names (FROM build AS final)."""
    names, image = {}, ""
    for line in lines:
        words = line.split()
        if words[0].upper() != "FROM":
            continue
        words = [word for word in words[1:] if not word.startswith("--")]
        if not words:
            continue
        image = names.get(words[0].lower(), words[0])
        if len(words) >= 3 and words[1].upper() == "AS":
            names[words[2].lower()] = image
    return image


def writable_mounts(container):
    return [mount for mount in container.get("Mounts", [])
            if mount.get("Type") in ("volume", "bind") and mount.get("RW")]


def compose_place(mount):
    if mount["Type"] == "volume":
        return ("volume", mount.get("Name", ""), "")
    return ("folder", "", mount.get("Source", ""))


@check_31("COMPOSE-01", "Containers", "Both services run in containers",
          why="Assignment 3.1: deploy the services with Docker Compose.",
          ask="Show docker compose ps. What does each container run?")
def compose_running(ctx):
    ps = ctx.compose_ps()
    running = [entry["Service"] for entry in ps if entry.get("State") == "running"]
    # A one-off container that finished its job (creating keys, for example) is fine.
    stopped = [f"{entry['Service']} ({entry.get('Status') or entry.get('State')})" for entry in ps
               if entry.get("State") != "running"
               and not (entry.get("State") == "exited" and entry.get("ExitCode") == 0)]
    if len(running) < 2:
        ctx.problem(f"running services: {running}")
    if stopped:
        ctx.problem(f"services that are not running: {stopped}")


@check_31("COMPOSE-02", "Containers", "The services' published ports listen on all interfaces",
          why="Assignment 3.1: the services must be accessible from outside the machine, not just from within "
              "the Docker container.", ask="From which machines can your services be reached?")
def compose_published(ctx):
    ports = {port_of(ctx.public.base_url), port_of(ctx.auth.base_url)}
    publishers = [(entry["Service"], publisher) for entry in ctx.compose_ps()
                  for publisher in entry.get("Publishers") or [] if publisher.get("PublishedPort") in ports]
    if not publishers:
        ctx.skip(f"no container publishes port {' or '.join(map(str, sorted(ports)))} (host network?)")
    for service, publisher in publishers:
        if publisher.get("URL") in ("127.0.0.1", "::1", "localhost"):
            ctx.problem(f"{service}: port {publisher['PublishedPort']} is published on {publisher['URL']} only")


@check_31("COMPOSE-03", "Containers", "The services work in their containers",
          why="Assignment 3.1: the services must still work when they run with Docker.",
          ask="Show a few requests to both services.")
def compose_works(ctx):
    if ctx.unreachable:
        ctx.problem(f"the services do not answer: {ctx.unreachable}")
        for line in ctx.compose("logs", "--no-color").stdout.splitlines():
            if re.search(r"Running on http://(127\.0\.0\.1|localhost)", line):
                ctx.problem(f"{line.strip()}: inside its container the service listens on 127.0.0.1 only, so "
                            "the published port cannot reach it")
                break
        return
    services_work(ctx)


@check_31("COMPOSE-04", "Persistence", "The data is kept in named volumes or folders of the host", severity="WARN",
          why="Assignment 3.1: write the data to a file and keep it in a Docker volume. Data written inside a "
              "container, or in an anonymous volume, is lost when docker compose down removes the container.",
          ask="Where do your services write their data, and what keeps it?")
def compose_volumes(ctx):
    containers = ctx.containers()
    kept = False
    for service, container in containers.items():
        for mount in writable_mounts(container):
            if mount["Type"] == "volume" and ANONYMOUS_VOLUME.fullmatch(mount.get("Name", "")):
                ctx.problem(f"{service}: {mount['Destination']} is an anonymous volume, which docker compose "
                            "down leaves behind and up does not use again")
            else:
                kept = True
    if containers and not kept:
        ctx.problem("no service mounts a named volume or a folder of the host for its data")


@check_31("COMPOSE-05", "Security", "The services do not share a writable data folder", severity="WARN",
          why="If the shortener can write the authentication service's data, it can change a password hash and "
              "log in as anyone.", ask="Can the shortener read or change the accounts?")
def compose_shared_data(ctx):
    containers = ctx.containers()
    auth = {name for name, role in ctx.roles().items() if role == "auth"}
    places = [(service, compose_place(mount)) for service, container in containers.items()
              for mount in writable_mounts(container)]
    for first, second, place in shared_places(places):
        if not auth or auth & {first, second}:
            ctx.problem(f"{first} and {second} both write {place[0]} {place[1] or place[2]}")


@check_31("COMPOSE-06", "Security", "The shortener's container cannot read the private key",
          why="Assignment 2 and 3: the signing key stays in the authentication service. With the private key, "
              "the shortener (or whoever breaks into it) can sign tokens for any user.",
          ask="Which key files does each container see, and why?")
def compose_shortener_key(ctx):
    containers = ctx.containers()
    for service in ctx.shortener_names():
        container = containers.get(service)
        if container is None:
            ctx.skip(f"{service} is not running, see COMPOSE-01")
        for variable in container["Config"].get("Env") or []:
            if holds_private_key(variable):
                ctx.problem(f"{service}: the environment variable {variable.split('=')[0]} holds a private key")
        for mount in container.get("Mounts", []):
            for path in sorted(keys_in_container(container["Id"], mount["Destination"])):
                ctx.problem(f"{service}: {path} (mounted from {mount.get('Name') or mount.get('Source')})")


def role_images(ctx, shortener):
    """(service, image name, image id) of the shortener, or of the other services the students built."""
    shorteners = set(ctx.shortener_names())
    return [(service, image_of(container), container["Image"])
            for service, container in ctx.student_containers().items() if (service in shorteners) == shortener]


@check_31("IMAGE-01", "Images", "The shortener image holds no private key",
          why="Assignment 2 and 3: the signing key stays in the authentication service. A key in any layer of "
              "the shortener image, even one that a later layer deletes, lets anyone with the image sign tokens.",
          ask="How do the keys get into your containers?")
def image_shortener_key(ctx):
    for service, name, image in role_images(ctx, shortener=True):
        for path in scan_image(ctx, image)["keys"]:
            ctx.problem(f"{service} image {name}: {path}")


@check_31("IMAGE-02", "Images", "The other images hold no private key", severity="WARN",
          why="A key built into an image is readable by anyone who can pull the image, and in Part 3.2 the images "
              "go to a registry. Mount the key instead (a volume, a Kubernetes Secret).",
          ask="Where does the authentication container get its key? Who can download your image?")
def image_auth_key(ctx):
    for service, name, image in role_images(ctx, shortener=False):
        for path in scan_image(ctx, image)["keys"]:
            ctx.problem(f"{service} image {name}: {path}")


@check_31("IMAGE-03", "Images", "The images are small", severity="WARN",
          why="Assignment 3.1: make the containers as efficient as possible. A python:3.x-slim image with Flask "
              "and cryptography holds about 150-200 MB of files.", ask="What did you do to keep the images small?")
def image_size(ctx):
    for service, container in ctx.student_containers().items():
        size = scan_image(ctx, container["Image"])["bytes"] / 1e6
        if size > 400:
            ctx.problem(f"{service}: {size:.0f} MB of files in its layers")


@check_31("IMAGE-04", "Images", "The images start from a slim base image", severity="WARN",
          why="A full python:3 image is several hundred MB larger than python:3-slim, and a general base such "
              "as ubuntu needs Python and its tools installed on top.", ask="Why this base image?")
def image_base(ctx):
    for service, (path, lines) in dockerfiles(ctx).items():
        base = final_base(lines)
        if base and not re.search(r"slim|alpine|distroless|scratch|chainguard|wolfi", base, re.IGNORECASE):
            ctx.problem(f"{service}: FROM {base} ({relative(ctx, path)})")


@check_31("IMAGE-05", "Images", "The dependencies are installed before the code is copied", severity="WARN",
          why="Assignment 3.1: pay attention to the ordering of your commands. Copying the code first invalidates "
              "the dependency layer on every code change, so every build installs all packages again.",
          ask="What happens to your build when you change one line of code?")
def image_order(ctx):
    for service, (path, lines) in dockerfiles(ctx).items():
        for stage in stages(lines):
            installs = [index for index, line in enumerate(stage) if line.split()[0].upper() == "RUN"
                        and re.search(r"\bpip3?\s+install|-m\s+pip\s+install|\buv\s+pip\s+install", line)]
            installs = [index for index in installs if re.search(r"requirements|-r\s", stage[index])] or installs[:1]
            early = [line for index in installs[:1] for line in stage[:index]
                     if line.split()[0].upper() in ("COPY", "ADD") and "--from" not in line
                     and not re.search(r"requirements|pyproject\.toml|poetry\.lock|uv\.lock|Pipfile|setup\.(py|cfg)",
                                       line)]
            if early:
                ctx.problem(f"{service}: '{early[0]}' comes before '{stage[installs[0]]}' ({relative(ctx, path)})")


@check_31("IMAGE-06", "Images", "The images hold no files the service does not need", severity="WARN",
          why="Assignment 3.1: include the minimum number of dependencies and source files. Caches, virtual "
              "environments and repositories make the image larger and may leak files; a .dockerignore and pip's "
              "--no-cache-dir keep them out.",
          ask="What is in your build context, and what ends up in the image?")
def image_clutter(ctx):
    for service, container in ctx.student_containers().items():
        config = container.get("Config") or {}
        # A virtual environment that the environment (PATH, PYTHONPATH) or the
        # command refers to is used, not clutter: built in an earlier stage, say.
        words = set(re.split(r"[\s:=,]+", " ".join(
            (config.get("Env") or []) + (config.get("Entrypoint") or []) + (config.get("Cmd") or []))))
        for label, folders in sorted(scan_image(ctx, container["Image"])["clutter"].items()):
            folders = sorted(folder for folder in folders
                             if folder not in words and not any(word.startswith(folder + "/") for word in words))
            if folders:
                more = f" and {len(folders) - 3} more" if len(folders) > 3 else ""
                ctx.problem(f"{service}: {label}: {', '.join(folders[:3])}{more}")


@check_31("IMAGE-07", "Images", "Flask's debugger is not running in the containers", severity="WARN",
          why="With debug mode on, the Werkzeug debugger lets anyone who triggers an error run code in the "
              "container; reachable from other machines, that is a remote code execution hole.",
          ask="Why does the container run in debug mode?")
def image_debugger(ctx):
    result = ctx.compose("logs", "--no-color")
    for line in result.stdout.splitlines():
        if "Debugger is active" in line:
            ctx.problem(line.strip())


@check_31("IMAGE-08", "Images", "Observations on the images", severity="INFO")
def image_observations(ctx):
    for service, container in ctx.student_containers().items():
        details = ctx.inspect(container["Image"])[0]
        config = details.get("Config") or {}
        layers = len(details.get("RootFS", {}).get("Layers", []))
        size = scan_image(ctx, container["Image"])["bytes"] / 1e6
        ctx.observe(f"{service} ({ctx.roles().get(service, 'role unknown')}): image {image_of(container)}, "
                    f"{size:.0f} MB of files in {layers} layers, user {config.get('User') or 'root'}, "
                    f"workdir {config.get('WorkingDir') or '/'}, "
                    f"command {(config.get('Entrypoint') or []) + (config.get('Cmd') or [])}")
    try:
        for service, (path, lines) in dockerfiles(ctx).items():
            ctx.observe(f"{service}: {relative(ctx, path)}: " + " | ".join(lines))
    except Exception:  # no Dockerfile: nothing more to show
        pass


@check_31("COMPOSE-07", "Persistence", "Accounts and mappings survive docker compose restart",
          why="Assignment 3.1: the services must keep their data across restarts.",
          ask="Where do your services write their data?")
def compose_restart(ctx):
    survives(ctx, compose_restarter(ctx, ("restart",)), "docker compose restart")


@check_31("COMPOSE-08", "Persistence", "Accounts and mappings survive docker compose down and up",
          why="Assignment 3.1: the data must also survive docker compose down, which removes the containers "
              "(but not the named volumes, unlike down -v).",
          ask="Which volume keeps the data, and what does docker compose down -v do?")
def compose_down_up(ctx):
    survives(ctx, compose_restarter(ctx, ("down",), ("up", "-d")), "docker compose down and up")


def compose_restarter(ctx, *commands):
    def restart():
        for command in commands:
            started = time.monotonic()
            result = ctx.compose(*command, timeout=600)
            if result.returncode != 0:
                ctx.problem(f"docker compose {' '.join(command)} failed: {shorten(result.stderr, 200)}")
                return False
            ctx.shared.setdefault("timings", []).append((" ".join(command), time.monotonic() - started))
        for key in ("ps", "containers"):
            ctx.shared.pop(key, None)
        return True
    return restart


@check_31("COMPOSE-09", "Containers", "Observations on the Compose project", severity="INFO")
def compose_observations(ctx):
    for name, service in ctx.compose_config().get("services", {}).items():
        ports = [f"{port.get('host_ip') or '*'}:{port.get('published')}->{port.get('target')}"
                 for port in service.get("ports", [])]
        volumes = [f"{relative(ctx, volume.get('source', '(anonymous)'))}:{volume.get('target')}"
                   f"{':ro' if volume.get('read_only') else ''}" for volume in service.get("volumes", [])]
        ctx.observe(f"{name} ({ctx.roles().get(name, 'role unknown')}): ports {ports}, volumes {volumes}, "
                    f"restart {service.get('restart', 'no')}, environment {sorted(service.get('environment') or {})}")
    timings = ctx.shared.get("timings", [])
    for command, seconds in timings:
        ctx.observe(f"docker compose {command} took {seconds:.0f} s")
    if any(seconds >= 9 for command, seconds in timings if command in ("restart", "down")):
        ctx.observe("stopping took 10 s or more: the services ignore SIGTERM, so Docker kills them after 10 s")


def relative(ctx, path):
    """path relative to the Compose folder, if it is inside it."""
    try:
        return "./" + str(Path(path).relative_to(ctx.compose_dir))
    except ValueError:
        return str(path)


# Kubernetes


def deployments(ctx):
    return ctx.items("deployments")


def ready(deployment):
    return deployment.get("status", {}).get("readyReplicas", 0) or 0


def replicated(ctx):
    return [deployment for deployment in deployments(ctx) if ready(deployment) >= 2]


def services_for(ctx, deployment):
    labels = deployment["spec"]["template"]["metadata"].get("labels", {})
    return [service for service in ctx.items("services")
            if service["spec"].get("selector")
            and all(labels.get(key) == value for key, value in service["spec"]["selector"].items())]


def pods_of(ctx, deployment):
    labels = deployment["spec"]["selector"].get("matchLabels", {})
    return [pod for pod in ctx.items("pods")
            if all(pod["metadata"].get("labels", {}).get(key) == value for key, value in labels.items())]


def shortener_deployments(ctx):
    names = set(ctx.shortener_names())
    return [deployment for deployment in deployments(ctx) if deployment["metadata"]["name"] in names]


def api_deployments(ctx):
    """The Deployments of the two services: those recognised, or else all that are not a database or proxy."""
    roles = ctx.roles()
    found = [deployment for deployment in deployments(ctx) if deployment["metadata"]["name"] in roles]
    return found or [deployment for deployment in deployments(ctx)
                     if not name_words(deployment["metadata"]["name"]) & AUXILIARY_WORDS]


def persistent_volumes(ctx):
    if "persistent volumes" not in ctx.shared:
        try:
            ctx.shared["persistent volumes"] = ctx.items("persistentvolumes", namespaced=False)
        except Exception:  # not allowed to list cluster objects
            ctx.shared["persistent volumes"] = []
    return ctx.shared["persistent volumes"]


def data_places(ctx, deployment):
    """(kind, volume, folder) of each writable volume the pods mount, following claims to their volumes."""
    claims = {claim["metadata"]["name"]: claim for claim in ctx.items("persistentvolumeclaims")}
    spec = deployment["spec"]["template"]["spec"]
    volumes = {volume["name"]: volume for volume in spec.get("volumes", [])}
    places = []
    for container in spec.get("containers", []):
        for mount in container.get("volumeMounts", []):
            volume = volumes.get(mount["name"], {})
            kind = next((key for key in volume if key != "name"), None)
            if kind is None or kind in READ_ONLY_VOLUMES or mount.get("readOnly"):
                continue
            sub_path = mount.get("subPath") or mount.get("subPathExpr") or ""
            source = volume[kind] if isinstance(volume[kind], dict) else {}
            if kind == "persistentVolumeClaim":
                bound = claims.get(source.get("claimName"), {}).get("spec", {}).get("volumeName")
                for persistent in persistent_volumes(ctx):
                    if persistent["metadata"]["name"] == bound:
                        found = [key for key in ("nfs", "hostPath", "local") if key in persistent["spec"]]
                        if found:
                            kind, source = found[0], persistent["spec"][found[0]]
            if kind == "nfs":
                places.append((kind, source.get("server", ""), str(PurePosixPath(source.get("path", "/")) / sub_path)))
            elif kind in ("hostPath", "local"):
                places.append(("node folder", "", str(PurePosixPath(source.get("path", "/")) / sub_path)))
            elif kind == "persistentVolumeClaim":
                places.append((kind, source.get("claimName", ""), sub_path))
            else:  # emptyDir and other volume types
                places.append((kind, mount["name"], sub_path))
    return places


def readable_objects(spec):
    """(kind, name, keys) of the Secrets and ConfigMaps the pod's containers can read; keys None means all."""
    containers = spec.get("containers", []) + spec.get("initContainers", [])
    mounted = {mount["name"] for container in containers for mount in container.get("volumeMounts", [])}
    found = []

    def add(kind, name, items=None):
        found.append((kind, name, frozenset(item.get("key") for item in items) if items else None))

    for volume in spec.get("volumes", []):
        if volume["name"] not in mounted:
            continue
        if "secret" in volume:
            add("Secret", volume["secret"].get("secretName"), volume["secret"].get("items"))
        if "configMap" in volume:
            add("ConfigMap", volume["configMap"].get("name"), volume["configMap"].get("items"))
        for source in volume.get("projected", {}).get("sources", []):
            if "secret" in source:
                add("Secret", source["secret"].get("name"), source["secret"].get("items"))
            if "configMap" in source:
                add("ConfigMap", source["configMap"].get("name"), source["configMap"].get("items"))
    for container in containers:
        for variable in container.get("env", []):
            reference = variable.get("valueFrom", {})
            if "secretKeyRef" in reference:
                add("Secret", reference["secretKeyRef"].get("name"), [reference["secretKeyRef"]])
            if "configMapKeyRef" in reference:
                add("ConfigMap", reference["configMapKeyRef"].get("name"), [reference["configMapKeyRef"]])
        for source in container.get("envFrom", []):
            if "secretRef" in source:
                add("Secret", source["secretRef"].get("name"))
            if "configMapRef" in source:
                add("ConfigMap", source["configMapRef"].get("name"))
    return found


def object_values(ctx, kind, name):
    """key -> text of a Secret or ConfigMap."""
    for item in ctx.items("secrets" if kind == "Secret" else "configmaps"):
        if item["metadata"]["name"] == name:
            encoded = (item.get("data") if kind == "Secret" else item.get("binaryData")) or {}
            values = {key: base64.b64decode(value).decode("utf-8", "replace") for key, value in encoded.items()}
            if kind == "ConfigMap":
                values.update(item.get("data") or {})
            return values
    return {}


def keys_in_pod_volumes(ctx, deployment):
    """Files with a private key in the volumes (other than Secrets and ConfigMaps) of a running pod."""
    spec = deployment["spec"]["template"]["spec"]
    volumes = {volume["name"]: volume for volume in spec.get("volumes", [])}
    pods = [pod for pod in pods_of(ctx, deployment) if pod["status"].get("phase") == "Running"]
    found = []
    for container in spec.get("containers", []) if pods else []:
        paths = [mount["mountPath"] for mount in container.get("volumeMounts", [])
                 if mount["name"] in volumes and not set(volumes[mount["name"]]) & READ_ONLY_VOLUMES]
        for python in ("python3", "python") if paths else ():
            result = ctx.execute(ctx.kubectl_args("exec", pods[0]["metadata"]["name"], "-n", ctx.namespace,
                                                  "-c", container["name"], "--", python, "-c", SCAN_SCRIPT, *paths),
                                 timeout=180)
            if result.returncode == 0:
                found += [f"{pods[0]['metadata']['name']}:{line.strip()}" for line in result.stdout.splitlines()
                          if line.strip()]
                break
    return found


def registry_images(ctx, shortener):
    """(Deployment, image) of the shortener, or of the other service; pulled if Docker does not have it."""
    names = set(ctx.shortener_names())
    found = []
    for deployment in api_deployments(ctx):
        if (deployment["metadata"]["name"] in names) == shortener:
            for container in deployment["spec"]["template"]["spec"].get("containers", []):
                found.append((deployment["metadata"]["name"], container["image"]))
    for _, image in found:
        if ctx.execute(["docker", "image", "inspect", image]).returncode != 0:
            nodes = ctx.items("nodes", namespaced=False)
            platform = "linux/" + (nodes[0]["status"]["nodeInfo"]["architecture"] if nodes else "amd64")
            result = ctx.execute(["docker", "pull", "--platform", platform, image], timeout=900)
            if result.returncode != 0:
                ctx.skip(f"docker pull {image} failed: {shorten(result.stderr, 200)}")
            ctx.shared.setdefault("pulled images", []).append(image)
    return found


@check_32("K8S-01", "Cluster", "The cluster has at least three nodes, all Ready",
          why="Assignment 3.2: a cluster on three VMs, one control plane and two workers.",
          ask="Show kubectl get nodes. How did you set up the cluster?")
def k8s_nodes(ctx):
    nodes = ctx.items("nodes", namespaced=False)
    not_ready = [node["metadata"]["name"] for node in nodes
                 if not any(condition["type"] == "Ready" and condition["status"] == "True"
                            for condition in node["status"].get("conditions", []))]
    if len(nodes) < 3:
        ctx.problem(f"{len(nodes)} nodes: {[node['metadata']['name'] for node in nodes]}")
    if not_ready:
        ctx.problem(f"not Ready: {not_ready}")


@check_32("K8S-02", "Cluster", "One control plane and at least two workers", severity="WARN",
          why="Assignment 3.2 uses one VM as the control plane and two as workers.", ask="Which node has which role?")
def k8s_roles(ctx):
    nodes = ctx.items("nodes", namespaced=False)
    control = [node["metadata"]["name"] for node in nodes
               if {"node-role.kubernetes.io/control-plane", "node-role.kubernetes.io/master"}
               & set(node["metadata"].get("labels", {}))]
    workers = [node["metadata"]["name"] for node in nodes if node["metadata"]["name"] not in control]
    if len(control) != 1 or len(workers) < 2:
        ctx.problem(f"control plane: {control}; workers: {workers}")


@check_32("K8S-03", "Cluster", "The system pods are running", severity="WARN",
          why="A failing network plugin, DNS or kube-proxy pod breaks Services in ways that are hard to see.",
          ask="Which network plugin do you use? Why does this pod fail?")
def k8s_system_pods(ctx):
    for pod in ctx.kube("get", "pods", "--all-namespaces", namespaced=False).get("items", []):
        namespace, phase = pod["metadata"]["namespace"], pod["status"].get("phase")
        if not SYSTEM_NAMESPACES.search(namespace) or phase == "Succeeded":
            continue
        waiting = [status["state"]["waiting"].get("reason", "waiting")
                   for status in pod["status"].get("containerStatuses", []) if status.get("state", {}).get("waiting")]
        if phase != "Running" or waiting:
            reasons = f" ({', '.join(waiting)})" if waiting else ""
            ctx.problem(f"{namespace}/{pod['metadata']['name']}: {phase}{reasons}")


@check_32("K8S-04", "Deployments", "A Deployment for each service, with all replicas ready",
          why="Assignment 3.2: create Deployments for your services.", ask="Show your Deployment files.")
def k8s_deployments(ctx):
    items = deployments(ctx)
    if len(items) < 2:
        ctx.problem(f"{len(items)} Deployments in {ctx.namespace}: {[d['metadata']['name'] for d in items]}")
    for deployment in items:
        wanted = deployment["spec"].get("replicas", 1)
        if ready(deployment) < wanted:
            ctx.problem(f"{deployment['metadata']['name']}: {ready(deployment)} of {wanted} replicas ready")


@check_32("K8S-05", "Deployments", "At least one service runs three or more replicas",
          why="Assignment 3.2: at least one of the services must run with 3 replicas.",
          ask="Which service did you replicate, and why that one?")
def k8s_three_replicas(ctx):
    counts = {deployment["metadata"]["name"]: ready(deployment) for deployment in api_deployments(ctx)}
    if not any(count >= 3 for count in counts.values()):
        ctx.problem(f"ready replicas: {counts}")


@check_32("K8S-06", "Deployments", "The replicas run on more than one node", severity="WARN",
          why="Replicas on one node do not survive the loss of that node and leave the workers unused.",
          ask="On which nodes do the replicas run, and why?")
def k8s_spread(ctx):
    for deployment in replicated(ctx):
        nodes = {pod["spec"].get("nodeName") for pod in pods_of(ctx, deployment)
                 if pod["status"].get("phase") == "Running"}
        if len(nodes) < 2:
            ctx.problem(f"{deployment['metadata']['name']}: all replicas on {sorted(filter(None, nodes))}")


@check_32("K8S-07", "Services", "Each service has a Service with an endpoint for every ready pod",
          why="Assignment 3.2: create Services for your services. A selector that misses pods sends them no "
              "traffic.", ask="Show your Service files. How does a Service find its pods?")
def k8s_services(ctx):
    slices = ctx.items("endpointslices")
    api = {deployment["metadata"]["name"] for deployment in api_deployments(ctx)}
    for deployment in deployments(ctx):
        services = services_for(ctx, deployment)
        if not services and deployment["metadata"]["name"] in api:
            ctx.problem(f"no Service selects the pods of {deployment['metadata']['name']}")
        for service in services:
            name = service["metadata"]["name"]
            endpoints = sum(1 for item in slices
                            if item["metadata"].get("labels", {}).get("kubernetes.io/service-name") == name
                            for endpoint in item.get("endpoints") or []
                            if endpoint.get("conditions", {}).get("ready") is not False)
            if endpoints < ready(deployment):
                ctx.problem(f"Service {name}: {endpoints} ready endpoints for {ready(deployment)} ready pods")


@check_32("K8S-08", "Services", "The services are reachable from outside the cluster",
          why="Assignment 3.2: create Services that make the services externally accessible (a NodePort or "
              "LoadBalancer Service, or an Ingress or proxy in front of them), and think about the best kind.",
          ask="Why this Service type? How do you reach it from your computer?")
def k8s_exposed(ctx):
    backends = set()
    result = ctx.execute(ctx.kubectl_args("get", "ingress", "-n", ctx.namespace, "-o", "json"))
    for ingress in json.loads(result.stdout or "{}").get("items", []) if result.returncode == 0 else []:
        spec = ingress.get("spec", {})
        backends.add((spec.get("defaultBackend") or {}).get("service", {}).get("name"))
        for rule in spec.get("rules") or []:
            for path in (rule.get("http") or {}).get("paths") or []:
                backends.add(path.get("backend", {}).get("service", {}).get("name"))
    exposed = set().union(*ctx.endpoints().values()) if ctx.endpoints() else set()
    targets = {"shortener": url_key(ctx.public.base_url), "auth": url_key(ctx.auth.base_url)}
    roles = ctx.roles()
    for deployment in api_deployments(ctx):
        name = deployment["metadata"]["name"]
        services = services_for(ctx, deployment)
        types = {service["spec"].get("type", "ClusterIP") for service in services}
        if types & {"NodePort", "LoadBalancer"} or {service["metadata"]["name"] for service in services} & backends:
            continue
        role = roles.get(name)
        if role and not ctx.unreachable and reaches(exposed, targets[role]):
            continue  # a proxy with a node port answers on its URL
        ctx.problem(f"{name}: Service types {sorted(types) or 'none'}, no Ingress and no proxy leads to it")


@check_32("K8S-09", "Services", "The services work through the given URLs",
          why="Assignment 3.2: the services must work when accessed from outside the cluster.",
          ask="Which address and port do you use from your computer?")
def k8s_works(ctx):
    if ctx.unreachable:
        ctx.problem(f"the services do not answer through the given URLs: {ctx.unreachable}")
        return
    services_work(ctx)


@check_32("K8S-10", "Replicas", "Every shortener replica gives the same data",
          why="Assignment 3.2: the replicas must offer a consistent view of the stored data.",
          ask="Where do the replicas keep their data? How does one replica see another's changes?")
def k8s_consistent(ctx):
    ctx.need_services()
    user = register_and_login(ctx, "replicas", setup=True)
    urls = [ctx.url(f"replicas-{number}") for number in range(5)]
    ids = []
    for url in urls:
        response = ctx.client(user).post("/", {"value": url})
        if response.status != 201 or not returned_id(response):
            ctx.problem(f"POST /: expected 201, got {response.status}", response)
            return
        ids.append(returned_id(response))
    for number in range(60):
        response = ctx.follow(ids[number % 5], user)
        if not gives_url(response, urls[number % 5]):
            ctx.problem(f"request {number + 1} of 60: GET /{ids[number % 5]} gave {response.status}", response)
            break
    for number in range(20):
        keys, response = ctx.listed_for(user)
        missing = set(ids) - keys
        if missing:
            ctx.problem(f"request {number + 1} of 20: GET / misses {sorted(missing)}", response)
            break
    new_url = ctx.url("replicas-updated")
    response = ctx.client(user).put("/" + quote(ids[0], safe=""), {"url": new_url})
    if response.status == 200:
        for number in range(20):
            response = ctx.follow(ids[0], user)
            if not gives_url(response, new_url):
                ctx.problem(f"after PUT, request {number + 1} of 20 did not give the new URL", response)
                break


@check_32("K8S-11", "Replicas", "Every authentication replica knows the same accounts and signs with the same key",
          why="Assignment 3.2: the replicas must offer a consistent view of the stored data, accounts included; and "
              "the shortener must accept the tokens of every replica.",
          ask="Where do the authentication replicas keep the accounts and the signing key?")
def k8s_auth_consistent(ctx):
    ctx.need_services()
    user = ctx.new_user("auth-replicas")
    response = ctx.register(user)
    if response.status not in (200, 201):
        ctx.problem(f"POST /users: expected 201, got {response.status}", response)
        return
    refused = []
    for number in range(20):
        response, token = ctx.login(user)
        if not token:
            ctx.problem(f"login {number + 1} of 20 failed ({response.status})", response)
            return
        if number == 0:
            try:
                ctx.detect_token_style(token)
            except Exception:  # judged below, with the default header
                pass
        listing = ctx.public.get("/", headers=ctx.headers(token))
        if listing.status != 200:
            refused.append(listing)
    if refused:
        ctx.problem(f"the shortener refused {len(refused)} of 20 fresh tokens: do all authentication replicas sign "
                    "with the same private key?", refused[0])
    old, user.password = user.password, "Pw-" + uuid.uuid4().hex[:12]
    response = ctx.change_password(user, old, user.password)
    if response.status != 200:
        ctx.problem(f"PUT /users: expected 200, got {response.status}", response)
        return
    for number in range(20):
        response, token = ctx.login(user)
        if not token:
            ctx.problem(f"after the password change, login {number + 1} of 20 with the new password failed "
                        f"({response.status})", response)
            return
    for number in range(3):  # few wrong passwords, in case the service locks accounts
        response, token = ctx.login(user, old)
        if token:
            ctx.problem(f"after the password change, login {number + 1} of 3 with the old password succeeded",
                        response)
            return


@check_32("K8S-12", "Replicas", "Concurrent writes through the Service", severity="INFO")
def k8s_concurrent(ctx):
    ctx.need_services()
    user = register_and_login(ctx, "concurrent", setup=True)
    urls = [ctx.url(f"concurrent-{number}") for number in range(100)]

    def create(url):
        response = ctx.client(user).post("/", {"value": url})
        return url, returned_id(response) if response.status == 201 else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(create, urls))
    ids = [short_id for _, short_id in results if short_id]
    lost = [url for url, short_id in results
            if short_id and not gives_url(ctx.follow(short_id, user), url)]
    ctx.observe(f"100 concurrent POSTs: {len(ids)} created, {len(ids) - len(set(ids))} duplicate ids, {len(lost)} "
                "that no longer lead to their URL (the assignment lets students assume no races; ask what would "
                "happen)")


@check_32("K8S-13", "Replicas", "How the Service spreads requests over the replicas", severity="INFO")
def k8s_distribution(ctx):
    ctx.need_services()
    marker = f"/audit-{ctx.run}-spread"
    served_by = collections.Counter()
    for _ in range(30):
        served_by[ctx.public.get(marker).headers.get("X-Served-By") or ""] += 1
    logged = collections.Counter()
    for deployment in shortener_deployments(ctx):
        for pod in pods_of(ctx, deployment):
            logged[pod["metadata"]["name"]] = ctx.logs(pod["metadata"]["name"], "--since=10m").count(marker)
    if sum(logged.values()):
        ctx.observe("30 requests, counted in the pod logs: " +
                    ", ".join(f"{name} {count}" for name, count in sorted(logged.items())))
    elif set(served_by) != {""}:
        ctx.observe("30 requests, by X-Served-By: " +
                    ", ".join(f"{name} {count}" for name, count in sorted(served_by.items())))
    else:
        ctx.observe("neither the answers nor the pod logs show which replica served a request")


@check_32("K8S-22", "Replicas", "Requests from one computer can reach every replica", severity="WARN",
          why="With sessionAffinity: ClientIP, or externalTrafficPolicy: Local, all requests from one computer (or "
              "through one node) reach the same pod: then K8S-10 and K8S-11 cannot see whether the other replicas "
              "hold the same data.",
          ask="How do requests reach the replicas? Show that every replica gives the same data.")
def k8s_affinity(ctx):
    for deployment in replicated(ctx):
        for service in services_for(ctx, deployment):
            spec, name = service["spec"], service["metadata"]["name"]
            if spec.get("sessionAffinity") == "ClientIP":
                ctx.problem(f"Service {name} ({deployment['metadata']['name']}): sessionAffinity ClientIP")
            if spec.get("externalTrafficPolicy") == "Local":
                ctx.problem(f"Service {name} ({deployment['metadata']['name']}): externalTrafficPolicy Local, so a "
                            "node port reaches only the replicas on that node")


@check_32("K8S-14", "Security", "No ConfigMap holds a private key", severity="WARN",
          why="ConfigMaps are meant for configuration, not secrets: access to Secrets can be limited separately, "
              "and they are not shown by default. A private key belongs in a Secret.",
          ask="Where is the signing key stored in the cluster?")
def k8s_configmap_keys(ctx):
    for configmap in ctx.items("configmaps"):
        for key, value in object_values(ctx, "ConfigMap", configmap["metadata"]["name"]).items():
            if holds_private_key(value):
                ctx.problem(f"ConfigMap {configmap['metadata']['name']}, key {key}, holds a private key")


@check_32("K8S-15", "Security", "The shortener's pods cannot read the private key",
          why="Assignment 2 and 3: the signing key stays in the authentication service. With the private key, "
              "the shortener (or whoever breaks into it) can sign tokens for any user.",
          ask="Which Secrets, ConfigMaps and volumes does each Deployment use, and why?")
def k8s_shortener_key(ctx):
    for deployment in shortener_deployments(ctx):
        name = deployment["metadata"]["name"]
        spec = deployment["spec"]["template"]["spec"]
        for kind, object_name, keys in readable_objects(spec):
            for key, value in object_values(ctx, kind, object_name).items():
                if (keys is None or key in keys) and holds_private_key(value):
                    ctx.problem(f"{name} can read {kind} {object_name}, key {key}, which holds a private key")
        for container in spec.get("containers", []):
            for variable in container.get("env", []):
                if holds_private_key(variable.get("value") or ""):
                    ctx.problem(f"{name}: the environment variable {variable['name']} holds a private key")
        for path in keys_in_pod_volumes(ctx, deployment):
            ctx.problem(f"{name}: {path} holds a private key (in a mounted volume)")


@check_32("K8S-23", "Security", "The shortener's image in the registry holds no private key",
          why="Assignment 2 and 3: the signing key stays in the authentication service. The registry hands the "
              "image to anyone who pulls it, with every layer.", ask="How do the keys get into your pods?")
def k8s_shortener_image(ctx):
    for name, image in registry_images(ctx, shortener=True):
        for path in scan_image(ctx, image)["keys"]:
            ctx.problem(f"{name} image {image}: {path}")


@check_32("K8S-24", "Security", "The other images in the registry hold no private key", severity="WARN",
          why="A key built into an image goes to the registry with it, readable by anyone who can pull the image. "
              "A Kubernetes Secret keeps it out of the image.", ask="Who can pull your images?")
def k8s_other_images(ctx):
    for name, image in registry_images(ctx, shortener=False):
        for path in scan_image(ctx, image)["keys"]:
            ctx.problem(f"{name} image {image}: {path}")


@check_32("K8S-16", "Security", "The services do not share a writable data folder", severity="WARN",
          why="If the shortener can write the authentication service's data, it can change a password hash and "
              "log in as anyone.", ask="Can the shortener read or change the accounts?")
def k8s_shared_data(ctx):
    auth = {name for name, role in ctx.roles().items() if role == "auth"}
    places = [(deployment["metadata"]["name"], place) for deployment in deployments(ctx)
              for place in data_places(ctx, deployment) if place[0] != "emptyDir"]
    for first, second, place in shared_places(places):
        if not auth or auth & {first, second}:
            ctx.problem(f"{first} and {second} both write {place[0]} {':'.join(filter(None, place[1:]))}")


@check_32("K8S-17", "Replicas", "The replicas keep their data where all of them can reach it", severity="WARN",
          why="emptyDir and hostPath are local to a pod or a node, and a ReadWriteOnce volume can be mounted on "
              "one node only: the replicas then keep separate data or must share one node.",
          ask="Where do the replicas keep their data?")
def k8s_replica_storage(ctx):
    claims = {claim["metadata"]["name"]: claim for claim in ctx.items("persistentvolumeclaims")}
    for deployment in replicated(ctx):
        name = deployment["metadata"]["name"]
        spec = deployment["spec"]["template"]["spec"]
        mounted = collections.defaultdict(list)
        for container in spec.get("containers", []):
            for mount in container.get("volumeMounts", []):
                mounted[mount["name"]].append(mount["mountPath"])
        for volume in spec.get("volumes", []):
            paths = mounted.get(volume["name"], [])
            if not paths or all(any(inside(path, folder) for folder in SCRATCH_FOLDERS) for path in paths):
                continue  # not mounted, or scratch space such as /tmp
            if "emptyDir" in volume:
                ctx.problem(f"{name}: volume {volume['name']} ({', '.join(paths)}) is an emptyDir, which every pod "
                            "has for itself")
            if "hostPath" in volume:
                ctx.problem(f"{name}: volume {volume['name']} is the folder {volume['hostPath'].get('path')} of "
                            "whichever node runs the pod (shared only if every node mounts the same storage there)")
            claim = claims.get(volume.get("persistentVolumeClaim", {}).get("claimName"))
            if claim and "ReadWriteMany" not in claim["spec"].get("accessModes", []):
                ctx.problem(f"{name}: claim {claim['metadata']['name']} is {claim['spec'].get('accessModes')}, "
                            "not ReadWriteMany")


@check_32("K8S-18", "Deployments", "The pods do not restart", severity="WARN",
          why="Restarts point to crashes or failing probes.", ask="Why did this pod restart?")
def k8s_restarts(ctx):
    for pod in ctx.items("pods"):
        for status in pod["status"].get("containerStatuses", []):
            if status.get("restartCount", 0) > 0:
                reason = (status.get("lastState", {}).get("terminated") or {}).get("reason", "")
                ctx.problem(f"{pod['metadata']['name']}/{status['name']}: {status['restartCount']} restarts {reason}")


@check_32("K8S-19", "Deployments", "Flask's debugger is not running in the pods", severity="WARN",
          why="With debug mode on, the Werkzeug debugger lets anyone who triggers an error run code in the pod; "
              "behind a NodePort, that is a remote code execution hole.", ask="Why does the pod run in debug mode?")
def k8s_debugger(ctx):
    for deployment in deployments(ctx):
        for pod in pods_of(ctx, deployment)[:1]:
            if "Debugger is active" in ctx.logs(pod["metadata"]["name"], "--limit-bytes=1000000"):
                ctx.problem(f"{deployment['metadata']['name']}: the log of {pod['metadata']['name']} says "
                            "\"Debugger is active\"")


@check_32("K8S-20", "Deployments", "Observations on the workloads", severity="INFO")
def k8s_observations(ctx):
    context = ctx.execute(ctx.kubectl_args("config", "current-context"))
    ctx.observe(f"kubectl context: {context.stdout.strip() or '?'}")
    for deployment in deployments(ctx):
        spec = deployment["spec"]["template"]["spec"]
        name = deployment["metadata"]["name"]
        for container in spec.get("containers", []):
            probes = [probe for probe in ("readinessProbe", "livenessProbe") if probe in container] or "none"
            ctx.observe(f"{name}/{container['name']}: image {container.get('image')}, "
                        f"pull {container.get('imagePullPolicy', 'default')}, probes {probes}, "
                        f"resources {container.get('resources') or 'none'}")
        places = [":".join(filter(None, place)) for place in data_places(ctx, deployment)]
        nodes = sorted({pod["spec"].get("nodeName") or "?" for pod in pods_of(ctx, deployment)})
        ctx.observe(f"{name} ({ctx.roles().get(name, 'role unknown')}): {ready(deployment)} ready on {nodes}, "
                    f"data {places or 'none'}")
    for service in ctx.items("services"):
        ports = [f"{port.get('port')}->{port.get('targetPort')}"
                 + (f" (node port {port['nodePort']})" if port.get("nodePort") else "")
                 for port in service["spec"].get("ports", [])]
        ctx.observe(f"Service {service['metadata']['name']}: {service['spec'].get('type')} {ports}")


@check_32("K8S-21", "Persistence", "Accounts and mappings survive a rollout restart of the services",
          why="New pods must find the data of the old ones.", ask="What happens to the data when a pod is replaced?")
def k8s_rollout(ctx):
    # Only the two services, and only when ready: a Deployment that is not
    # ready (K8S-04) would never finish its rollout.
    names = [deployment["metadata"]["name"] for deployment in api_deployments(ctx)
             if ready(deployment) and ready(deployment) >= deployment["spec"].get("replicas", 1)]

    def restart():
        for name in names:
            result = ctx.execute(ctx.kubectl_args("rollout", "restart", f"deployment/{name}", "-n", ctx.namespace))
            if result.returncode != 0:
                ctx.problem(f"kubectl rollout restart {name} failed: {shorten(result.stderr, 200)}")
                return False
        for name in names:
            result = ctx.execute(ctx.kubectl_args("rollout", "status", f"deployment/{name}", "-n", ctx.namespace,
                                                  "--timeout=300s"), timeout=330)
            if result.returncode != 0:
                ctx.problem(f"the rollout of {name} did not finish: {shorten(result.stderr or result.stdout, 200)}")
                return False
        # The old pods may still answer while they shut down: wait until they are gone.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and any(pod["metadata"].get("deletionTimestamp")
                                                  for pod in ctx.kube("get", "pods").get("items", [])):
            time.sleep(2)
        for key in [key for key in ctx.shared if isinstance(key, tuple)]:
            del ctx.shared[key]
        return True
    survives(ctx, restart, "kubectl rollout restart")


def main():
    parser = argparse.ArgumentParser(description="TA audit for Assignment 3 (containers and Kubernetes).")
    parser.add_argument("--part", choices=("3.1", "3.2"), required=True)
    parser.add_argument("--url", default="http://127.0.0.1:5000", help="URL shortener (default: %(default)s)")
    parser.add_argument("--auth-url", default="http://127.0.0.1:5001",
                        help="authentication service (default: %(default)s)")
    parser.add_argument("--compose-dir", metavar="DIR", help="3.1: the folder with the students' Compose file")
    parser.add_argument("--project", help="3.1: the Compose project name, if the students used -p")
    parser.add_argument("--namespace", help="3.2: the namespace of the students' Deployments")
    parser.add_argument("--kubectl", default="kubectl",
                        help="3.2: the kubectl command, e.g. 'ssh USER@VM kubectl' (default: %(default)s)")
    parser.add_argument("--shortener-service", metavar="NAME",
                        help="the shortener's Compose service (3.1) or Deployment (3.2), if not recognised")
    parser.add_argument("--auth-service", metavar="NAME",
                        help="the authentication service's Compose service or Deployment, if not recognised")
    parser.add_argument("--allow-restart", action="store_true",
                        help="let the audit restart the services to check that the data survives")
    parser.add_argument("--token-header", metavar="'NAME: FORMAT'",
                        help="how to send the token, e.g. 'Authorization: Bearer {token}' (default: detected)")
    parser.add_argument("--report", metavar="FILE.md", help="also write the findings to a Markdown file")
    parser.add_argument("--only", nargs="*", help="run only checks whose id starts with these, e.g. A3-IMAGE")
    parser.add_argument("-v", "--verbose", action="store_true", help="show each check while it runs")
    args = parser.parse_args()
    if args.part == "3.1" and not args.compose_dir:
        parser.error("--part 3.1 needs --compose-dir")
    if args.part == "3.2" and not args.namespace:
        parser.error("--part 3.2 needs --namespace")

    style = None
    if args.token_header:
        name, _, value = args.token_header.partition(":")
        style = (name.strip(), value.strip())
    context = A3Context(args, style)
    try:
        wait_for(context.public, context.auth)
    except ServiceUnreachable as error:
        context.unreachable = str(error)
        print(f"Cannot reach a service ({error}); the checks that need it fail or are skipped.", file=sys.stderr)
    started = time.monotonic()
    checks = CHECKS_31 if args.part == "3.1" else CHECKS_32
    results = run_checks(checks, context, "A3", args.only, args.verbose)
    for user in context.users:  # remove the audit's mappings; accounts remain
        if user.token:
            try:
                context.client(user).delete("/")
            except ServiceUnreachable:
                break
    for image in context.shared.get("pulled images", []):  # pulled by K8S-23 and K8S-24
        subprocess.run(["docker", "image", "rm", image], capture_output=True)
    title = f"TA audit, Assignment {args.part} ({'containers' if args.part == '3.1' else 'Kubernetes'})"
    where = f"Compose folder {context.compose_dir}" if args.part == "3.1" else f"namespace {args.namespace}"
    target = (f"Shortener: {args.url}, authentication: {args.auth_url}, {where}. "
              f"{len(results)} checks in {time.monotonic() - started:.0f} s.")
    print_report(title, target, results)
    if args.report:
        write_markdown(args.report, title, target, results)
        print(f"Report written to {args.report}")
    sys.exit(1 if any(result.status == "FAIL" for result in results) else 0)


if __name__ == "__main__":
    main()
