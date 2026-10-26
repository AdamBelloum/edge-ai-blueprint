"""A fake k3s cluster for the grading tests: the kubectl and helm commands of grading-remote.py.

FakeCluster.call(command, input) answers like subprocess.run would, keeps the
objects that are created, and can finish pods with the log that grading-pod.py
prints. Run as a program (python3 grading_fake_cluster.py k3s|helm ...), it
keeps its state in the JSON file named by FAKE_CLUSTER, for tests that put
k3s and helm wrappers on PATH.
"""
import base64
import gzip
import json
import os
import sys
import types
from datetime import datetime, timezone

NAMESPACE = "digitafrica"
IMAGE = {"name": "quay.io/jupyterhub/k8s-singleuser-sample", "tag": "4.4.2"}
KINDS = {"configmap": "ConfigMap", "pvc": "PersistentVolumeClaim", "pod": "Pod",
         "networkpolicy": "NetworkPolicy", "node": "Node"}


def results_log(summary, files):
    """The grader's log, as grading-pod.py prints it."""
    block = base64.b64encode(gzip.compress(json.dumps({"summary": summary, "files": files}).encode())).decode()
    return "\n".join(["[runner] done", "===== GRADING RESULTS BEGIN ====="]
                     + [block[start:start + 76] for start in range(0, len(block), 76)]
                     + ["===== GRADING RESULTS END ====="]) + "\n"


def tests_result(module="1", earned=12, possible=12, work="changed"):
    """The grader's log for a grading-script run with the given points."""
    report = {"assignment": module, "earned": earned, "possible": possible, "not_checked": 0,
              "passed": earned == possible, "notes": [], "not_tested": [{"line": "Report", "points": 20}],
              "lines": [{"line": "Methods: GET /:id answers 301 with the URL", "points": possible,
                         "status": "passed" if earned == possible else "failed", "earned": earned,
                         "problems": [] if earned == possible else [{"outcome": "fail", "detail": "expected 301"}]}]}
    summary = {"module": module, "kind": "tests", "track": "intermediate", "work": work, "reason": "",
               "waited": 1.0, "closed": [], "listening": [5000], "exit": 0, "outcome": "graded"}
    return results_log(summary, {"tests.json": json.dumps(report), "tests.txt": "12/12 tested by this script\n",
                                 "prepare.json": json.dumps({"work": work}), "grade.json": json.dumps(summary)})


