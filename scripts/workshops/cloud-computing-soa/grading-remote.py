"""Grading runs on the control plane: one pod per group, then clean up.

grading-main.sh sends this module with a payload to the control-plane host
(run_deployment_remote) for each step of a run:

    status   the workshop state, the participant workspaces and any grading run
    start    check the cluster, create the run's ConfigMaps and NetworkPolicy,
             and start the first pods
    step     delete the pods whose results the organiser has saved, start the
             next ones, and return the results of the pods that finished
    cleanup  delete everything the run created and check that nothing is left

Every object of a run has the label digitafrica.io/grading-run=<run> and is
owned by the run's lock ConfigMap, so deleting the lock also removes what an
interrupted run left behind. The pods are described in grading-pod.py. The
answer is one compressed JSON block on stdout; errors go to stderr.
"""
import base64
import gzip
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
import zlib
from datetime import datetime, timezone

LOCK = "digitafrica-grading-run"
RUN_LABEL = "digitafrica.io/grading-run"
GROUP_LABEL = "digitafrica.io/grading-group"
WORKSPACE = re.compile(r"^claim-group-(\d+)---")
KUBECONFIG = "/etc/rancher/k3s/k3s.yaml"
BEGIN = "===== GRADING ANSWER BEGIN ====="
END = "===== GRADING ANSWER END ====="
RESULTS_BEGIN = "===== GRADING RESULTS BEGIN ====="
RESULTS_END = "===== GRADING RESULTS END ====="
# Waiting reasons that do not resolve by themselves.
STUCK = {"ErrImagePull", "ImagePullBackOff", "InvalidImageName", "CreateContainerConfigError",
         "CreateContainerError", "RunContainerError"}
# Egress "participant": DNS, and the internet as for participant servers, but
# not these ranges (other pods, Services, private networks, shared address space,
# link-local addresses with the cloud metadata server), nor the nodes or the
# Kubernetes API, whose addresses can be public.
BLOCKED = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16"]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def call(command, input=None):
    return subprocess.run(command, input=input, capture_output=True, text=True)


def short(text, limit=400):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


class Cluster:
    """kubectl and helm for one namespace, through call() (replaced in the tests)."""

    def __init__(self, namespace, call=call, now=time.time):
        self.namespace, self.call, self.now = namespace, call, now
        self.kubectl = ["k3s", "kubectl", "-n", namespace]

    def read(self, command, what):
        result = self.call(command)
        require(result.returncode == 0, f"Cannot read {what}: {short(result.stderr)}")
        try:
            return json.loads(result.stdout) if result.stdout.strip() else None
        except ValueError:
            raise RuntimeError(f"Cannot read {what}: the answer is not JSON.") from None

    def get(self, kind, name):
        return self.read(self.kubectl + ["get", kind, name, "--ignore-not-found", "-o", "json"], f"{kind} {name}")

    def items(self, kind, selector=None):
        command = self.kubectl + ["get", kind, "-o", "json"] + (["-l", selector] if selector else [])
        return (self.read(command, f"the {kind} list") or {}).get("items", [])

    def create(self, manifest):
        result = self.call(self.kubectl + ["create", "-f", "-", "-o", "json"], json.dumps(manifest))
        require(result.returncode == 0,
                f"Cannot create {manifest['kind']} {manifest['metadata']['name']}: {short(result.stderr)}")
        return json.loads(result.stdout)

    def delete(self, kind, name=None, selector=None, wait=True):
        """Delete; an error message if that failed (a pod can hang in Terminating), else None."""
        target = [kind, name] if name else [kind, "-l", selector]
        options = ["--wait=true", "--timeout=120s"] if wait else ["--wait=false"]
        result = self.call(self.kubectl + ["delete"] + target + ["--ignore-not-found"] + options)
        return None if result.returncode == 0 else f"Cannot delete {' '.join(target)}: {short(result.stderr)}"

    def logs(self, pod, container, tail=None, limit=None):
        """A container's log, or None if it cannot be read."""
        command = self.kubectl + ["logs", pod, "-c", container]
        command += (["--tail", str(tail)] if tail else []) + ([f"--limit-bytes={limit}"] if limit else [])
        result = self.call(command)
        return result.stdout if result.returncode == 0 else None


def timestamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age(item, now):
    created = item["metadata"].get("creationTimestamp")
    if not created:
        return 0
    return now - datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def workshop_state(cluster):
    state = (cluster.get("configmap", "digitafrica-workshop-state") or {}).get("data") or {}
    return {key: state.get(key, "") for key in
            ("workshop_type", "workshop_module", "mode", "solutions_released", "cleanup_status")}


def workspaces(cluster):
    """[group, volume claim] for every bound participant volume, in group order."""
    found = {}
    for claim in cluster.items("pvc"):
        name = claim["metadata"]["name"]
        match = WORKSPACE.match(name)
        if match and claim.get("status", {}).get("phase") == "Bound":
            group = f"group_{match.group(1)}"
            require(group not in found, f"{group} has two volumes: {found.get(group)} and {name}.")
            found[group] = name
    return sorted(found.items(), key=lambda item: int(item[0].split("_")[1]))


def server_version(cluster):
    version = cluster.read(["k3s", "kubectl", "version", "-o", "json"], "the Kubernetes version")
    server = (version or {}).get("serverVersion") or {}
    minor = re.match(r"\d+", server.get("minor", ""))
    require(server.get("major") == "1" and minor, "Cannot read the Kubernetes version.")
    return (1, int(minor.group())), server.get("gitVersion", "")


def notebook_image(cluster):
    values = cluster.read(["helm", "--kubeconfig", KUBECONFIG, "-n", cluster.namespace, "get", "values", "jhub",
                           "-o", "json"], "the JupyterHub values (helm get values jhub)") or {}
    image = (values.get("singleuser") or {}).get("image") or {}
    require(isinstance(image.get("name"), str) and image["name"],
            "The JupyterHub values name no singleuser image.")
    return f"{image['name']}:{image['tag']}" if image.get("tag") else image["name"]


def owner(lock):
    return {"apiVersion": "v1", "kind": "ConfigMap", "name": LOCK, "uid": lock["metadata"]["uid"]}


def cluster_addresses(cluster):
    """The IPv4 addresses of the nodes and of the Kubernetes API that BLOCKED leaves out, as /32 ranges."""
    found = set()
    for node in cluster.items("node"):
        for address in (node.get("status") or {}).get("addresses") or []:
            if address.get("type") in ("InternalIP", "ExternalIP") and address.get("address"):
                found.add(address["address"])
    endpoints = cluster.read(["k3s", "kubectl", "-n", "default", "get", "endpoints", "kubernetes", "-o", "json"],
                             "the Kubernetes API endpoints") or {}
    for subset in endpoints.get("subsets") or []:
        found.update(address["ip"] for address in subset.get("addresses") or [] if address.get("ip"))
    require(found, "Cannot read the addresses of the nodes and the Kubernetes API, which the grading pods "
                   "must not reach.")
    blocked = [ipaddress.ip_network(cidr) for cidr in BLOCKED]
    addresses = set()
    for text in found:
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            continue
        if address.version == 4 and not any(address in network for network in blocked):
            addresses.add(address)
    return [f"{address}/32" for address in sorted(addresses)]


def network_policy(run, egress, owned_by, unreachable=()):
    """No ingress. Egress: none at all, or DNS and the internet except BLOCKED and the unreachable ranges."""
    rules = []
    if egress == "participant":
        rules = [
            {"ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
             "to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}}]},
            {"to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": BLOCKED + list(unreachable)}}]},
        ]
    return {
        "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
        "metadata": {"name": f"grading-{run}", "labels": {RUN_LABEL: run}, "ownerReferences": [owned_by]},
        "spec": {"podSelector": {"matchLabels": {RUN_LABEL: run}}, "policyTypes": ["Ingress", "Egress"],
                 "ingress": [], "egress": rules},
    }


