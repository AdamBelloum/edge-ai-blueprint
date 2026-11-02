"""Injected entry-point tests; no production filesystem or staging access."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

old_path = list(sys.path)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                         "scripts/workshops/big-data/spark"))
    import livy_candidate_deliver as delivery
finally:
    sys.path[:] = old_path

PATH = "/var/lib/digitafrica-livy-stage-test123"


class CandidateDeliverTests(unittest.TestCase):
    def test_non_root_is_refused_before_open(self):
        with patch.object(delivery.os, "geteuid", return_value=1000),              patch.object(delivery.os, "open") as opened:
            with self.assertRaises(PermissionError):
                with delivery.open_bundle(PATH):
                    self.fail("Unexpected bundle access")
            opened.assert_not_called()

    def test_arbitrary_or_traversing_paths_are_refused_before_open(self):
        with patch.object(delivery.os, "geteuid", return_value=0),              patch.object(delivery.os, "open") as opened:
            for path in ("/tmp/bundle", PATH + "/../other",
                         PATH + "/", "/var/lib/digitafrica-livy-stage-"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    with delivery.open_bundle(path):
                        self.fail("Unexpected bundle access")
            opened.assert_not_called()

    def test_protected_bundle_opens_nofollow_and_closes_on_caller_failure(self):
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        bundle = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
        with patch.object(delivery.os, "geteuid", return_value=0),              patch.object(delivery.os, "open", side_effect=range(10, 14)) as opened,              patch.object(delivery.os, "fstat",
                          side_effect=[directory, directory, directory, bundle]),              patch.object(delivery.os, "close") as closed:
            with self.assertRaisesRegex(RuntimeError, "caller failed"):
                with delivery.open_bundle(PATH) as fd:
                    self.assertEqual(fd, 13)
                    raise RuntimeError("caller failed")
            self.assertEqual([call.args[0] for call in opened.call_args_list],
                             ["/", "var", "lib", "digitafrica-livy-stage-test123"])
            self.assertTrue(all(call.args[1] & delivery.os.O_NOFOLLOW
                                for call in opened.call_args_list))
            self.assertEqual([call.args[0] for call in closed.call_args_list],
                             [13, 12, 11, 10])

    def test_delivery_reads_bundle_then_invokes_verified_stage(self):
        events = []
        files, reviewed = {"asset": b"data"}, {"asset": b"reference"}
        @contextmanager
        def bundle(path):
            self.assertEqual(path, PATH)
            events.append("open")
            try:
                yield 9
            finally:
                events.append("close")
        def reader(fd):
            self.assertEqual(fd, 9)
            events.append("read")
            return files, reviewed
        def stage(actual, *, reviewed_text_files):
            self.assertIs(actual, files)
            self.assertIs(reviewed_text_files, reviewed)
            events.append("stage")
            return ["created"]
        self.assertEqual(delivery.deliver_candidate(
            PATH, bundle_context=bundle, reader=reader, stage=stage), ["created"])
        self.assertEqual(events, ["open", "read", "close", "stage"])

    def test_reader_failure_prevents_staging(self):
        @contextmanager
        def bundle(path):
            yield 9
        def reader(fd):
            raise ValueError("invalid delivery")
        with patch.object(delivery, "stage_verified_candidate") as stage:
            with self.assertRaisesRegex(ValueError, "invalid delivery"):
                delivery.deliver_candidate(
                    PATH, bundle_context=bundle, reader=reader, stage=stage)
            stage.assert_not_called()

    def test_missing_confirmation_and_unknown_options_prevent_delivery(self):
        with patch.object(delivery, "deliver_candidate") as deliver:
            for args in ([PATH], [PATH, "--maintenance-window-confirmed", "--unknown"]):
                with self.subTest(args=args), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        delivery.main(args)
                    self.assertEqual(error.exception.code, 2)
            deliver.assert_not_called()

    def test_cli_success_reports_staging_not_runtime_readiness(self):
        output = io.StringIO()
        with patch.object(delivery, "deliver_candidate", return_value=["created"]) as deliver,              redirect_stdout(output):
            self.assertEqual(delivery.main(
                [PATH, "--maintenance-window-confirmed"]), 0)
        deliver.assert_called_once_with(PATH)
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "candidate-assets-staged")
        self.assertEqual(report["runtime_readiness"], "not-validated")

    def test_cli_failure_does_not_report_success(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(delivery, "deliver_candidate",
                          side_effect=ValueError("verification failed")),              redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(delivery.main(
                [PATH, "--maintenance-window-confirmed"]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("verification failed", errors.getvalue())
        self.assertEqual(json.loads(errors.getvalue()), {
            "status": "failed", "phase": "candidate-staging",
            "error_type": "ValueError",
        })


    def test_cli_failure_redacts_synthetic_secret(self):
        secret = "SYNTHETIC_TEST_ONLY_DO_NOT_LOG"
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(
                delivery, "deliver_candidate",
                side_effect=RuntimeError("synthetic-token=" + secret)), \
                redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(delivery.main(
                [PATH, "--maintenance-window-confirmed"]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn(secret, errors.getvalue())
        self.assertEqual(json.loads(errors.getvalue()), {
            "status": "failed", "phase": "candidate-staging",
            "error_type": "RuntimeError",
        })

    def test_cli_failure_bounds_and_validates_error_type(self):
        for name in ("X" * 102, "Invalid/Error"):
            with self.subTest(name=name):
                error = type(name, (Exception,), {})("synthetic-detail")
                output, errors = io.StringIO(), io.StringIO()
                with patch.object(delivery, "deliver_candidate",
                                  side_effect=error), \
                        redirect_stdout(output), redirect_stderr(errors):
                    self.assertEqual(delivery.main(
                        [PATH, "--maintenance-window-confirmed"]), 1)
                self.assertEqual(output.getvalue(), "")
                self.assertNotIn("synthetic-detail", errors.getvalue())
                self.assertEqual(json.loads(errors.getvalue()), {
                    "status": "failed", "phase": "candidate-staging",
                    "error_type": "Exception",
                })


if __name__ == "__main__":
    unittest.main()
