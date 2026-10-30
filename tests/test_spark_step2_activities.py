"""Offline regression tests for guided Step 2; no live Livy or Spark required."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import importlib.util
import io
from pathlib import Path
import socket
import subprocess
import sys
import types
import unittest
from unittest import mock
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workshop_assets/big-data/spark/beginner"
CLIENT = BASE / "02_spark_via_livy.py"
DATA = "/reviewed/data/Bank_Personal_Loan_Modelling.csv"
SESSION = 37


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Step2ActivityTests(unittest.TestCase):
    def setUp(self):
        self.client = load_module("_guided_step2_test_client", CLIENT)
        guard = mock.patch.object(socket, "socket", side_effect=AssertionError("Network access forbidden in offline tests."))
        guard.start()
        self.addCleanup(guard.stop)

    def run_client(self, activity=None, verify=True, analysis_error=None,
                   cleanup_error=None, creation_error=None, wait_error=None,
                   creation_response=None):
        events = []
        helper = types.ModuleType("spark_livy_access")

        @contextmanager
        def connection(reader):
            events.append("connection-open")
            try:
                yield {"LIVY_URL": "http://127.0.0.1:12345",
                       "LIVY_DATA_PATH": DATA, "VERIFY_DATASET": verify}
            finally:
                events.append("connection-closed")

        helper.managed_connection = mock.Mock(side_effect=connection)
        helper.verify_dataset = mock.Mock(side_effect=lambda *args: events.append("verify") or DATA)

        def cleanup(*args):
            events.append("cleanup")
            if cleanup_error is not None:
                raise cleanup_error
        helper.delete_owned_session = mock.Mock(side_effect=cleanup)

        def request(base_url, method, path, payload=None):
            events.append("create")
            if creation_error is not None:
                raise creation_error
            return {"id": SESSION} if creation_response is None else creation_response

        def wait(*args):
            events.append("wait")
            if wait_error is not None:
                raise wait_error

        def statement(base_url, session_id, code):
            events.append("statement")
            if analysis_error is not None and "Spark version:" not in code:
                raise analysis_error
            return "mocked statement output"

        stdout, stderr = io.StringIO(), io.StringIO()
        error = None
        with mock.patch.dict(sys.modules, {"spark_livy_access": helper}), \
             mock.patch.object(self.client, "preview_local_dataset") as preview, \
             mock.patch.object(self.client, "livy_request", side_effect=request) as requests, \
             mock.patch.object(self.client, "wait_for_session", side_effect=wait) as readiness, \
             mock.patch.object(self.client, "run_statement", side_effect=statement) as statements, \
             mock.patch.object(self.client, "export_preview", return_value=Path("mock-output.csv")) as export, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                self.client.main(activity=activity)
            except BaseException as caught:
                error = caught
        return types.SimpleNamespace(events=events, helper=helper, preview=preview,
                                     requests=requests, readiness=readiness,
                                     statements=statements, export=export, error=error,
                                     stdout=stdout.getvalue(), stderr=stderr.getvalue())

    def test_full_analysis_preserves_original_statement_sequence(self):
        expected = (
            ("3. Read CSV and inspect schema", f"""
df = (spark.read.format('csv')
      .option('header', 'true')
      .option('inferSchema', 'true')
      .load({DATA!r}))
df.printSchema()
df.show(5)
print('Number of records:', df.count())
"""),
            ("4. Filter records where Age > 30", """
result_df = df.select('Age', 'Income', 'Family').filter(df.Age > 30)
result_df.show(10)
print('Matching records:', result_df.count())
"""),
            ("5. Count Personal Loan categories", """