def pod(run, group, claim, owned_by):
    """The grading pod of one group (see grading-pod.py)."""
    image, bundle = run["image"], f"grading-{run['run']}-bundle"
    secure = {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
              "runAsNonRoot": True, "runAsUser": 1000}

    def command(step, folder, *extra):
        return ["python3", "-s", "-E", "-B", f"{folder}/grading-pod.py", step,
                "--module", run["module"], "--track", run["track"], *extra]

    def resources(cpu, memory, limits=None):
        return {"requests": {"cpu": cpu, "memory": memory}, "limits": limits or {"cpu": "1", "memory": "1Gi"}}

    def mount(name, path, read_only=False):
        return {"name": name, "mountPath": path, "readOnly": read_only}

    # Without network, the pod's only name server is its dns container on
    # 127.0.0.1:53, a port that uid 1000 may open in this pod: it refuses every
    # lookup at once and writes down the names. At the cluster DNS, blocked
    # lookups would take up to 5 seconds each.
    offline = run["egress"] == "none"
    dns = {"dnsPolicy": "None", "dnsConfig": {"nameservers": ["127.0.0.1"]}} if offline else {}
    ports = {"sysctls": [{"name": "net.ipv4.ip_unprivileged_port_start", "value": "53"}]} if offline else {}
    resolver = [
        {"name": "dns", "image": image, "imagePullPolicy": "IfNotPresent", "restartPolicy": "Always",
         "command": command("dns", "/runner"), "securityContext": secure,
         "resources": resources("20m", "32Mi", {"cpu": "200m", "memory": "128Mi"}),
         # The group's services start once it answers.
         "startupProbe": {"exec": {"command": ["test", "-f", "/queries/ready"]}, "periodSeconds": 1,
                          "failureThreshold": 60},
         "volumeMounts": [mount("queries", "/queries"), mount("runner", "/runner", True)]},
    ] if offline else []
    return {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {
            "name": f"grading-{run['run']}-{group.replace('_', '-')}",
            "labels": {RUN_LABEL: run["run"], GROUP_LABEL: group, "app.kubernetes.io/name": "digitafrica-grading"},
            "ownerReferences": [owned_by],
        },
        "spec": {
            "restartPolicy": "Never",
            "activeDeadlineSeconds": int(run["deadline"]),
            "terminationGracePeriodSeconds": 5,
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            **dns,
            "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "seccompProfile": {"type": "RuntimeDefault"},
                                **ports},
            # The tolerations of the chart's participant servers, so that the pod runs where they do.
            "tolerations": [{"key": key, "operator": "Equal", "value": "user", "effect": "NoSchedule"}
                            for key in ("hub.jupyter.org/dedicated", "hub.jupyter.org_dedicated")],
            "volumes": [
                {"name": "workspace", "persistentVolumeClaim": {"claimName": claim, "readOnly": True}},
                {"name": "home", "emptyDir": {"sizeLimit": "1Gi"}},
                {"name": "source", "emptyDir": {"sizeLimit": "64Mi"}},
                {"name": "results", "emptyDir": {"sizeLimit": "64Mi"}},
                # Where the group's processes write down the hosts that they try to reach.
                {"name": "network", "emptyDir": {"sizeLimit": "16Mi"}},
                {"name": "runner", "configMap": {"name": bundle, "items": [
                    {"key": "grading-pod.py", "path": "grading-pod.py"},
                    {"key": "manifest.json", "path": "manifest.json"}]}},
                {"name": "grading", "configMap": {"name": bundle}},
            ] + ([{"name": "queries", "emptyDir": {"sizeLimit": "8Mi"}}] if offline else []),
            "initContainers": [
                {"name": "prepare", "image": image, "imagePullPolicy": "IfNotPresent",
                 "command": command("prepare", "/runner", "--policy-wait", "60"), "securityContext": secure,
                 # The node's address, for the check that the pod's network rules are in force.
                 "env": [{"name": "HOST_IP", "valueFrom": {"fieldRef": {"fieldPath": "status.hostIP"}}}],
                 "resources": resources("100m", "128Mi"),
                 "volumeMounts": [mount("workspace", "/workspace", True), mount("home", "/home/jovyan"),
                                  mount("source", "/source"), mount("runner", "/runner", True)]},
                *resolver,
                # A native sidecar: it runs next to the grader and stops when the grader is done.
                {"name": "service", "image": image, "imagePullPolicy": "IfNotPresent", "restartPolicy": "Always",
                 "command": command("serve", "/runner"), "env": [{"name": "HOME", "value": "/home/jovyan"}],
                 # The limits of a participant server (singleuser cpu and memory in the JupyterHub values).
                 "securityContext": secure, "resources": resources("250m", "256Mi", {"cpu": "2", "memory": "2G"}),
                 "volumeMounts": [mount("workspace", "/workspace", True), mount("home", "/home/jovyan"),
                                  mount("runner", "/runner", True), mount("network", "/network")]},
            ],
            "containers": [
                {"name": "grader", "image": image, "imagePullPolicy": "IfNotPresent",
                 "command": command("grade", "/grading", "--kind", run["kind"], "--wait", run["wait"],
                                    "--timeout", run["timeout"]),
                 "env": [{"name": "HOME", "value": "/results"}], "securityContext": secure,
                 "resources": resources("100m", "128Mi"),
                 "volumeMounts": [mount("grading", "/grading", True), mount("source", "/source", True),
                                  mount("results", "/results"), mount("network", "/network", True)]
                 + ([mount("queries", "/queries", True)] if offline else [])},
            ],
        },
    }


