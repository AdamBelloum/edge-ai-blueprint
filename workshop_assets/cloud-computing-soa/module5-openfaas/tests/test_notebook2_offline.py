"""Test Notebook 2 offline without network or external commands."""

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


class Notebook2OfflineTests(unittest.TestCase):
    """Verify candidate preparation without saving notebook outputs."""

    def test_offline_source_and_manifest_exercises(self):
        path = MODULE / "beginner/02-develop-and-deploy.ipynb"
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

            call.assert_not_called()
            opener.assert_not_called()
            command.assert_not_called()
            shell.assert_not_called()

        self.assertIn("PASS: Only temporary source and test copies changed.", captured.getvalue())
        self.assertFalse(namespace["edited_source_directory"].exists())
        self.assertIn("Welcome ${name}", namespace["source_after"])
        self.assertIn("Welcome ${name}", namespace["tests_after"])
        self.assertEqual(
            namespace["source_after"].replace(namespace["revised_message"], namespace["original_message"], 1),
            namespace["source_before"],
        )
        self.assertEqual(
            namespace["tests_after"].replace(namespace["revised_message"], namespace["original_message"], 1),
            namespace["tests_before"],
        )
        for filename, content in namespace["reference_files_before"].items():
            self.assertEqual((MODULE / "examples/greeting" / filename).read_bytes(), content)
        self.assertEqual(
            namespace["edited_candidate"]["functions"][namespace["edited_name"]]["handler"],
            str(namespace["edited_source_directory"]),
        )
        self.assertTrue(namespace["old_image"].endswith(":v1"))
        self.assertTrue(namespace["new_image"].endswith(":v2"))
        self.assertIn(
            "PASS: Existing candidate cannot be overwritten.",
            captured.getvalue(),
        )
        self.assertFalse(namespace["candidate"].exists())
        self.assertFalse(namespace["temporary_config"].exists())
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