df.groupBy('Personal Loan').count().orderBy('Personal Loan').show()
"""),
        )
        self.assertEqual(self.client.analysis_steps(DATA), expected)

    def test_activity_1_only_inspects_schema_and_input(self):
        steps = self.client.analysis_steps(DATA, 1)
        self.assertEqual(len(steps), 1)
        code = steps[0][1]
        self.assertIn("df.printSchema()", code)
        self.assertIn("Number of records:", code)
        self.assertNotIn("result_df", code)
        self.assertNotIn("groupBy", code)

    def test_activity_2_selects_without_filtering(self):
        code = self.client.analysis_steps(DATA, 2)[-1][1]
        self.assertIn("select('Age', 'Income', 'Family')", code)
        self.assertIn("selected_df.count()", code)
        self.assertNotIn(".filter(", code)
        self.assertNotIn("groupBy", code)

    def test_activity_3_uses_strict_age_filter(self):
        code = self.client.analysis_steps(DATA, 3)[-1][1]
        self.assertIn("filter(df.Age > 30)", code)
        self.assertIn("Matching records:", code)
        self.assertNotIn("groupBy", code)

    def test_activity_4_groups_full_input(self):
        code = self.client.analysis_steps(DATA, 4)[-1][1]
        self.assertIn("df.groupBy('Personal Loan').count()", code)
        self.assertNotIn("result_df", code)
        self.assertNotIn(".filter(", code)

    def test_activity_5_recreates_filter_without_other_analysis_actions(self):
        code = self.client.analysis_steps(DATA, 5)[-1][1]
        self.assertIn("result_df =", code)
        self.assertIn("filter(df.Age > 30)", code)
        for unwanted in (".show(", ".count(", "groupBy", "printSchema"):
            self.assertNotIn(unwanted, code)

    def test_invalid_activity_values_are_rejected(self):
        for value in (0, 6, -1, True, False, "1", 1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.client.analysis_steps(DATA, value)

    def test_data_path_is_safely_quoted_and_statements_compile(self):
        path = "/reviewed/quote'and\\slash\nname.csv"
        for activity in (None, 1, 2, 3, 4, 5):
            with self.subTest(activity=activity):
                steps = self.client.analysis_steps(path, activity)
                self.assertIn(repr(path), steps[0][1])
                for heading, code in steps:
                    compile(code, heading, "exec")

    def test_each_activity_loads_its_own_required_dataframe(self):
        for activity in range(1, 6):
            with self.subTest(activity=activity):
                code = self.client.analysis_steps(DATA, activity)[0][1]
                self.assertIn("df = (spark.read.format('csv')", code)
                self.assertIn(".option('inferSchema', 'true')", code)
                self.assertIn(f".load({DATA!r})", code)

    def test_each_successful_command_creates_and_cleans_only_returned_session(self):
        for activity in (None, 1, 2, 3, 4, 5):
            with self.subTest(activity=activity):
                result = self.run_client(activity)
                self.assertIsNone(result.error)
                result.requests.assert_called_once_with(
                    "http://127.0.0.1:12345", "POST", "/sessions", {"kind": "pyspark"})
                result.helper.delete_owned_session.assert_called_once_with(
                    result.requests, "http://127.0.0.1:12345", SESSION)
                self.assertEqual(result.events[-2:], ["cleanup", "connection-closed"])
                self.assertIn("Owned-session removal confirmed", result.stdout)

    def test_only_activity_5_and_full_analysis_export(self):
        for activity in (None, 1, 2, 3, 4, 5):
            with self.subTest(activity=activity):
                result = self.run_client(activity)
                self.assertIsNone(result.error)
                if activity in (None, 5):
                    result.export.assert_called_once_with(
                        "http://127.0.0.1:12345", SESSION, BASE / "outputs")
                    self.assertIn("Saved:", result.stdout)
                else:
                    result.export.assert_not_called()
                    self.assertNotIn("Saved:", result.stdout)

    def test_managed_dataset_verification_precedes_analysis(self):
        result = self.run_client(2)
        self.assertIsNone(result.error)
        self.assertEqual(result.events[:5], ["connection-open", "create", "wait", "statement", "verify"])
        result.helper.verify_dataset.assert_called_once_with(
            result.statements, "http://127.0.0.1:12345", SESSION,
            DATA, BASE / "data/Bank_Personal_Loan_Modelling.csv")
        actual = [call.args[2] for call in result.statements.call_args_list[1:]]
        self.assertEqual(actual, [code for heading, code in self.client.analysis_steps(DATA, 2)])

    def test_explicit_settings_do_not_claim_managed_verification(self):
        result = self.run_client(1, verify=False)
        self.assertIsNone(result.error)
        result.helper.verify_dataset.assert_not_called()

    def test_session_readiness_failure_still_cleans_owned_session(self):
        error = TimeoutError("readiness expired")
        result = self.run_client(1, wait_error=error)
        self.assertIs(result.error, error)
        result.statements.assert_not_called()
        result.helper.delete_owned_session.assert_called_once()
        self.assertEqual(result.events[-2:], ["cleanup", "connection-closed"])

    def test_analysis_failure_still_cleans_and_never_exports(self):
        error = RuntimeError("statement failed")
        result = self.run_client(5, analysis_error=error)
        self.assertIs(result.error, error)
        result.export.assert_not_called()
        result.helper.delete_owned_session.assert_called_once()
        self.assertEqual(result.events[-1], "connection-closed")

    def test_keyboard_interrupt_attempts_owned_cleanup(self):
        error = KeyboardInterrupt()
        result = self.run_client(1, analysis_error=error)
        self.assertIs(result.error, error)
        result.helper.delete_owned_session.assert_called_once()
        self.assertEqual(result.events[-1], "connection-closed")

    def test_cleanup_failure_prevents_success_claim(self):
        error = TimeoutError("cleanup unconfirmed")
        result = self.run_client(1, cleanup_error=error)
        self.assertIs(result.error, error)
        self.assertIn("unconfirmed", result.stderr)
        self.assertNotIn("Owned-session removal confirmed", result.stdout)
        self.assertNotIn("Analysis completed successfully", result.stdout)
        self.assertEqual(result.events[-1], "connection-closed")

    def test_cleanup_failure_preserves_original_analysis_error(self):
        error = RuntimeError("original statement failure")
        result = self.run_client(1, analysis_error=error,
                                 cleanup_error=TimeoutError("cleanup unconfirmed"))
        self.assertIs(result.error, error)
        self.assertIn("unconfirmed", result.stderr)
        self.assertNotIn("Analysis completed successfully", result.stdout)

    def test_creation_failure_without_id_never_guesses_cleanup_id(self):
        error = TimeoutError("creation response lost")
        result = self.run_client(1, creation_error=error)
        self.assertIs(result.error, error)
        result.helper.delete_owned_session.assert_not_called()
        result.readiness.assert_not_called()
        self.assertEqual(result.events[-1], "connection-closed")

    def test_invalid_creation_id_never_triggers_guessed_cleanup(self):
        result = self.run_client(1, creation_response={"id": True})
        self.assertIsInstance(result.error, RuntimeError)
        result.helper.delete_owned_session.assert_not_called()
        result.readiness.assert_not_called()
        self.assertEqual(result.events[-1], "connection-closed")

    def test_invalid_main_activity_fails_before_connection(self):
        result = self.run_client(0)
        self.assertIsInstance(result.error, ValueError)
        result.helper.managed_connection.assert_not_called()
        result.requests.assert_not_called()
        result.preview.assert_not_called()
        self.assertEqual(result.events, [])

    def test_cli_rejects_invalid_activity_before_execution(self):
        for value in ("0", "6", "invalid"):
            with self.subTest(value=value):
                result = subprocess.run([sys.executable, "-B", str(CLIENT), "--activity", value],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Created Livy session:", result.stdout)
                self.assertIn("--activity", result.stderr)


class OwnedSessionConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_module("_guided_step2_test_access", BASE / "spark_livy_access.py")

    def http_error(self, code):
        return HTTPError("http://127.0.0.1:12345/sessions/37", code, "test status", {}, None)

    def test_cleanup_requires_owned_get_404_after_delete(self):
        request = mock.Mock(side_effect=[{}, self.http_error(404)])
        with mock.patch.object(self.helper.time, "monotonic", side_effect=[0, 0]):
            self.helper.delete_owned_session(request, "http://127.0.0.1:12345", SESSION)
        self.assertEqual(request.call_args_list, [
            mock.call("http://127.0.0.1:12345", "DELETE", "/sessions/37"),
            mock.call("http://127.0.0.1:12345", "GET", "/sessions/37")])

    def test_failed_delete_can_still_be_confirmed_by_owned_get_404(self):
        request = mock.Mock(side_effect=[OSError("delete response lost"), self.http_error(404)])
        with mock.patch.object(self.helper.time, "monotonic", side_effect=[0, 0]):
            self.helper.delete_owned_session(request, "http://127.0.0.1:12345", SESSION)
        self.assertEqual(request.call_count, 2)

    def test_accepted_delete_without_disappearance_times_out(self):
        request = mock.Mock(return_value={"state": "idle"})
        with mock.patch.object(self.helper.time, "monotonic", side_effect=[0, 0, 61]), \
             mock.patch.object(self.helper.time, "sleep"), self.assertRaises(TimeoutError):
            self.helper.delete_owned_session(request, "http://127.0.0.1:12345", SESSION)

    def test_non_404_http_error_is_not_cleanup_confirmation(self):
        request = mock.Mock(side_effect=[{}, self.http_error(503)])
        with mock.patch.object(self.helper.time, "monotonic", side_effect=[0, 0]), \
             self.assertRaises(RuntimeError):
            self.helper.delete_owned_session(request, "http://127.0.0.1:12345", SESSION)

    def test_invalid_owned_id_is_rejected_before_requests(self):
        for value in (-1, True, "37", None):
            with self.subTest(value=value):
                request = mock.Mock()
                with self.assertRaises(ValueError):
                    self.helper.delete_owned_session(request, "http://127.0.0.1:12345", value)
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
