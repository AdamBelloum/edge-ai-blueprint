"""Execute Notebook 1's default path with invocation and networking blocked."""

import contextlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "helpers"))
import invoke


class NotebookOfflineTests(unittest.TestCase):
    """Protect offline execution without saving notebook outputs."""

    def test_notebook1_defaults_skip_live_execution(self):
        path = MODULE / "beginner/01-explore-and-invoke.ipynb"
        original = path.read_bytes()
        notebook = json.loads(original)
        namespace = {"__name__": "__main__"}
        captured = io.StringIO()
        executed = 0

        previous_cwd = Path.cwd()
        previous_path = sys.path[:]
        self.addCleanup(os.chdir, previous_cwd)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous_path))
        os.chdir(MODULE / "beginner")

        with (
            patch.object(invoke, "invoke",
                         side_effect=AssertionError("Unexpected invocation")) as call,
            patch.object(invoke, "build_opener",
                         side_effect=AssertionError("Unexpected HTTP opener")) as opener,
            patch.object(socket.socket, "connect",
                         side_effect=AssertionError("Unexpected connection")),
            patch.object(socket, "create_connection",
                         side_effect=AssertionError("Unexpected connection")),
            contextlib.redirect_stdout(captured),
        ):
            for cell in notebook["cells"]:
                if cell["cell_type"] != "code":
                    continue
                self.assertIsNone(cell["execution_count"])
                self.assertEqual(cell["outputs"], [])
                source = "".join(cell["source"])
                exec(compile(source, f"{path.name}:{cell['id']}", "exec"), namespace)
                executed += 1
            call.assert_not_called()
            opener.assert_not_called()

        self.assertGreater(executed, 0)
        self.assertEqual(namespace["parsed_synthetic_error"], {"error": "invalid_name"})
        self.assertIs(namespace["synthetic_parse_rejected"], True)
        self.assertEqual(namespace["synthetic_html_error"].status, 400)
        self.assertIn("SYNTHETIC RESPONSE PRACTICE — NO REQUESTS SENT", captured.getvalue())
        self.assertNotIn("<html>", captured.getvalue())
        self.assertIs(namespace["RUN_LIVE"], False)
        self.assertEqual(captured.getvalue().count("SKIPPED:"), 4)
        self.assertIn("Expected live-configuration rejection:", captured.getvalue())
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
