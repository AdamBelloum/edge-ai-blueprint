"""Mocked traffic tests; no requests, real delays or platform validation."""

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "helpers"))
import traffic
from invoke import InvocationError
from lab_config import ConfigurationError


class TrafficTests(unittest.TestCase):
    """Verify sequential traffic accounting and fail-closed behaviour."""

    def setUp(self):
        """Replace configuration, invocation, clock and sleep with mocks."""
        self.config = {
            "functions": {"greeting": "group-01-greeting"},
            "load": {
                "requests": 3,
                "interval_seconds": 0.5,
                "concurrency": 1,
            },
        }
        self.loader = self.enterContext(
            patch.object(traffic, "load_config", return_value=self.config)
        )
        self.invoke = self.enterContext(patch.object(traffic, "invoke"))
        self.invoke.return_value = SimpleNamespace(status=200)
        self.clock = self.enterContext(
            patch.object(
                traffic.time, "perf_counter",
                side_effect=[0, 0.25, 1, 1.5, 2, 2.75],
            )
        )
        self.sleep = self.enterContext(patch.object(traffic.time, "sleep"))

    def test_counts_statuses_and_client_latencies(self):
        self.invoke.side_effect = [
            SimpleNamespace(status=200),
            SimpleNamespace(status=400),
            SimpleNamespace(status=200),
        ]
        result = traffic.run_traffic(
            "lab.local.json", "greeting", {"name": "Ada"}
        )
        self.assertEqual(result["completed_requests"], 3)
        self.assertEqual(result["status_counts"], {200: 2, 400: 1})
        self.assertEqual(result["client_latency_seconds"], {
            "minimum": 0.25, "mean": 0.5, "maximum": 0.75,
        })
        self.assertEqual(self.invoke.call_count, 3)
        for call in self.invoke.call_args_list:
            self.assertEqual(
                call.args, ("lab.local.json", "greeting", {"name": "Ada"})
            )
        self.assertEqual(self.sleep.call_count, 2)
        for call in self.sleep.call_args_list:
            self.assertEqual(call.args, (0.5,))

    def test_single_request_has_no_trailing_sleep(self):
        self.config["load"]["requests"] = 1
        result = traffic.run_traffic("lab.local.json", "greeting", {})
        self.assertEqual(result["completed_requests"], 1)
        self.invoke.assert_called_once()
        self.sleep.assert_not_called()

    def test_transport_failure_stops_without_retry(self):
        self.invoke.side_effect = [
            SimpleNamespace(status=200),
            InvocationError("Transport failed."),
        ]
        with self.assertRaisesRegex(InvocationError, "Transport failed"):
            traffic.run_traffic("lab.local.json", "greeting", {})
        self.assertEqual(self.invoke.call_count, 2)
        self.sleep.assert_called_once_with(0.5)

    def test_invalid_assignment_stops_before_requests_or_sleep(self):
        with self.assertRaisesRegex(ValueError, "assigned function key"):
            traffic.run_traffic("lab.local.json", "unassigned", {})
        self.invoke.assert_not_called()
        self.clock.assert_not_called()
        self.sleep.assert_not_called()

    def test_real_template_blocks_traffic(self):
        from lab_config import load_config
        self.loader.side_effect = load_config
        with self.assertRaisesRegex(ConfigurationError, "Live execution is disabled"):
            traffic.run_traffic(
                MODULE / "config/lab.example.json", "greeting", {}
            )
        self.invoke.assert_not_called()
        self.clock.assert_not_called()
        self.sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
