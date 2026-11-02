# Offline only. Real exercise/access helpers; fake HTTP and managed forwarding.
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/workshops/big-data/spark/participant-livy-verify.py"


def load():
    spec = importlib.util.spec_from_file_location("_participant_verifier_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ParticipantVerificationTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(socket, "socket",
            side_effect=AssertionError("Network forbidden in offline tests"))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.v = load()
        self.exercise, self.access = self.v.load_modules()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.workspace = self.base / "workspace"
        (self.workspace / "data").mkdir(parents=True)
        self.csv = self.workspace / "data/Bank_Personal_Loan_Modelling.csv"
        self.csv.write_bytes(b"ID,Income\n1,10\n2,20\n")
        self.events, self.calls, self.records = [], [], []
        self.gone = self.delete_attempted = False
        self.active = self.post_active = self.bad_dataset = False
        self.creation_error = self.wait_error = self.cleanup_error = None
        self.creation_id = 41
        self.observed = dict(deepcopy(self.v.EXPECTED), application_id="app-123")
        self.now = 0
        self.expire_after_creation = False
        self.close_error = False
        self.statement = None
        self.exercise.livy_request = self.http
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("LIVY_URL", None)
        os.environ.pop("LIVY_DATA_PATH", None)

    def http(self, base, method, path, payload=None):
        self.calls.append((method, path, deepcopy(payload)))
        if path.startswith(("/sessions?", "/batches?")):
            total = int(self.active or (self.post_active and self.gone))
            return {"total": total, "sessions": [] if not total else [{"id": 99}]}
        if method == "POST" and path == "/sessions":
            if self.creation_error:
                raise self.creation_error
            if self.expire_after_creation:
                self.now = 240
            return {"id": self.creation_id}
        if method == "POST" and path == "/sessions/41/statements":
            self.statement = payload["code"]
            return {"id": 73}
        if method == "GET" and path == "/sessions/41/statements/73":
            if self.access.DATA_MARKER in self.statement:
                digest = hashlib.sha256(self.csv.read_bytes()).hexdigest()
                result = {"path": self.access.DATA_CANDIDATE,
                          "sha256": "wrong" if self.bad_dataset else digest,
                          "executors": [{"host": "spark-worker-1", "sha256": digest}]}
                text = self.access.DATA_MARKER + json.dumps(result)
            else:
                text = self.v.MARKER + json.dumps(self.observed)
            return {"state": "available",
                    "output": {"status": "ok", "data": {"text/plain": text}}}
        if method == "DELETE" and path == "/sessions/41":
            self.delete_attempted = True
            if self.cleanup_error:
                raise self.cleanup_error
            self.gone = True
            return {}
        if method == "GET" and path == "/sessions/41":
            if self.gone:
                raise HTTPError(base + path, 404, "gone", {}, None)
            if self.delete_attempted and self.cleanup_error:
                raise HTTPError(base + path, 500, "DO-NOT-LEAK", {}, None)
            if self.wait_error:
                error, self.wait_error = self.wait_error, None
                raise error
            return {"state": "idle"}
        raise AssertionError((method, path))

    @contextmanager
    def connection(self):
        self.events.append("forwarding-open")
        try:
            yield {"LIVY_URL": "http://127.0.0.1:12345",
                   "LIVY_DATA_PATH": self.access.DATA_CANDIDATE,
                   "VERIFY_DATASET": True}
        finally:
            self.events.append("forwarding-closed")
            if self.close_error:
                raise RuntimeError("DO-NOT-LEAK")

    def emit(self, event, payload):
        self.records.append((event, deepcopy(payload)))

    def run_probe(self, **overrides):
        arguments = dict(workspace=self.workspace, exercise=self.exercise,
            access=self.access, connection=self.connection, emit=self.emit,
            maintenance_confirmed=True, submissions_paused=True, clock=lambda: self.now)
        arguments.update(overrides)
        with redirect_stdout(io.StringIO()):
            return self.v.verify(**arguments)

    def test_success_real_helpers_bounded_payload_owned_cleanup_and_close(self):
        original = self.exercise.livy_request
        result = self.run_probe()
        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["observed"], self.observed)
        self.assertEqual(result["cleanup"], "owned-session-http-404-confirmed")
        self.assertTrue(result["forwarding_closed"])
        self.assertIs(self.exercise.livy_request, original)
        creations = [c for c in self.calls if c[:2] == ("POST", "/sessions")]
        self.assertEqual(len(creations), 1)
        payload = creations[0][2]
        self.assertEqual(payload["driverMemory"], "512m")
        self.assertEqual(payload["executorMemory"], "512m")
        self.assertEqual(payload["executorCores"], 1)
        self.assertEqual(payload["numExecutors"], 1)
        self.assertEqual(payload["conf"], self.v.PAYLOAD["conf"])
        self.assertEqual([c[1] for c in self.calls if c[0] == "DELETE"], ["/sessions/41"])
        self.assertEqual(self.events, ["forwarding-open", "forwarding-closed"])
        self.assertEqual(self.records[-1][0], "verification-finished")
        self.assertLess(len(self.calls), 20)

    def test_acknowledgements_refuse_before_forwarding_or_requests(self):
        for key in ("maintenance_confirmed", "submissions_paused"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_probe(**{key: False})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.events, [])

    def test_even_empty_explicit_override_refuses(self):
        os.environ["LIVY_URL"] = ""
        with self.assertRaises(ValueError):
            self.run_probe()
        self.assertEqual(self.calls, [])

    def test_existing_work_refuses_before_creation(self):
        self.active = True
        result = self.run_probe()
        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(result["session_request_sent"])
        self.assertFalse(self.delete_attempted)

    def test_creation_timeout_never_guesses_an_id_or_retries(self):
        self.creation_error = TimeoutError("DO-NOT-LEAK")
        result = self.run_probe()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["cleanup"], "creation-outcome-unknown-no-id-do-not-retry")
        self.assertIsNone(result["session_id"])
        self.assertFalse(self.delete_attempted)
        self.assertEqual(sum(c[:2] == ("POST", "/sessions") for c in self.calls), 1)
        self.assertNotIn("DO-NOT-LEAK", json.dumps(self.records))

    def test_boolean_creation_id_is_not_owned(self):
        self.creation_id = True
        result = self.run_probe()
        self.assertEqual(result["status"], "FAILED")
        self.assertIsNone(result["session_id"])
        self.assertFalse(self.delete_attempted)

    def test_interruption_after_owned_id_still_cleans_only_that_id(self):
        self.wait_error = KeyboardInterrupt()
        result = self.run_probe()
        self.assertEqual(result["error_type"], "KeyboardInterrupt")
        self.assertTrue(self.gone)
        self.assertTrue(result["forwarding_closed"])

    def test_budget_expiry_after_creation_still_allows_owned_cleanup(self):
        self.expire_after_creation = True
        result = self.run_probe()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["error_type"], "TimeoutError")
        self.assertTrue(self.gone)

    def test_dataset_mismatch_cleans_owned_session(self):
        self.bad_dataset = True
        result = self.run_probe()
        self.assertEqual(result["status"], "FAILED")
        self.assertTrue(self.gone)
        self.assertNotIn("observed", result)

    def test_wrong_worker_and_extra_output_fields_refuse(self):
        self.observed["worker_hosts"] = ["spark-livy"]
        self.observed["private"] = "DO-NOT-LEAK"
        result = self.run_probe()
        self.assertEqual(result["status"], "FAILED")
        self.assertTrue(self.gone)
        self.assertNotIn("DO-NOT-LEAK", json.dumps(self.records))

    def test_uncertain_cleanup_never_passes(self):
        self.cleanup_error = RuntimeError("DO-NOT-LEAK")
        result = self.run_probe()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["cleanup"], "unconfirmed-inspect-owned-id-before-retry")
        self.assertNotIn("DO-NOT-LEAK", json.dumps(self.records))

    def test_cleanup_failure_does_not_replace_original_verification_failure(self):
        self.bad_dataset = True
        self.cleanup_error = RuntimeError("DO-NOT-LEAK")
        result = self.run_probe()
        self.assertEqual(result["error_type"], "RuntimeError")
        self.assertEqual(result["failure_phase"], "dataset-verification")
        self.assertIn("cleanup_error_type", result)

    def test_post_cleanup_nonempty_inventory_refuses(self):
        self.post_active = True
        result = self.run_probe()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failure_phase"], "post-cleanup-inventory")
        self.assertTrue(self.gone)

    def test_uncertain_forwarding_close_refuses(self):
        self.close_error = True
        result = self.run_probe()
        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(result["forwarding_closed"])
        self.assertTrue(self.gone)

    def test_owned_id_evidence_failure_still_cleans(self):
        def emit(event, payload):
            if event == "owned-session-created":
                raise OSError("DO-NOT-LEAK")
            self.emit(event, payload)
        result = self.run_probe(emit=emit)
        self.assertEqual(result["status"], "FAILED")
        self.assertTrue(self.gone)
        self.assertEqual(result["error_type"], "OSError")

    def test_final_evidence_failure_preserves_original_failure(self):
        self.active = True
        def emit(event, payload):
            if event == "verification-finished":
                raise OSError("DO-NOT-LEAK")
            self.emit(event, payload)
        result = self.run_probe(emit=emit)
        self.assertEqual(result["error_type"], "ValueError")
        self.assertEqual(result["evidence_error_type"], "OSError")

    def test_final_evidence_failure_prevents_success(self):
        def emit(event, payload):
            if event == "verification-finished":
                raise OSError("DO-NOT-LEAK")
            self.emit(event, payload)
        result = self.run_probe(emit=emit)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failure_phase"], "final-evidence-recording")

    def test_private_exclusive_journal_and_symlink_refusal(self):
        directory = self.base / "evidence"
        directory.mkdir(mode=0o700)
        with self.v.Journal(directory) as journal:
            journal.record("test", {"session_id": 41})
            filename = directory / (journal.evidence_id + ".jsonl")
            self.assertEqual(filename.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(filename.read_text())["session_id"], 41)
        link = self.base / "evidence-link"
        link.symlink_to(directory, target_is_directory=True)
        with self.assertRaises(ValueError):
            with self.v.Journal(link):
                pass
        directory.chmod(0o755)
        with self.assertRaises(ValueError):
            with self.v.Journal(directory):
                pass

    def test_colocated_assets_are_pinned_before_execution(self):
        directory = self.base / "colocated"
        directory.mkdir()
        assets = ROOT / "workshop_assets/big-data/spark/beginner"
        for filename in self.v.ASSET_SHA256:
            shutil.copyfile(assets / filename, directory / filename)
        with patch.object(self.v, "__file__", str(directory / "participant-livy-verify.py")):
            self.assertEqual(len(self.v.load_modules()), 2)
            (directory / "02_spark_via_livy.py").write_text('raise RuntimeError("DO-NOT-EXECUTE")')
            with self.assertRaises(ValueError):
                self.v.load_modules()

    def test_expected_pin_and_credential_stability_are_enforced(self):
        home = self.base / "home"
        credentials = home / ".ssh/spark-direct"
        for directory in (home, home / ".ssh", credentials):
            directory.mkdir(mode=0o700)
        for filename, mode in (("login_key", 0o600), ("known_hosts", 0o644)):
            target = credentials / filename
            target.write_bytes(b"offline-fixture")
            target.chmod(mode)
        pins = SimpleNamespace(load=lambda _: None,
                               keys=lambda: ["[pilot.example]:2222"])
        paramiko = SimpleNamespace(HostKeys=lambda: pins)
        @contextmanager
        def managed(reader):
            yield {"LIVY_URL": "http://127.0.0.1:12345",
                   "LIVY_DATA_PATH": self.access.DATA_CANDIDATE,
                   "VERIFY_DATASET": True}
        with patch.object(self.v.Path, "home", return_value=home), \
             patch.dict(sys.modules, {"paramiko": paramiko}), \
             patch.object(self.access, "managed_connection", side_effect=managed) as opener:
            with self.assertRaises(ValueError):
                with self.v.managed_connection(self.access, "wrong.example", 2222):
                    pass
            opener.assert_not_called()
            with self.v.managed_connection(self.access, "pilot.example", 2222) as settings:
                self.assertTrue(settings["VERIFY_DATASET"])
            @contextmanager
            def changed(reader):
                (credentials / "login_key").write_bytes(b"changed")
                with managed(reader) as settings:
                    yield settings
            opener.side_effect = changed
            with self.assertRaises(ValueError):
                with self.v.managed_connection(self.access, "pilot.example", 2222):
                    pass

    def test_cli_exception_output_is_sanitised(self):
        directory = self.base / "cli-evidence"
        directory.mkdir(mode=0o700)
        output = io.StringIO()
        args = ["--workspace", str(self.workspace), "--evidence-dir", str(directory),
                "--expected-ssh-host", "pilot.example", "--expected-ssh-port", "2222",
                "--maintenance-window-confirmed", "--submissions-paused-confirmed"]
        with patch.object(self.v, "verify", side_effect=RuntimeError("DO-NOT-LEAK")), \
             redirect_stdout(io.StringIO()), redirect_stderr(output):
            code = self.v.main(args)
        self.assertEqual(code, 1)
        self.assertNotIn("DO-NOT-LEAK", output.getvalue())


if __name__ == "__main__":
    unittest.main()
