#!/usr/bin/env python3
"""Plan/create immutable group Secrets. Private stdin and kubectl output stay in memory.

Must run in an Ansible no_log task. Prints only a sanitised public summary.
Never replaces an existing Secret, deletes resources or restarts services.
"""
import base64
from copy import deepcopy
import hashlib
import json
import re
import subprocess
import sys

MANAGED = {
    "digitafrica.eu/managed-by": "organiser",
    "digitafrica.eu/workshop": "big-data",
    "digitafrica.eu/module": "spark",
}
HELPER = "digitafrica-spark-credential-code"


class Blocked(Exception):
    pass


def require(ok, reason):
    if not ok:
        raise Blocked(reason)


def kubectl(argv, payload=None):
    result = subprocess.run(["k3s", "kubectl", *argv],
        input=None if payload is None else json.dumps(payload),
        text=True, capture_output=True, timeout=30, check=False)
    require(result.returncode == 0, "kubernetes_operation_failed")
    return result.stdout


def existing(namespace, kind, name):
    text = kubectl(["-n", namespace, "get", kind, name, "-o", "json", "--ignore-not-found"])
    return json.loads(text) if text.strip() else None


def check_secret(current, desired):
    if current is None:
        return "create"
    labels = current.get("metadata", {}).get("labels", {})
    require(all(labels.get(k) == v for k, v in desired["metadata"]["labels"].items()),
            "existing_secret_ownership_conflict")
    require(current.get("type") == "Opaque" and current.get("immutable") is True,
            "existing_secret_not_managed_immutable_opaque")
    require(current.get("data") == desired["data"], "existing_secret_credential_conflict")
    return "preserve"


def desired_secret(namespace, request):
    group = request["group_id"]
    require(re.fullmatch(r"group_[0-9]{2,}", group), "invalid_group_id")
    require(bool(request["worker"]) and bool(request["worker_node"]), "missing_worker_binding")
    require(request["operation"] == "apply", "invalid_startup_operation")
    for name in ("login_key", "known_hosts"):
        entry = request["credentials"][name]
        value = base64.b64decode(entry["content_b64"], validate=True)
        require(0 < len(value) <= 16384 and hashlib.sha256(value).hexdigest() == entry["sha256"],
                "credential_payload_checksum_mismatch")
    encoded = base64.b64encode(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).decode()
    return {"apiVersion": "v1", "kind": "Secret", "type": "Opaque", "immutable": True,
        "metadata": {"name": "digitafrica-spark-direct-" + group.replace("_", "-"),
                     "namespace": namespace,
                     "labels": {**MANAGED, "digitafrica.eu/spark-group": group}},
        "data": {"request.json": encoded}}


def stage(request):
    namespace = request["namespace"]
    require(isinstance(namespace, str) and len(namespace) <= 63
            and re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", namespace), "invalid_namespace")
    operation = request.get("operation", "plan")
    require(operation in ("plan", "apply", "verify"), "invalid_operation")
    requests = request["requests"]
    require(bool(requests), "no_validated_requests")
    require(len({r["group_id"] for r in requests}) == len(requests), "duplicate_group")
    require(len({r["worker"] for r in requests}) == len(requests), "duplicate_worker")
    plans = []
    for item in requests:
        desired = desired_secret(namespace, item)
        action = check_secret(existing(namespace, "secret", desired["metadata"]["name"]), desired)
        plans.append((item, desired, action))
    code = request["helper_code"]
    require(isinstance(code, str) and bool(code), "missing_reconciler_code")
    current_helper = existing(namespace, "configmap", HELPER)
    helper = {"apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {"name": HELPER, "namespace": namespace, "labels": MANAGED},
        "data": {"reconcile_credentials.py": code}}
    helper_action = "create"
    if current_helper is not None:
        labels = current_helper.get("metadata", {}).get("labels", {})
        require(all(labels.get(k) == v for k, v in MANAGED.items()), "helper_configmap_ownership_conflict")
        require(set(current_helper.get("data", {})) == {"reconcile_credentials.py"}
                and not current_helper.get("binaryData"), "helper_configmap_unexpected_contents")
        helper_action = "preserve" if current_helper["data"] == helper["data"] else "update"
    # Verify uses the same identity/payload checks but never creates or updates.
    if operation == "verify":
        require(helper_action == "preserve", "credential_helper_not_staged_current")
        require(all(action == "preserve" for _, _, action in plans),
                "group_credentials_not_staged")
    # All source payloads and existing resources pass preflight before any write.
    if operation == "apply":
        if helper_action == "create":
            kubectl(["create", "-f", "-"], helper)
        elif helper_action == "update":
            replacement = deepcopy(current_helper)
            replacement["data"] = helper["data"]
            kubectl(["replace", "-f", "-"], replacement)
        for item, desired, action in plans:
            if action == "create":
                # CREATE, never APPLY/REPLACE: a conflicting race fails closed.
                kubectl(["create", "-f", "-"], desired)
    return {"status": {"plan": "planned", "apply": "staged", "verify": "verified"}[operation],
        "namespace": namespace, "helper_action": helper_action,
        "groups": [{"group_id": item["group_id"], "worker": item["worker"],
                    "worker_node": item["worker_node"],
                    "secret": desired["metadata"]["name"], "action": action}
                   for item, desired, action in plans]}


def self_test():
    import unittest
    class Tests(unittest.TestCase):
        def setUp(self):
            self.desired = {"metadata": {"labels": {**MANAGED, "digitafrica.eu/spark-group": "group_01"}},
                "type": "Opaque", "immutable": True, "data": {"request.json": "Zml4dHVyZQ=="}}
        def test_missing_secret(self):
            self.assertEqual(check_secret(None, self.desired), "create")
        def test_matching_secret_preserved(self):
            self.assertEqual(check_secret(deepcopy(self.desired), self.desired), "preserve")
        def test_conflicting_secret_data(self):
            current = deepcopy(self.desired)
            current["data"]["request.json"] = "b3RoZXI="
            with self.assertRaises(Blocked): check_secret(current, self.desired)
        def test_foreign_secret(self):
            current = deepcopy(self.desired)
            current["metadata"]["labels"]["digitafrica.eu/managed-by"] = "other"
            with self.assertRaises(Blocked): check_secret(current, self.desired)
        def test_mutable_secret(self):
            current = deepcopy(self.desired)
            current["immutable"] = False
            with self.assertRaises(Blocked): check_secret(current, self.desired)
        def test_unrelated_metadata_preserved(self):
            current = deepcopy(self.desired)
            current["metadata"]["annotations"] = {"unrelated": "preserve"}
            self.assertEqual(check_secret(current, self.desired), "preserve")
    return unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(Tests)).wasSuccessful()


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--self-test"]:
            sys.exit(0 if self_test() else 1)
        require(not sys.argv[1:], "unsupported_arguments")
        raw = sys.stdin.read(2097153)
        require(len(raw) <= 2097152, "request_too_large")
        print(json.dumps(stage(json.loads(raw))))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, Blocked) else "credential_staging_failed"
        print(json.dumps({"status": "blocked", "reason": reason}))
        sys.exit(2)