def classify(item, now, deadline):
    """done, failed, stuck, pending or running, and why."""
    status = item.get("status") or {}
    phase = status.get("phase", "Pending")
    if phase == "Succeeded":
        return "done", ""
    if phase == "Failed":
        return "failed", short(" ".join(filter(None, (status.get("reason"), status.get("message")))))
    seconds = age(item, now)
    for container in status.get("initContainerStatuses", []) + status.get("containerStatuses", []):
        waiting = (container.get("state") or {}).get("waiting") or {}
        if waiting.get("reason") in STUCK and seconds > 120:
            return "stuck", short(f"{container['name']}: {waiting['reason']} {waiting.get('message', '')}")
    if phase == "Pending":
        unscheduled = [condition for condition in status.get("conditions", [])
                       if condition.get("type") == "PodScheduled" and condition.get("status") == "False"]
        if unscheduled and seconds > 600:
            return "stuck", short(f"not scheduled: {unscheduled[0].get('message', '')}")
        if seconds > 1200:
            return "stuck", "still pending after 20 minutes"
        return "pending", ""
    if phase != "Running" and seconds > deadline + 600:
        return "stuck", f"pod phase {phase}"
    return "running", ""


def results_block(log):
    """The results that grading-pod.py printed, and the log lines around them."""
    lines = log.splitlines()
    if RESULTS_BEGIN in lines and RESULTS_END in lines[lines.index(RESULTS_BEGIN):]:
        first = lines.index(RESULTS_BEGIN)
        last = lines.index(RESULTS_END, first)
        try:
            block = json.loads(gzip.decompress(base64.b64decode("".join(lines[first + 1:last]))))
        except (ValueError, OSError, EOFError, zlib.error):
            block = None
        return block, lines[:first] + lines[last + 1:]
    return None, lines


def start_and_end(cluster, pod, container):
    """A log's first 60 kB, where start-up errors are, and its last 200 lines."""
    head = cluster.logs(pod, container, limit=60000)
    if head is None or len(head) < 60000:
        return head or ""
    tail = cluster.logs(pod, container, tail=200, limit=60000) or ""
    return head.rsplit("\n", 1)[0] + "\n[... the middle of the log is left out ...]\n" + tail


