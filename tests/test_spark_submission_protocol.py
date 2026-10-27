"""Offline request-boundary tests; no sockets, containers or services started."""
import importlib.util
import json
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1]
          / "scripts/workshops/big-data/spark/submission/protocol.py")
spec = importlib.util.spec_from_file_location("spark_submission_protocol", SOURCE)
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)
RUN_ID = "0123456789abcdef0123456789abcdef"


def frame(value):
    return (json.dumps(value) + "\n").encode("utf-8")


def run_request(**changes):
    value = {"version": 1, "operation": "run", "request_id": RUN_ID,
             "exercise": "direct"}
    value.update(changes)
    return value


class SubmissionProtocolTests(unittest.TestCase):
    def assert_rejected(self, value):
        with self.assertRaises(protocol.RequestError):
            protocol.decode_request(frame(value))

    def test_both_fixed_exercises_round_trip(self):
        for exercise in ("direct", "livy"):
            with self.subTest(exercise=exercise):
                request = protocol.decode_request(protocol.encode_run_request(exercise, RUN_ID))
                self.assertEqual(request, ("run", RUN_ID, exercise))

    def test_status_round_trip(self):
        request = protocol.decode_request(protocol.encode_status_request(RUN_ID))
        self.assertEqual(request, ("status", RUN_ID, None))

    def test_run_generates_a_new_valid_id(self):
        first = protocol.decode_request(protocol.encode_run_request("direct"))
        second = protocol.decode_request(protocol.encode_run_request("direct"))
        self.assertRegex(first.request_id, r"^[0-9a-f]{32}$")
        self.assertNotEqual(first.request_id, second.request_id)

    def test_no_code_paths_hosts_group_claims_or_settings(self):
        for field, value in {
            "source": "print('untrusted')", "code": "print('untrusted')",
            "script": "/tmp/evil.py", "host": "tier2-worker-2",
            "group_id": "group_01", "GROUP_ID": "group_01",
            "args": ["--privileged"], "SPARK_MASTER_URL": "spark://other:7077",
            "LIVY_URL": "http://other:8998", "outputs": "/etc",
        }.items():
            with self.subTest(field=field):
                self.assert_rejected(run_request(**{field: value}))

    def test_rejects_nonapproved_exercise_values(self):
        for exercise in ("", "../direct", "01_spark_basics.py", "direct; id",
                         "DIRECT", None, True, 1, [], {}):
            with self.subTest(exercise=exercise):
                self.assert_rejected(run_request(exercise=exercise))

    def test_rejects_unsupported_operations(self):
        for operation in ("exec", "stop", "delete", "run; id", None, [], {}):
            with self.subTest(operation=operation):
                self.assert_rejected(run_request(operation=operation))

    def test_version_requires_exact_supported_integer(self):
        for version in (True, False, 1.0, "1", 0, 2, None, []):
            with self.subTest(version=version):
                self.assert_rejected(run_request(version=version))

    def test_rejects_missing_fields(self):
        for field in ("version", "operation", "request_id", "exercise"):
            with self.subTest(field=field):
                value = run_request()
                del value[field]
                self.assert_rejected(value)

    def test_status_cannot_carry_exercise_or_other_fields(self):
        self.assert_rejected(run_request(operation="status"))
        self.assert_rejected({"version": 1, "operation": "status",
                              "request_id": RUN_ID, "host": "other"})

    def test_rejects_invalid_ids(self):
        for request_id in ("", "a" * 31, "a" * 33, "A" * 32, "g" * 32,
                           "../" + "a" * 29, None, True, 1, [], {}):
            with self.subTest(request_id=request_id):
                self.assert_rejected(run_request(request_id=request_id))

    def test_rejects_nonobject_json(self):
        for value in ([], None, "direct", 1, True):
            with self.subTest(value=value):
                self.assert_rejected(value)

    def test_rejects_duplicate_fields(self):
        good = protocol.encode_run_request("direct", RUN_ID)
        duplicate = good[:-2] + b',"exercise":"livy"}\n'
        with self.assertRaises(protocol.RequestError):
            protocol.decode_request(duplicate)

    def test_rejects_malformed_json_and_utf8(self):
        for value in (b"{\n", b"\xff\n", b"{} {}\n"):
            with self.subTest(value=value):
                with self.assertRaises(protocol.RequestError):
                    protocol.decode_request(value)

    def test_rejects_empty_unterminated_and_multiple_frames(self):
        good = protocol.encode_run_request("direct", RUN_ID)
        for value in (b"", b"\n", good[:-1], good + good, good + b"\n"):
            with self.subTest(value=value):
                with self.assertRaises(protocol.RequestError):
                    protocol.decode_request(value)

    def test_rejects_oversized_frames(self):
        with self.assertRaises(protocol.RequestError):
            protocol.decode_request(b" " * protocol.MAX_REQUEST_BYTES + b"\n")

    def test_requires_bytes_not_other_frame_types(self):
        for value in ("{}\n", bytearray(b"{}\n"), None):
            with self.subTest(value=value):
                with self.assertRaises(protocol.RequestError):
                    protocol.decode_request(value)

    def test_encoders_also_validate_inputs(self):
        with self.assertRaises(protocol.RequestError):
            protocol.encode_run_request("arbitrary")
        with self.assertRaises(protocol.RequestError):
            protocol.encode_run_request("direct", False)
        with self.assertRaises(protocol.RequestError):
            protocol.encode_status_request("../escape")

    def test_approved_filename_mapping_is_immutable(self):
        self.assertEqual(dict(protocol.EXERCISE_FILES), {
            "direct": "01_spark_basics.py", "livy": "02_spark_via_livy.py"})
        with self.assertRaises(TypeError):
            protocol.EXERCISE_FILES["direct"] = "/tmp/evil.py"


if __name__ == "__main__":
    unittest.main()
