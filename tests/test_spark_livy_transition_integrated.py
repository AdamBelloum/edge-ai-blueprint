# Offline only: real adapter/planner/executor with fake Docker responses.
# Success fixtures stub only archive verification; real checksum refusal is tested.
from contextlib import contextmanager, redirect_stderr
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml
import test_spark_livy_candidate_verify as candidate_fixture
import test_spark_livy_transition as plan_fixture
from test_spark_teardown_validation import validator as v

HELPERS = Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark"
sys.path.insert(0, str(HELPERS))
import livy_transition_live as live
import livy_transition_docker as adapter
import livy_candidate_verify as verify


class FakeDocker:
    def __init__(self, baseline, candidate, dockerfile):
        self.baseline, self.candidate, self.dockerfile = baseline, candidate, dockerfile
        self.state, self.master, self.images, self.hashes = plan_fixture.fixture()
        self.hashes.update({"spark-livy": "6" * 64, "spark-livy-access": "7" * 64})
        self.calls, self.mutations = [], []
        self.fail_start = self.bad_image = self.bad_candidate = self.bad_probe = False
        self.change_daemon = False
        self.daemon_calls = 0
        self.on_config = None
        self.inventory = {kind: {"total": 0, "sessions": []}
                          for kind in ("sessions", "batches")}

    def add_services(self):
        containers, networks, _ = self.state
        present = {c["Config"]["Labels"]["com.docker.compose.service"]
                   for c in containers}
        if "spark-livy" not in present:
            livy = deepcopy(next(c for c in containers
                if c["Config"]["Labels"]["com.docker.compose.service"] == "spark-master"))
            livy.update(Id="e" * 64, Name="/" + v.PROJECT + "-spark-livy-1",
                        Image=self.images[adapter.LIVY_IMAGE])
            livy["Config"]["Image"] = adapter.LIVY_IMAGE
            livy["Config"]["Labels"].update({
                "com.docker.compose.service": "spark-livy",
                "com.docker.compose.config-hash": self.hashes["spark-livy"],
                "com.docker.compose.project.config_files": adapter.TRANSITION_CONFIG})
            livy["Mounts"] = [dict(Type="bind", RW=False, Source=s, Destination=d)
                             for s, d in sorted({v.DATA_MOUNT} | v.TRANSITION_LIVY_MOUNTS)]
            livy["HostConfig"] = dict(Memory=2147483648, PortBindings={}, NetworkMode=v.NETWORK)
            containers.append(livy)
            for network in networks:
                if network["Name"] == v.NETWORK:
                    network["Containers"][livy["Id"]] = {}
        if self.fail_start:
            raise subprocess.CalledProcessError(1, ["fake-start"], stderr="DO-NOT-LEAK")
        if "spark-livy-access" not in present:
            gateway_state, _, _, _ = plan_fixture.fixture(gateway=True)
            gateway = deepcopy(next(c for c in gateway_state[0]
                if c["Config"]["Labels"]["com.docker.compose.service"] == "spark-livy-access"))
            source_gateway_id = gateway["Id"]
            gateway["Id"] = "a1" * 32
            assert gateway["Id"] not in {c["Id"] for c in containers}
            gateway["Config"]["Labels"].update({
                "com.docker.compose.config-hash": self.hashes["spark-livy-access"],
                "com.docker.compose.project.config_files": adapter.TRANSITION_CONFIG})
            gateway["Image"] = self.images[adapter.PARTICIPANT_IMAGE]
            containers.append(gateway)
            for network in networks:
                source = next(n for n in gateway_state[1] if n["Name"] == network["Name"])
                if source_gateway_id in source["Containers"]:
                    network["Containers"][gateway["Id"]] = deepcopy(
                        source["Containers"][source_gateway_id])

    def fake_run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[:3] != adapter.PREFIX:
            raise AssertionError("Non-local Docker invocation")
        args = argv[3:]
        containers, networks, volumes = self.state
        if len({c["Id"] for c in containers}) != len(containers):
            raise AssertionError("Duplicate simulated container IDs")
        if args[0] == "compose":
            if "config" in args and "--hash" in args:
                out = "\n".join(f"{k} {value}" for k, value in self.hashes.items())
            elif "config" in args:
                text = yaml.safe_load(kwargs["input"])
                if self.bad_candidate and "spark-livy" in text["services"]:
                    text["services"]["spark-master"]["cpus"] = 999
                if self.on_config:
                    callback, self.on_config = self.on_config, None
                    callback()
                out = json.dumps(text)
            elif "up" in args:
                self.mutations.append(("start", tuple(args[args.index("never") + 1:])))
                self.add_services()
                out = ""
            else:
                raise AssertionError(args)
        elif args[0] == "info":
            self.daemon_calls += 1
            out = ("changed" if self.change_daemon and self.daemon_calls > 2
                   else "reviewed-daemon")
        elif args[:2] == ["image", "inspect"]:
            reference = args[-1]
            record = {"Id": self.images[reference], "Os": "linux",
                      "Architecture": "amd64", "RepoTags": [reference],
                      "RepoDigests": [reference], "Config": {}}
            if reference == adapter.LIVY_IMAGE:
                record["Config"] = {
                    "User": "185:0", "Cmd": ["/opt/livy/bin/livy-server"],
                    "Env": ["LIVY_SERVER_START_MODE=foreground"], "Labels": {
                        "org.digitafrica.livy.archive-sha512": verify.ARCHIVE_SHA512,
                        "org.digitafrica.livy.dockerfile-sha512":
                            hashlib.sha512(self.dockerfile).hexdigest(),
                        "org.digitafrica.livy.spark-base": adapter.CLIENT_IMAGE}}
                if self.bad_image:
                    record["Config"]["Labels"]["org.digitafrica.livy.archive-sha512"] = "wrong"
            out = json.dumps([record])
        elif args[:2] == ["container", "ls"]:
            out = ("\n".join(c["Id"] for c in containers)
                   if args[-1].startswith("label=com.docker.compose.project=") else "")
        elif args[:2] == ["network", "ls"]:
            out = "\n".join(n["Id"] for n in networks)
        elif args[:2] == ["volume", "ls"]:
            out = "\n".join(volumes)
        elif args[:2] in (["container", "inspect"], ["network", "inspect"]):
            records = containers if args[0] == "container" else networks
            out = json.dumps([next(c for c in records if c["Id"] == identifier)
                              for identifier in args[2:]])
        elif args[:2] == ["container", "stop"]:
            target = next(c for c in containers if c["Id"] == args[-1])
            if target["Config"]["Labels"]["com.docker.compose.service"] != "spark-client":
                raise AssertionError("Stopped a shared service")
            self.mutations.append(("stop", args[-1]))
            target["State"]["Running"] = False
            out = args[-1]
        elif args[0] == "exec":
            probe = args[-1]
            if probe == adapter.MASTER_PROBE:
                out = json.dumps(self.master)
            elif probe == adapter.INVENTORY_PROBE:
                out = json.dumps(self.inventory)
            elif probe in (adapter.HEAP_PROBE, adapter.GATEWAY_PROBE):
                if self.bad_probe:
                    raise subprocess.CalledProcessError(1, ["fake-probe"], stderr="DO-NOT-LEAK")
                out = "read-only readiness probe verified"
            else:
                raise AssertionError("Unknown probe")
        else:
            raise AssertionError(args)
        return SimpleNamespace(stdout=out)


class IntegratedTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.runtime, self.bundle, self.evidence = [
            self.base / name for name in ("runtime", "bundle", "evidence")]
        for directory in (self.runtime, self.bundle, self.evidence):
            directory.mkdir(mode=0o700)
        fixture = candidate_fixture.CandidateVerificationTests()
        fixture.setUp()
        self.baseline, self.candidate = fixture.baseline, fixture.candidate
        self.files = dict(fixture.files)
        self.files["compose.livy-transition.yaml"] = yaml.safe_dump(self.candidate).encode()
        self.reviewed = {k: value for k, value in self.files.items() if k != verify.ARCHIVE}
        self.write(self.runtime / "compose.yaml",
                   yaml.safe_dump(self.baseline).encode(), 0o640)
        for name, mode in live.FILES.items():
            self.write(self.runtime / name, self.files[name], mode)
            self.write(self.bundle / name, self.files[name], 0o600)
        self.write(self.bundle / "reviewed-assets.json",
                   json.dumps({k: value.decode() for k, value in self.reviewed.items()}).encode(),
                   0o600)
        self.fake = FakeDocker(self.baseline, self.candidate,
                               self.files["livy-transition/livy-build/Dockerfile"])

    def write(self, path, value, mode):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(value)
        path.chmod(mode)

    @contextmanager
    def directory(self, path):
        fd = os.open(path, live.FLAGS)
        try:
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def lock(self):
        yield 123

    @contextmanager
    def evidence_context(self):
        with self.directory(self.evidence) as fd:
            yield live.Evidence(fd, "offline-test")

    def execute(self, *, checksum_stub=True, **overrides):
        options = dict(
            maintenance_confirmed=True, submissions_paused=True,
            bundle_context=lambda _: self.directory(self.bundle),
            runtime_context=lambda: self.directory(self.runtime),
            submission_lock=self.lock, evidence_context=self.evidence_context,
            owner_uid=os.getuid(),
            delivery_reader=lambda fd: live.read_delivery(fd, owner_uid=os.getuid()),
            engine=lambda **kwargs: adapter.transition_with_docker(
                **kwargs, run=self.fake.fake_run, sleep=lambda _: None))
        options.update(overrides)
        with patch.object(live.os, "geteuid", return_value=0):
            if checksum_stub:
                with patch.object(verify, "verify_archive", return_value=None):
                    return live.run_transition("test-only-bundle", **options)
            return live.run_transition("test-only-bundle", **options)

    def events(self):
        return [json.loads(p.read_text()) for p in sorted(self.evidence.glob("*.json"))]

    def test_real_round_trip_and_completed_runtime_retry(self):
        shared = {c["Config"]["Labels"]["com.docker.compose.service"]: c["Id"]
                  for c in self.fake.state[0]
                  if c["Config"]["Labels"]["com.docker.compose.service"]
                  in {"spark-master", "spark-worker-1"}}
        networks = [(n["Name"], n["Id"]) for n in self.fake.state[1]]
        result = self.execute()
        self.assertEqual(result["status"], "runtime-transition-verified")
        self.assertEqual(result["preserved_shared_ids"], shared)
        self.assertEqual(result["participant_readiness"], "not-established-by-this-executor")
        self.assertEqual([m[0] for m in self.fake.mutations], ["stop", "start"])
        self.assertEqual(self.fake.mutations[-1][1], ("spark-livy", "spark-livy-access"))
        self.assertEqual([(n["Name"], n["Id"]) for n in self.fake.state[1]], networks)
        self.assertEqual([e["event"] for e in self.events()],
            ["planned", "stopping-direct-client", "starting-livy-services",
             "runtime-transition-verified"])
        for path in self.evidence.glob("*.json"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.evidence = self.base / "retry-evidence"
        self.evidence.mkdir(mode=0o700)
        self.fake.mutations.clear()
        self.assertFalse(self.execute()["changed"])
        self.assertEqual(self.fake.mutations, [])

    def test_acknowledgements_refuse_before_evidence_or_docker(self):
        for key in ("maintenance_confirmed", "submissions_paused"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.execute(**{key: False})
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.events(), [])

    def test_absent_shared_lock_refuses_before_docker(self):
        @contextmanager
        def missing():
            yield None
        with self.assertRaises(ValueError):
            self.execute(submission_lock=missing)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.events()[-1]["event"], "failed")

    def test_real_unlocked_archive_refuses_before_docker(self):
        with self.assertRaises(ValueError):
            self.execute(checksum_stub=False)
        self.assertEqual(self.fake.calls, [])

    def test_each_staged_file_must_be_present(self):
        (self.runtime / "livy-transition/livy.conf").unlink()
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.calls, [])

    def test_changed_staged_content_refuses(self):
        (self.runtime / "livy-transition/livy.conf").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.calls, [])

    def test_unprotected_mode_refuses(self):
        (self.runtime / "livy-transition/livy.conf").chmod(0o666)
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.calls, [])

    def test_symlink_refuses(self):
        target = self.runtime / "livy-transition/livy.conf"
        target.unlink()
        target.symlink_to(self.bundle / "livy-transition/livy.conf")
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.calls, [])

    def test_hardlink_refuses(self):
        os.link(self.runtime / "livy-transition/livy.conf", self.base / "extra-link")
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.calls, [])

    def test_baseline_replacement_before_stop_refuses(self):
        def replace():
            target = self.runtime / "compose.yaml"
            replacement = self.base / "replacement"
            self.write(replacement, target.read_bytes(), 0o640)
            os.replace(replacement, target)
        self.fake.on_config = replace
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.mutations, [])

    def test_reference_manifest_replacement_before_stop_refuses(self):
        def replace():
            target = self.bundle / "reviewed-assets.json"
            replacement = self.base / "replacement"
            self.write(replacement, target.read_bytes(), 0o600)
            os.replace(replacement, target)
        self.fake.on_config = replace
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.mutations, [])

    def test_active_master_refuses_without_mutation(self):
        self.fake.master["activeapps"] = ["app"]
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.mutations, [])

    def test_image_provenance_refuses_without_mutation(self):
        self.fake.bad_image = True
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.mutations, [])

    def test_compose_preservation_refuses_without_mutation(self):
        self.fake.bad_candidate = True
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.mutations, [])

    def test_configuration_hash_refuses_without_mutation(self):
        self.fake.state[0][0]["Config"]["Labels"]["com.docker.compose.config-hash"] = "f" * 64
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.mutations, [])

    def test_paused_shared_service_refuses_without_mutation(self):
        self.fake.state[0][0]["State"]["Paused"] = True
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.mutations, [])

    def test_daemon_drift_refuses_without_mutation(self):
        self.fake.change_daemon = True
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.mutations, [])

    def test_partial_start_retains_failure_without_rollback_or_retry(self):
        self.fake.fail_start = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute()
        self.assertEqual([m[0] for m in self.fake.mutations], ["stop", "start"])
        self.assertEqual(self.events()[-1]["event"], "failed")
        self.assertNotIn("DO-NOT-LEAK", json.dumps(self.events()))
        self.assertNotIn("runtime-transition-verified", [e["event"] for e in self.events()])

    def test_readiness_failure_does_not_claim_success(self):
        self.fake.bad_probe = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute()
        self.assertEqual(self.events()[-1]["phase"], "runtime-readiness")

    def test_existing_nonempty_livy_inventory_refuses(self):
        for container in self.fake.state[0]:
            if container["Config"]["Labels"]["com.docker.compose.service"] == "spark-client":
                container["State"]["Running"] = False
        self.fake.add_services()
        self.fake.inventory["sessions"] = {"total": 1, "sessions": [{"id": 1}]}
        with self.assertRaises(ValueError):
            self.execute()
        self.assertEqual(self.fake.mutations, [])

    def test_failed_evidence_does_not_mask_execution_error(self):
        self.fake.fail_start = True
        original = live.Evidence.record
        def record(instance, event, payload):
            if event == "failed":
                raise OSError("evidence failure")
            return original(instance, event, payload)
        with patch.object(live.Evidence, "record", record):
            with self.assertRaises(subprocess.CalledProcessError):
                self.execute()

    def test_cli_error_is_sanitised(self):
        output = io.StringIO()
        with patch.object(live, "run_transition", side_effect=RuntimeError("DO-NOT-LEAK")):
            with redirect_stderr(output):
                code = live.main(["/var/lib/digitafrica-livy-stage-test",
                                  "--maintenance-window-confirmed",
                                  "--submissions-paused-confirmed"])
        self.assertEqual(code, 1)
        self.assertNotIn("DO-NOT-LEAK", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["error_type"], "RuntimeError")

    def test_bundle_namespace_and_nonroot_refuse(self):
        with patch.object(live.os, "geteuid", return_value=0):
            for path in ("/tmp/bundle", "/var/lib/digitafrica-livy-stage-x/../y"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    with live.open_bundle(path):
                        pass
        with patch.object(live.os, "geteuid", return_value=1000):
            with self.assertRaises(ValueError):
                live.run_transition("/var/lib/digitafrica-livy-stage-test",
                                    maintenance_confirmed=True, submissions_paused=True)


if __name__ == "__main__":
    unittest.main()
