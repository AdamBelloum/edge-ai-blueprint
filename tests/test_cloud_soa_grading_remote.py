"""Grading runs on the control plane (grading-remote.py), against a fake cluster.

Checks what the run creates (the lock, the files, the NetworkPolicy and one
locked-down pod per group), that only the grader container sees the grading
script or the TA audit, how pods are started, followed and collected, and that
cleanup leaves nothing behind. No Kubernetes, Helm or network access.
"""
import base64
import contextlib
import gzip
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from grading_fake_cluster import NAMESPACE, FakeCluster, results_log, tests_result  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "grading_remote", ROOT / "scripts/workshops/cloud-computing-soa/grading-remote.py")
remote = importlib.util.module_from_spec(spec)
written, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no cache next to the file under test
spec.loader.exec_module(remote)
sys.dont_write_bytecode = written

RUN = "0123abcd"
SELECTOR = f"digitafrica.io/grading-run={RUN}"
FILES = {"grading-pod.py": "print('pod')\n", "manifest.json": "{}\n", "test_api.py": "print('tests')\n",
         "read_from.csv": "url\n"}


def pack(data):
    return base64.b64encode(gzip.compress(json.dumps(data).encode())).decode()


class GradingRemoteTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.cluster = FakeCluster()

    def execute(self, operation, **fields):
        payload = {"operation": operation, "namespace": NAMESPACE}
        payload.update(fields)
        return remote.execute(payload, call=self.cluster.call, now=lambda: self.cluster.state["now"])

    def start(self, **fields):
        payload = {"run": RUN, "module": "1", "track": "intermediate", "kind": "tests", "parallel": 2,
                   "egress": "none", "wait": 120, "timeout": 600, "groups": [], "image": "",
                   "bundle": pack(FILES)}
        payload.update(fields)
        return self.execute("start", **payload)

    def pod(self, group):
        return self.cluster.objects["pod"][f"grading-{RUN}-{group.replace('_', '-')}"]

    def run_objects(self):
        return {kind: sorted(name for name, item in items.items()
                             if item["metadata"].get("labels", {}).get("digitafrica.io/grading-run") == RUN)
                for kind, items in self.cluster.objects.items()}

    # ---- status and start

    def test_status_lists_bound_group_workspaces_and_the_state(self):
        answer = self.execute("status")
        self.assertEqual(answer["groups"], ["group_01", "group_02", "group_03"])
        self.assertEqual(answer["state"]["mode"], "intermediate")
        self.assertIsNone(answer["lock"])
        self.assertTrue(answer["host"])

    def test_start_creates_the_lock_files_policy_and_the_first_pods(self):
        answer = self.start()
        self.assertEqual(answer["names"], ["group_01", "group_02", "group_03"])
        self.assertEqual(answer["image"], "quay.io/jupyterhub/k8s-singleuser-sample:4.4.2")
        self.assertEqual(answer["groups"], {"group_01": "pending", "group_02": "pending", "group_03": "waiting"})
        objects = self.run_objects()
        self.assertEqual(objects["configmap"], ["digitafrica-grading-run", f"grading-{RUN}-bundle"])
        self.assertEqual(objects["networkpolicy"], [f"grading-{RUN}"])
        self.assertEqual(objects["pod"], [f"grading-{RUN}-group-01", f"grading-{RUN}-group-02"])
        lock = self.cluster.objects["configmap"]["digitafrica-grading-run"]
        self.assertEqual(json.loads(lock["data"]["groups"]), [
            ["group_01", "claim-group-01---4f9a1b2c"], ["group_02", "claim-group-02---77aa01bb"],
            ["group_03", "claim-group-03---0c0c0c0c"]])
        self.assertEqual(lock["data"]["deadline"], str(120 + 600 + 300))
        self.assertEqual(self.cluster.objects["configmap"][f"grading-{RUN}-bundle"]["data"], FILES)
        # Everything belongs to the lock, so deleting it removes the run.
        for kind in ("pod", "networkpolicy"):
            for item in self.cluster.objects[kind].values():
                self.assertEqual(item["metadata"]["ownerReferences"][0]["uid"], lock["metadata"]["uid"])

    def test_groups_can_be_limited_and_unknown_groups_are_refused(self):
        answer = self.start(groups=["group_03"])
        self.assertEqual(answer["names"], ["group_03"])
        self.assertEqual(self.run_objects()["pod"], [f"grading-{RUN}-group-03"])
        cluster = FakeCluster()
        self.cluster = cluster
        with self.assertRaisesRegex(RuntimeError, "No workspace for group_07"):
            self.start(groups=["group_03", "group_07"])
        self.assertEqual(self.run_objects()["configmap"], [])

    def test_start_refuses_before_creating_anything(self):
        def no_cluster_addresses(cluster):
            cluster.objects["node"].clear()
            cluster.state["endpoints"] = {}

        cases = {
            "old Kubernetes": (lambda c: c.state["version"]["serverVersion"].update(minor="28"), {}),
            "a run in the cluster": (lambda c: c.add("configmap", "digitafrica-grading-run",
                                                     data={"run": "ffff0000", "started": "earlier"}), {}),
            "cleanup in progress": (lambda c: c.objects["configmap"]["digitafrica-workshop-state"]["data"].update(
                cleanup_status="in_progress"), {}),
            "no workspaces": (lambda c: c.objects["pvc"].clear(), {}),
            "no image": (lambda c: c.state["values"].update(singleuser={}), {}),
            "unknown network setting": (lambda c: None, {"egress": "internet"}),
            "addresses to keep out unknown": (no_cluster_addresses, {"egress": "participant"}),
        }
        for name, (change, fields) in cases.items():
            with self.subTest(name):
                self.cluster = FakeCluster()
                change(self.cluster)
                with self.assertRaises(RuntimeError):
                    self.start(**fields)
                self.assertEqual(self.run_objects()["configmap"], [])
                self.assertEqual(self.run_objects()["pod"], [])
                self.assertEqual(self.run_objects()["networkpolicy"], [])

    def test_an_image_given_by_the_organiser_replaces_the_jupyterhub_one(self):
        self.start(image="registry.example/notebook:1")
        self.assertEqual({container["image"] for container in
                          self.pod("group_01")["spec"]["initContainers"] + self.pod("group_01")["spec"]["containers"]},
                         {"registry.example/notebook:1"})
        self.assertFalse([command for command in self.cluster.commands if command[0] == "helm"])

    # ---- the pod

    def test_pods_run_locked_down_on_a_read_only_workspace(self):
        self.start()
        spec = self.pod("group_02")["spec"]
        self.assertEqual(spec["restartPolicy"], "Never")
        self.assertEqual(spec["activeDeadlineSeconds"], 1020)
        self.assertIs(spec["automountServiceAccountToken"], False)
        self.assertIs(spec["enableServiceLinks"], False)
        self.assertEqual(spec["securityContext"], {
            "runAsNonRoot": True, "runAsUser": 1000, "seccompProfile": {"type": "RuntimeDefault"},
            "sysctls": [{"name": "net.ipv4.ip_unprivileged_port_start", "value": "53"}]})
        self.assertNotIn("fsGroup", json.dumps(spec))  # would change the ownership of the group's files
        self.assertNotIn("hostPath", json.dumps(spec))
        self.assertNotIn("serviceAccountName", spec)
        volumes = {volume["name"]: volume for volume in spec["volumes"]}
        self.assertEqual(volumes["workspace"]["persistentVolumeClaim"],
                         {"claimName": "claim-group-02---77aa01bb", "readOnly": True})
        containers = spec["initContainers"] + spec["containers"]
        self.assertEqual([container["name"] for container in containers], ["prepare", "dns", "service", "grader"])
        for container in containers:
            with self.subTest(container=container["name"]):
                self.assertEqual(container["securityContext"], {
                    "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
                    "runAsNonRoot": True, "runAsUser": 1000})
                self.assertIn("limits", container["resources"])
                for mount in container["volumeMounts"]:
                    if mount["name"] in ("workspace", "runner", "grading"):
                        self.assertTrue(mount["readOnly"], mount)
        service = spec["initContainers"][2]
        self.assertEqual((service["name"], service.get("restartPolicy")), ("service", "Always"))  # a sidecar
        # The group's services get the limits of a participant server.
        self.assertEqual(service["resources"]["limits"], {"cpu": "2", "memory": "2G"})
        self.assertNotIn("restartPolicy", spec["initContainers"][0])
        self.assertEqual(spec["containers"][0]["command"][-8:], [
            "--track", "intermediate", "--kind", "tests", "--wait", "120", "--timeout", "600"])

    def test_pods_copy_the_group_s_code_only_once_their_network_rules_are_in_force(self):
        for egress in ("none", "participant"):
            with self.subTest(egress=egress):
                self.cluster = FakeCluster()
                self.start(egress=egress)
                prepare = self.pod("group_01")["spec"]["initContainers"][0]
                self.assertEqual(prepare["name"], "prepare")
                self.assertEqual(prepare["command"][-2:], ["--policy-wait", "60"])
                # The check also asks the kubelet on the pod's node, which answers while the API is down.
                self.assertEqual(prepare["env"], [
                    {"name": "HOST_IP", "valueFrom": {"fieldRef": {"fieldPath": "status.hostIP"}}}])

    def test_pods_without_network_answer_name_lookups_themselves(self):
        self.start(egress="none")
        spec = self.pod("group_01")["spec"]
        self.assertEqual((spec["dnsPolicy"], spec["dnsConfig"]), ("None", {"nameservers": ["127.0.0.1"]}))
        # The dns container answers on 127.0.0.1:53, a port that uid 1000 may open in this pod.
        self.assertEqual(spec["securityContext"]["sysctls"],
                         [{"name": "net.ipv4.ip_unprivileged_port_start", "value": "53"}])
        dns = spec["initContainers"][1]
        self.assertEqual((dns["name"], dns["restartPolicy"], dns["command"][5]), ("dns", "Always", "dns"))
        # The group's services start once it answers.
        self.assertEqual(dns["startupProbe"]["exec"]["command"], ["test", "-f", "/queries/ready"])
        self.assertEqual(spec["initContainers"][2]["name"], "service")
        self.assertEqual({mount["name"]: mount["readOnly"] for mount in dns["volumeMounts"]},
                         {"queries": False, "runner": True})
        self.cluster = FakeCluster()
        self.start(egress="participant")
        spec = self.pod("group_01")["spec"]
        self.assertNotIn("dnsPolicy", spec)  # the cluster DNS, as in participant servers
        self.assertNotIn("dnsConfig", spec)
        self.assertNotIn("sysctls", spec["securityContext"])
        self.assertEqual([container["name"] for container in spec["initContainers"]], ["prepare", "service"])
        self.assertNotIn("queries", [volume["name"] for volume in spec["volumes"]])

    def test_only_the_grader_sees_the_grading_files_and_the_results(self):
        self.start(kind="audit", bundle=pack(dict(FILES, **{"audit_a1.py": "print('audit')\n"})))
        spec = self.pod("group_01")["spec"]
        volumes = {volume["name"]: volume for volume in spec["volumes"]}
        self.assertEqual(volumes["grading"]["configMap"], {"name": f"grading-{RUN}-bundle"})
        self.assertEqual(volumes["runner"]["configMap"]["items"], [
            {"key": "grading-pod.py", "path": "grading-pod.py"}, {"key": "manifest.json", "path": "manifest.json"}])
        mounts = {container["name"]: {mount["name"]: mount for mount in container["volumeMounts"]}
                  for container in spec["initContainers"] + spec["containers"]}
        self.assertEqual(sorted(mounts["service"]), ["home", "network", "runner", "workspace"])
        self.assertEqual(sorted(mounts["prepare"]), ["home", "runner", "source", "workspace"])
        self.assertEqual(sorted(mounts["dns"]), ["queries", "runner"])
        self.assertEqual(sorted(mounts["grader"]), ["grading", "network", "queries", "results", "source"])
        self.assertTrue(mounts["grader"]["source"]["readOnly"])
        self.assertTrue(mounts["grader"]["queries"]["readOnly"])
        # The group's processes write down their network use; the grader only reads it.
        self.assertEqual((mounts["service"]["network"]["readOnly"], mounts["grader"]["network"]["readOnly"]),
                         (False, True))
        self.assertEqual(volumes["network"], {"name": "network", "emptyDir": {"sizeLimit": "16Mi"}})
        # The group's code runs in the service container: no grading files, no results.
        for name in ("grading", "results", "source"):
            self.assertNotIn(name, mounts["service"])

    def test_network_policy_blocks_ingress_and_keeps_participant_egress_off_the_cluster(self):
        answer = self.start(egress="participant")
        policy = self.cluster.objects["networkpolicy"][f"grading-{RUN}"]["spec"]
        self.assertEqual(policy["podSelector"], {"matchLabels": {"digitafrica.io/grading-run": RUN}})
        self.assertEqual(policy["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(policy["ingress"], [])
        dns, internet = policy["egress"]
        self.assertEqual(dns, {"ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
                               "to": [{"namespaceSelector": {"matchLabels": {
                                   "kubernetes.io/metadata.name": "kube-system"}}}]})
        block = internet["to"][0]["ipBlock"]
        self.assertEqual(block["cidr"], "0.0.0.0/0")
        # The private, shared and link-local ranges, and the nodes' public addresses; the
        # private and IPv6 node addresses are blocked anyway or not covered by the rule.
        self.assertEqual(sorted(block["except"]), [
            "10.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
            "203.0.113.10/32", "203.0.113.11/32"])
        self.assertEqual(answer["unreachable"], ["203.0.113.10/32", "203.0.113.11/32"])
        # The Kubernetes API can answer on an address that no node has, such as a load balancer.
        self.cluster = FakeCluster()
        self.cluster.state["endpoints"]["subsets"][0]["addresses"] = [{"ip": "198.51.100.7"}]
        self.start(egress="participant")
        block = self.cluster.objects["networkpolicy"][f"grading-{RUN}"]["spec"]["egress"][1]["to"][0]["ipBlock"]
        self.assertIn("198.51.100.7/32", block["except"])
        # A cluster on a private network needs no addresses of its own in the list.
        self.cluster = FakeCluster()
        del self.cluster.objects["node"]["worker1"]
        self.cluster.objects["node"]["central"]["status"]["addresses"][0]["address"] = "10.0.0.4"
        self.cluster.state["endpoints"]["subsets"][0]["addresses"] = [{"ip": "10.0.0.4"}]
        self.assertEqual(self.start(egress="participant")["unreachable"], [])
        self.cluster = FakeCluster()
        self.assertEqual(self.start(egress="none")["unreachable"], [])
        self.assertEqual(self.cluster.objects["networkpolicy"][f"grading-{RUN}"]["spec"]["egress"], [])
        self.assertFalse([command for command in self.cluster.commands if "node" in command])

    # ---- steps

    def test_steps_start_the_next_pods_collect_results_and_delete_saved_pods(self):
        self.start()
        first = f"grading-{RUN}-group-01"
        self.cluster.state["logs"][f"{first}/service"] = "[shortener] Running on http://127.0.0.1:5000\n"
        self.cluster.finish(first, log=tests_result(earned=9))
        answer = self.execute("step", run=RUN, saved=[])
        self.assertEqual(answer["groups"], {"group_01": "done", "group_02": "pending", "group_03": "pending"})
        result = answer["results"]["group_01"]
        self.assertEqual(json.loads(result["results"]["files"]["tests.json"])["earned"], 9)
        self.assertIn("Running on", result["logs"]["service"])
        self.assertEqual(result["logs"]["grader"], "[runner] done")
        self.assertIn(first, self.cluster.pods())  # kept until the organiser has saved it
        answer = self.execute("step", run=RUN, saved=["group_01"])
        self.assertNotIn(first, self.cluster.pods())
        self.assertEqual(answer["groups"]["group_01"], "saved")
        self.assertEqual(answer["results"], {})

    def test_pods_that_fail_or_hang_are_reported_with_their_events(self):
        self.start(parallel=3)
        one, two, three = (f"grading-{RUN}-group-0{number}" for number in (1, 2, 3))
        self.cluster.finish(one, phase="Failed", reason="DeadlineExceeded", message="too long")
        self.cluster.state["events"][one] = [{"type": "Warning", "reason": "DeadlineExceeded", "message": "x"}]
        self.cluster.objects["pod"][two]["status"] = {"phase": "Pending", "initContainerStatuses": [
            {"name": "prepare", "state": {"waiting": {"reason": "ImagePullBackOff", "message": "no such image"}}}]}
        self.cluster.objects["pod"][three]["status"] = {"phase": "Pending", "conditions": [
            {"type": "PodScheduled", "status": "False", "message": "0/3 nodes are available"}]}
        answer = self.execute("step", run=RUN, saved=[])
        self.assertEqual(answer["groups"], {"group_01": "failed", "group_02": "pending", "group_03": "pending"})
        self.assertEqual(answer["results"]["group_01"]["events"], ["Warning DeadlineExceeded: x"])
        self.assertIsNone(answer["results"]["group_01"]["results"])
        self.cluster.state["now"] += 700
        answer = self.execute("step", run=RUN, saved=["group_01"])
        self.assertEqual(answer["groups"], {"group_01": "saved", "group_02": "stuck", "group_03": "stuck"})
        self.assertIn("ImagePullBackOff", answer["results"]["group_02"]["reason"])
        self.assertIn("not scheduled: 0/3 nodes", answer["results"]["group_03"]["reason"])

    def test_a_pod_that_cannot_be_created_is_reported_for_its_group(self):
        self.start(parallel=1)
        self.cluster.finish(f"grading-{RUN}-group-01", log=tests_result())
        self.cluster.state["fail"] = ["create -f -"]
        answer = self.execute("step", run=RUN, saved=[])
        self.assertEqual(answer["groups"]["group_02"], "not started")
        self.assertIn("Cannot create Pod", answer["results"]["group_02"]["reason"])

    def test_a_damaged_results_block_counts_as_no_results(self):
        self.start(parallel=1)
        name = f"grading-{RUN}-group-01"
        log = tests_result().splitlines()
        log[3] = "!!!" + log[3][3:]
        self.cluster.finish(name, log="\n".join(log))
        answer = self.execute("step", run=RUN, saved=[])
        self.assertIsNone(answer["results"]["group_01"]["results"])

    def test_service_logs_keep_their_start_and_their_end(self):
        self.start(parallel=1)
        name = f"grading-{RUN}-group-01"
        self.cluster.finish(name, log=tests_result())
        lines = ["[shortener] Traceback at start-up"] + [f"[shortener] request {n}" for n in range(5000)]
        self.cluster.state["logs"][f"{name}/service"] = "\n".join(lines) + "\n"
        log = self.execute("step", run=RUN, saved=[])["results"]["group_01"]["logs"]["service"]
        self.assertTrue(log.startswith("[shortener] Traceback at start-up\n"))
        self.assertIn("[... the middle of the log is left out ...]", log)
        self.assertTrue(log.endswith("[shortener] request 4999\n"))
        self.assertLess(len(log), 130000)

    def test_a_finished_pod_is_kept_until_its_results_can_be_read(self):
        self.start(parallel=1)
        name = f"grading-{RUN}-group-01"
        self.cluster.finish(name, log=tests_result(earned=7))
        self.cluster.state["fail"] = [f"logs {name} -c grader"]
        answer = self.execute("step", run=RUN, saved=[])
        self.assertEqual(answer["groups"]["group_01"], "running")
        self.assertEqual(answer["groups"]["group_02"], "waiting")  # the pod still counts
        self.assertEqual(answer["results"], {})
        self.cluster.state["fail"] = []
        answer = self.execute("step", run=RUN, saved=[])
        self.assertEqual(json.loads(answer["results"]["group_01"]["results"]["files"]["tests.json"])["earned"], 7)
        # A log that never becomes readable is reported once the pod's deadline is long past.
        self.cluster.state["fail"] = [f"logs {name} -c grader"]
        self.cluster.state["now"] += 1020 + 600
        answer = self.execute("step", run=RUN, saved=[])
        self.assertIsNone(answer["results"]["group_01"]["results"])

    def test_a_pod_that_hangs_in_deletion_stops_neither_steps_nor_cleanup(self):
        self.start()
        self.cluster.finish(f"grading-{RUN}-group-01", log=tests_result())
        self.cluster.state["fail"] = ["delete pod"]
        answer = self.execute("step", run=RUN, saved=["group_01"])
        self.assertEqual(answer["groups"]["group_01"], "saved")
        answer = self.execute("cleanup", run=RUN)
        self.assertEqual(len(answer["errors"]), 1)
        self.assertEqual(sorted(answer["left"]), ["pod"])
        # The NetworkPolicy and the ConfigMaps are gone; the lock's owner references take the pods along.
        self.assertEqual(self.run_objects()["configmap"], [])
        self.assertEqual(self.run_objects()["networkpolicy"], [])

    def test_steps_show_that_the_run_is_followed(self):
        self.start()
        self.assertEqual(self.execute("status")["lock"]["idle"], 0)
        self.cluster.state["now"] += 700
        self.assertEqual(self.execute("status")["lock"]["idle"], 700)
        self.execute("step", run=RUN, saved=[])
        self.assertEqual(self.execute("status")["lock"]["idle"], 0)

    def test_steps_refuse_a_run_that_is_gone(self):
        with self.assertRaisesRegex(RuntimeError, "no longer in the cluster"):
            self.execute("step", run=RUN, saved=[])

    # ---- cleanup

    def test_cleanup_removes_everything_of_the_run_and_nothing_else(self):
        self.start()
        self.cluster.add("pod", "jupyter-group-5f01")
        answer = self.execute("cleanup", run=RUN)
        self.assertEqual(answer["deleted"], {"pod": 2, "networkpolicy": 1, "configmap": 2})
        self.assertEqual((answer["left"], answer["errors"]), ({}, []))
        self.assertEqual(self.run_objects(), {"configmap": [], "pvc": [], "pod": [], "networkpolicy": [], "node": []})
        self.assertIn("jupyter-group-5f01", self.cluster.objects["pod"])
        self.assertIn("digitafrica-workshop-state", self.cluster.objects["configmap"])
        self.assertEqual(len(self.cluster.objects["pvc"]), 5)
        # Nothing to remove is fine; another run's lock is not.
        self.assertEqual(self.execute("cleanup", run=RUN)["deleted"], {"pod": 0, "networkpolicy": 0, "configmap": 0})
        self.cluster.add("configmap", "digitafrica-grading-run", data={"run": "ffff0000"})
        with self.assertRaisesRegex(RuntimeError, "ffff0000"):
            self.execute("cleanup", run=RUN)

    def test_the_answer_is_one_framed_block(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            remote.answer({"run": RUN, "groups": {"group_01": "pending"}})
        printed = output.getvalue().splitlines()
        self.assertEqual(printed[0], remote.BEGIN)
        self.assertEqual(printed[-1], remote.END)
        self.assertTrue(all(len(line) <= 76 for line in printed[1:-1]))
        decoded = json.loads(gzip.decompress(base64.b64decode("".join(printed[1:-1]))))
        self.assertEqual(decoded["run"], RUN)

    def test_results_block_is_found_between_other_log_lines(self):
        log = "before\n" + results_log({"kind": "tests"}, {"tests.txt": "x"}) + "after\n"
        block, other = remote.results_block(log)
        self.assertEqual(block["files"], {"tests.txt": "x"})
        self.assertEqual(other, ["before", "[runner] done", "after"])


if __name__ == "__main__":
    unittest.main()
