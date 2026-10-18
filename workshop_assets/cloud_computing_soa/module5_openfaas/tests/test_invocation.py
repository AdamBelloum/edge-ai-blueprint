"""Mocked HTTP tests; no gateway, TLS or platform validation."""

import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "helpers"))
import invoke as http
from lab_config import ConfigurationError


def response(status=200, body=b'{"message":"Hello Ada, your function is live!"}'):
    """Create a bounded in-memory response supporting a context manager."""
    result = io.BytesIO(body)
    result.code = status
    result.headers = {
        "Content-Type": "application/json",
        "Allow": "POST",
        "Set-Cookie": "must-not-be-returned",
    }
    return result


class InvocationTests(unittest.TestCase):
    """Check request construction, error handling and execution safeguards."""

    def setUp(self):
        """Mock configuration and the opener; never permit a real connection."""
        self.config = {
            "functions": {"greeting": "group-01-greeting"},
            "gateway_url": "https://gateway.example.test/openfaas",
            "request_timeout_seconds": 10,
        }
        self.loader = self.enterContext(
            patch.object(http, "load_config", return_value=self.config)
        )
        self.builder = self.enterContext(patch.object(http, "build_opener"))
        self.opener = Mock()
        self.builder.return_value = self.opener
        self.opener.open.return_value = response()

    def test_success_constructs_assigned_request(self):
        result = http.invoke("lab.local.json", "greeting", {"name": "Ada"})
        self.assertEqual(result.status, 200)
        self.assertEqual(result.json()["message"], "Hello Ada, your function is live!")
        request = self.opener.open.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://gateway.example.test/openfaas/function/group-01-greeting",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"name": "Ada"})
        self.assertEqual(self.opener.open.call_args.kwargs, {"timeout": 10})
        self.assertNotIn("set-cookie", result.headers)
        self.assertIsInstance(self.builder.call_args.args[0], http.NoRedirects)

    def test_http_error_is_an_inspectable_result(self):
        self.opener.open.side_effect = HTTPError(
            "https://gateway.example.test", 400, "Bad Request",
            {"Content-Type": "application/json"},
            io.BytesIO(b'{"error":"invalid_name"}'),
        )
        result = http.invoke("lab.local.json", "greeting", {"name": ""})
        self.assertEqual(result.status, 400)
        self.assertEqual(result.json(), {"error": "invalid_name"})

    def test_redirect_is_refused(self):
        self.opener.open.side_effect = HTTPError(
            "https://gateway.example.test", 302, "Redirect",
            {"Location": "https://other.example.test"}, io.BytesIO(b""),
        )
        with self.assertRaisesRegex(http.InvocationError, "Redirect refused"):
            http.invoke("lab.local.json", "greeting", {})
        self.assertIsNone(
            http.NoRedirects().redirect_request(
                None, None, 302, "Redirect", {}, "https://other.example.test"
            )
        )

    def test_oversized_response_is_rejected(self):
        self.opener.open.return_value = response(
            body=b"x" * (http.MAX_RESPONSE_BYTES + 1)
        )
        with self.assertRaisesRegex(http.InvocationError, "Response exceeds"):
            http.invoke("lab.local.json", "greeting", {})

    def test_invalid_response_encoding_and_json(self):
        self.opener.open.return_value = response(body=b"\xff")
        with self.assertRaisesRegex(http.InvocationError, "UTF-8"):
            http.invoke("lab.local.json", "greeting", {})
        self.opener.open.return_value = response(body=b"not JSON")
        result = http.invoke("lab.local.json", "greeting", {})
        with self.assertRaisesRegex(http.InvocationError, "not valid JSON"):
            result.json()

    def test_transport_error_does_not_echo_details_or_retry(self):
        self.opener.open.side_effect = URLError("sensitive-route-detail")
        with self.assertRaises(http.InvocationError) as caught:
            http.invoke("lab.local.json", "greeting", {})
        self.assertNotIn("sensitive-route-detail", str(caught.exception))
        self.opener.open.assert_called_once()

    def test_invalid_inputs_do_not_construct_an_opener(self):
        for key, payload, method in (
            ("unassigned", {}, "POST"),
            ("greeting", {}, "DELETE"),
            ("greeting", {"value": float("nan")}, "POST"),
            ("greeting", b"x" * (http.MAX_RESPONSE_BYTES + 1), "POST"),
        ):
            with self.subTest(key=key, method=method):
                with self.assertRaises(http.InvocationError):
                    http.invoke("lab.local.json", key, payload, method)
        self.builder.assert_not_called()

    def test_raw_malformed_json_and_get_are_supported(self):
        http.invoke("lab.local.json", "greeting", b"{broken")
        self.assertEqual(self.opener.open.call_args.args[0].data, b"{broken")
        self.opener.open.return_value = response(status=405)
        result = http.invoke("lab.local.json", "greeting", method="GET")
        self.assertEqual(result.status, 405)
        self.assertEqual(self.opener.open.call_args.args[0].get_method(), "GET")

    def test_real_template_blocks_network_before_opener_creation(self):
        # Restore the real loader for this test only.
        from lab_config import load_config
        self.loader.side_effect = load_config
        with self.assertRaisesRegex(ConfigurationError, "Live execution is disabled"):
            http.invoke(MODULE / "config/lab.example.json", "greeting", {})
        self.builder.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