def collect(cluster, item, state, reason, deadline):
    """What a finished pod left; None while a finished grader's log cannot be read yet."""
    name = item["metadata"]["name"]
    status = item.get("status") or {}
    log = cluster.logs(name, "grader")
    if log is None and state == "done" and age(item, cluster.now()) < deadline + 600:
        return None
    block, other = results_block(log or "")
    containers = {}
    for container in status.get("initContainerStatuses", []) + status.get("containerStatuses", []):
        kind, detail = next(iter((container.get("state") or {}).items()), ("unknown", {}))
        containers[container["name"]] = {
            "state": kind, "reason": detail.get("reason", ""), "exit": detail.get("exitCode"),
            "restarts": container.get("restartCount", 0)}
    events = []
    if state != "done":
        listed = cluster.read(cluster.kubectl + ["get", "events", "--field-selector",
                                                 f"involvedObject.name={name}", "-o", "json"], "the events")
        events = [f"{event.get('type', '')} {event.get('reason', '')}: {short(event.get('message', ''), 300)}"
                  for event in (listed or {}).get("items", [])][-15:]
    return {
        "state": state, "reason": reason, "results": block,
        "pod": {"name": name, "phase": status.get("phase", ""), "reason": status.get("reason", ""),
                "message": short(status.get("message", "")), "node": item.get("spec", {}).get("nodeName", ""),
                "started": status.get("startTime", ""), "containers": containers},
        "events": events,
        "logs": {"grader": "\n".join(other[-60:]), "service": start_and_end(cluster, name, "service"),
                 "prepare": start_and_end(cluster, name, "prepare"), "dns": start_and_end(cluster, name, "dns")},
    }


def the_run(cluster, run):
    lock = cluster.get("configmap", LOCK)
    require(lock is not None and (lock.get("data") or {}).get("run") == run,
            f"Grading run {run} is no longer in the cluster.")
    return lock


def idle(run, now):
    """Seconds since the organiser last followed the run."""
    last = run.get("touched") or run.get("started")
    try:
        return int(now - datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError):
        return None


def status(cluster, payload):
    lock = (cluster.get("configmap", LOCK) or {}).get("data")
    if lock:
        lock["idle"] = idle(lock, cluster.now())
    return {"state": workshop_state(cluster), "lock": lock,
            "groups": [group for group, _ in workspaces(cluster)], "host": socket.gethostname()}


def start(cluster, payload):
    version, git_version = server_version(cluster)
    require(version >= (1, 29), f"Kubernetes {git_version} cannot run the grading pods: they need "
                                "sidecar containers, from Kubernetes 1.29.")
    existing = (cluster.get("configmap", LOCK) or {}).get("data")
    require(existing is None, f"Grading run {(existing or {}).get('run')}, started "
                              f"{(existing or {}).get('started')}, is still in the cluster.")
    cleanup_status = workshop_state(cluster)["cleanup_status"]
    require(cleanup_status not in ("in_progress", "failed"),
            f"Workshop cleanup is incomplete ({cleanup_status}); the workspaces may be partly deleted.")
    egress = payload["egress"]
    require(egress in ("none", "participant"), f"Unknown network setting for the grading pods: {egress}.")
    unreachable = cluster_addresses(cluster) if egress == "participant" else []
    image = payload.get("image") or notebook_image(cluster)
    groups = workspaces(cluster)
    if payload.get("groups"):
        unknown = sorted(set(payload["groups"]) - {group for group, _ in groups})
        require(not unknown, f"No workspace for {', '.join(unknown)}.")
        groups = [(group, claim) for group, claim in groups if group in payload["groups"]]
    require(groups, "There are no participant workspaces (claim-group-NN volumes) to grade.")
    run = payload["run"]
    data = {key: str(payload[key]) for key in ("run", "module", "track", "kind", "parallel", "egress",
                                               "wait", "timeout")}
    data.update(image=image, started=timestamp(cluster.now()), groups=json.dumps(groups),
                deadline=str(int(payload["wait"]) + int(payload["timeout"]) + 300))
    lock = cluster.create({"apiVersion": "v1", "kind": "ConfigMap",
                           "metadata": {"name": LOCK, "labels": {RUN_LABEL: run}}, "data": data})
    owned_by = owner(lock)
    files = json.loads(gzip.decompress(base64.b64decode(payload["bundle"])))
    cluster.create({"apiVersion": "v1", "kind": "ConfigMap",
                    "metadata": {"name": f"grading-{run}-bundle", "labels": {RUN_LABEL: run},
                                 "ownerReferences": [owned_by]},
                    "data": files})
    cluster.create(network_policy(run, egress, owned_by, unreachable))
    answer = step(cluster, {"run": run, "saved": []})
    answer.update(image=image, names=[group for group, _ in groups], host=socket.gethostname(),
                  kubernetes=git_version, started=data["started"], unreachable=unreachable)
    return answer


