"""Verify Notebook 3 defaults without live traffic or external commands."""

import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "helpers"))
import invoke
import traffic


class Notebook3OfflineTests(unittest.TestCase):
    """Check fixture exploration, synthetic observations and live gates."""

    def test_default_weather_and_observability_path(self):
        path = MODULE / "beginner/03-data-and-observability.ipynb"
        original = path.read_bytes()
        notebook = json.loads(original)
        namespace = {"__name__": "__main__"}
        captured = io.StringIO()

        previous_cwd = Path.cwd()
        previous_path = sys.path[:]
        self.addCleanup(os.chdir, previous_cwd)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous_path))
        os.chdir(MODULE / "beginner")

        with (
            patch.object(invoke, "invoke",
                         side_effect=AssertionError("Unexpected invocation")) as call,
            patch.object(traffic, "run_traffic",
                         side_effect=AssertionError("Unexpected traffic")) as batch,
            patch.object(traffic, "invoke",
                         side_effect=AssertionError("Unexpected traffic invocation")) as traffic_call,
            patch.object(invoke, "build_opener",
                         side_effect=AssertionError("Unexpected HTTP opener")) as opener,
            patch.object(socket.socket, "connect",
                         side_effect=AssertionError("Unexpected connection")),
            patch.object(socket, "create_connection",
                         side_effect=AssertionError("Unexpected connection")),
            patch.object(subprocess, "Popen",
                         side_effect=AssertionError("Unexpected command")) as command,
            patch.object(os, "system",
                         side_effect=AssertionError("Unexpected shell")) as shell,
            contextlib.redirect_stdout(captured),
        ):
            code_cells = [
                cell for cell in notebook["cells"]
                if cell["cell_type"] == "code"
            ]
            self.assertGreater(len(code_cells), 0)
            for cell in code_cells:
                self.assertIsNone(cell["execution_count"])
                self.assertEqual(cell["outputs"], [])
                source = "".join(cell["source"])
                exec(compile(source, f"{path.name}:{cell['id']}", "exec"), namespace)

            for mocked in (call, batch, traffic_call, opener, command, shell):
                mocked.assert_not_called()

        self.assertIs(namespace["RUN_LIVE"], False)
        self.assertIs(namespace["RUN_TRAFFIC"], False)
        self.assertEqual(namespace["weather"], {
            "city": "Amsterdam",
            "temperature_c": 12.5,
            "condition": "Cloudy",
        })
        summary = namespace["synthetic_summary"]
        self.assertEqual(summary["completed_requests"], 3)
        self.assertEqual(summary["status_counts"], {200: 2, 400: 1})
        self.assertEqual(summary["client_latency_seconds"], {
            "minimum": 0.25, "mean": 0.5, "maximum": 0.75,
        })
        self.assertIn(
            "SYNTHETIC TEACHING EXAMPLE — NOT MEASURED", captured.getvalue()
        )
        self.assertEqual(captured.getvalue().count("SKIPPED:"), 3)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