class FakeCluster:
    def __init__(self, state=None):
        self.state = state or {
            "now": 1_800_000_000.0, "uid": 0,
            "objects": {kind: {} for kind in KINDS},
            "logs": {}, "events": {},
            "version": {"serverVersion": {"major": "1", "minor": "30", "gitVersion": "v1.30.4+k3s1"}},
            "values": {"singleuser": {"image": dict(IMAGE)}},
            # The Kubernetes API answers on the public address of the first node.
            "endpoints": {"subsets": [{"addresses": [{"ip": "203.0.113.10"}], "ports": [{"port": 6443}]}]},
            "fail": [],        # substrings of commands that fail
            "finish": None,    # grader log that newly created pods finish with
            "container_logs": {},  # container name -> log, for pods without a log of their own
        }
        self.commands = []
        if state is None:
            # Public node addresses, as in production; private and IPv6 ones are blocked anyway.
            self.add("node", "central", status={"addresses": [
                {"type": "InternalIP", "address": "203.0.113.10"}, {"type": "InternalIP", "address": "2001:db8::10"},
                {"type": "Hostname", "address": "central"}]})
            self.add("node", "worker1", status={"addresses": [
                {"type": "InternalIP", "address": "10.0.0.5"}, {"type": "ExternalIP", "address": "203.0.113.11"}]})
            self.add("configmap", "digitafrica-workshop-state", data={
                "workshop_type": "cloud-computing-soa", "workshop_module": "module1", "mode": "intermediate",
                "solutions_released": "false", "cleanup_status": "complete"})
            for number, suffix in (("01", "4f9a1b2c"), ("02", "77aa01bb"), ("03", "0c0c0c0c")):
                self.add("pvc", f"claim-group-{number}---{suffix}", status={"phase": "Bound"})
            self.add("pvc", "claim-admin", status={"phase": "Bound"})
            self.add("pvc", "claim-group-09---pending", status={"phase": "Pending"})

    @property
    def objects(self):
        return self.state["objects"]

    def timestamp(self):
        return datetime.fromtimestamp(self.state["now"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def add(self, resource, name, **fields):
        self.state["uid"] += 1
        item = {"apiVersion": "v1", "kind": KINDS[resource],
                "metadata": {"name": name, "namespace": NAMESPACE, "uid": f"uid-{self.state['uid']}",
                             "creationTimestamp": self.timestamp(), "labels": {}}}
        item.update(fields)
        self.objects[resource][name] = item
        return item

    def finish(self, name, phase="Succeeded", log=None, **status):
        item = self.objects["pod"][name]
        item["status"] = dict(item.get("status") or {}, phase=phase, **status)
        if log is not None:
            self.state["logs"][f"{name}/grader"] = log

    def pods(self):
        return sorted(self.objects["pod"])

    # ---- the commands

    def call(self, command, input=None):
        self.commands.append(command)
        text = " ".join(command)
        if any(failing in text for failing in self.state["fail"]):
            return self.answer(1, "", f"fake failure: {text}")
        if command[0] == "helm":
            return self.answer(0, json.dumps(self.state["values"]))
        assert command[:2] == ["k3s", "kubectl"], command
        if command[2] == "version":
            return self.answer(0, json.dumps(self.state["version"]))
        if command[2:7] == ["-n", "default", "get", "endpoints", "kubernetes"]:
            return self.answer(0, json.dumps(self.state["endpoints"]))
        assert command[2:4] == ["-n", NAMESPACE], command
        verb, rest = command[4], command[5:]
        return getattr(self, "do_" + verb)(rest, input)

    def answer(self, code, stdout, stderr="", raw=None):
        """As grading-remote.py's call() returns it; raw: the bytes that kubectl prints, for main()."""
        return types.SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr, raw=raw)

    def selected(self, kind, rest):
        items = list(self.objects[kind].values())
        if "-l" in rest:
            key, value = rest[rest.index("-l") + 1].split("=", 1)
            items = [item for item in items if item["metadata"].get("labels", {}).get(key) == value]
        return items

    def do_get(self, rest, input):
        kind = rest[0]
        if kind == "events":
            name = rest[rest.index("--field-selector") + 1].split("=", 1)[1]
            return self.answer(0, json.dumps({"items": self.state["events"].get(name, [])}))
        if len(rest) > 1 and not rest[1].startswith("-"):
            item = self.objects[kind].get(rest[1])
            if item is None:
                return self.answer(0, "") if "--ignore-not-found" in rest else self.answer(1, "", "NotFound")
            output = rest[rest.index("-o") + 1] if "-o" in rest else ""
            if output.startswith("jsonpath={.data.") and output.endswith("}"):  # the only JSONPath used
                return self.answer(0, str((item.get("data") or {}).get(output[len("jsonpath={.data."):-1], "")))
            return self.answer(0, json.dumps(item))
        return self.answer(0, json.dumps({"items": self.selected(kind, rest)}))

    def do_create(self, rest, input):
        manifest = json.loads(input)
        kind = {value: key for key, value in KINDS.items()}[manifest["kind"]]
        name = manifest["metadata"]["name"]
        if name in self.objects[kind]:
            return self.answer(1, "", f'{kind} "{name}" already exists')
        item = self.add(kind, name, **{key: value for key, value in manifest.items()
                                       if key not in ("metadata", "kind", "apiVersion")})
        item["apiVersion"] = manifest["apiVersion"]
        item["metadata"].update({key: value for key, value in manifest["metadata"].items()})
        if kind == "pod":
            item["status"] = {"phase": "Pending"}
            if self.state["finish"] is not None:
                self.finish(name, log=self.state["finish"])
        return self.answer(0, json.dumps(item))

    def do_delete(self, rest, input):
        kind = rest[0]
        if rest[1] == "-l":
            for item in self.selected(kind, rest):
                del self.objects[kind][item["metadata"]["name"]]
        else:
            self.objects[kind].pop(rest[1], None)
        return self.answer(0, "deleted")

    def do_patch(self, rest, input):
        kind, name, patch = rest[0], rest[1], json.loads(rest[rest.index("-p") + 1])
        item = self.objects[kind].get(name)
        if item is None:
            return self.answer(1, "", "NotFound")
        item.setdefault("data", {}).update(patch.get("data", {}))
        return self.answer(0, "patched")

    def do_logs(self, rest, input):
        pod, container = rest[0], rest[rest.index("-c") + 1]
        if pod not in self.objects["pod"]:
            return self.answer(1, "", "NotFound")
        log = self.state["logs"].get(f"{pod}/{container}", self.state.get("container_logs", {}).get(container, ""))
        data = log.encode()
        if "--tail" in rest:
            data = b"".join(data.splitlines(True)[-int(rest[rest.index("--tail") + 1]):])
        for option in rest:
            if option.startswith("--limit-bytes="):  # as kubelet: bytes, from the start of the tail
                data = data[:int(option.split("=", 1)[1])]
        return self.answer(0, data.decode("utf-8", "replace"), raw=data)


def main():
    """k3s or helm: answer one command, with the state in the file FAKE_CLUSTER."""
    path = os.environ["FAKE_CLUSTER"]
    with open(path, encoding="utf-8") as stream:
        cluster = FakeCluster(json.load(stream))
    command = sys.argv[1:]
    stdin = sys.stdin.read() if "-f" in command else None
    result = cluster.call(command, stdin)
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(cluster.state, stream)
    sys.stdout.buffer.write(result.stdout.encode() if result.raw is None else result.raw)
    sys.stdout.flush()
    # kubectl can warn on stderr also when a command succeeds, for example about API discovery.
    sys.stderr.write(result.stderr or cluster.state.get("warning", ""))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