def step(cluster, payload):
    lock = the_run(cluster, payload["run"])
    run = lock["data"]
    # Shows a later status check that the organiser still follows the run.
    cluster.call(cluster.kubectl + ["patch", "configmap", LOCK, "--type", "merge", "-p",
                                    json.dumps({"data": {"touched": timestamp(cluster.now())}})])
    saved = set(payload.get("saved") or [])
    pods = {item["metadata"]["labels"].get(GROUP_LABEL): item
            for item in cluster.items("pod", f"{RUN_LABEL}={run['run']}")}
    for group in sorted(saved & set(pods)):  # cleanup removes any that hang
        cluster.delete("pod", pods.pop(group)["metadata"]["name"], wait=False)
    states, results, active = {}, {}, 0
    groups = json.loads(run["groups"])
    for group, _ in groups:
        if group in saved:
            states[group] = "saved"
        elif group not in pods:
            states[group] = "waiting"
        else:
            state, reason = classify(pods[group], cluster.now(), int(run["deadline"]))
            result = None if state in ("pending", "running") else \
                collect(cluster, pods[group], state, reason, int(run["deadline"]))
            if result is None:
                states[group] = "running" if state == "done" else state
                active += 1
            else:
                states[group] = state
                results[group] = result
    for group, claim in groups:
        if states[group] == "waiting" and active < int(run["parallel"]):
            try:
                cluster.create(pod(run, group, claim, owner(lock)))
            except RuntimeError as error:  # reported for this group; the others go on
                states[group] = "not started"
                results[group] = {"state": "not started", "reason": str(error), "results": None,
                                  "pod": {}, "events": [], "logs": {}}
                continue
            states[group] = "pending"
            active += 1
    return {"run": run["run"], "groups": states, "results": results}


def cleanup(cluster, payload):
    run = payload["run"]
    current = (cluster.get("configmap", LOCK) or {}).get("data") or {}
    require(not current or current.get("run") == run,
            f"The grading run in the cluster is {current.get('run')}, not {run}.")
    selector = f"{RUN_LABEL}={run}"
    deleted, left, errors = {}, {}, []
    # The pods first. While one is left, for example hanging in deletion, the
    # run's NetworkPolicy and ConfigMaps stay: without its rules a pod that still
    # runs would reach the network, and the lock lets the next run remove it.
    for kind in ("pod", "networkpolicy", "configmap"):
        if kind != "pod" and cluster.items("pod", selector):
            deleted[kind] = 0
            continue
        deleted[kind] = len(cluster.items(kind, selector))
        error = cluster.delete(kind, selector=selector)
        if error:
            errors.append(error)
    for kind in deleted:
        names = [item["metadata"]["name"] for item in cluster.items(kind, selector)]
        if names:
            left[kind] = names
    return {"run": run, "deleted": deleted, "left": left, "errors": errors}


def execute(payload, call=call, now=time.time):
    operations = {"status": status, "start": start, "step": step, "cleanup": cleanup}
    require(payload.get("operation") in operations, "Invalid grading operation.")
    return operations[payload["operation"]](Cluster(payload["namespace"], call, now), payload)


def answer(data):
    block = base64.b64encode(gzip.compress(json.dumps(data).encode())).decode()
    print(BEGIN)
    for first in range(0, len(block), 76):
        print(block[first:first + 76])
    print(END)


if __name__ == "__main__":
    try:
        answer(execute(json.loads(gzip.decompress(base64.b64decode(sys.argv[1])))))
    except (RuntimeError, ValueError, KeyError, TypeError, OSError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
