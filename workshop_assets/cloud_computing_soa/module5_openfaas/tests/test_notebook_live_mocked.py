"""Exercise notebook live branches with mocks, never a live platform."""

import ast
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import call, patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "helpers"))
import invoke
import lab_config
import traffic


class EnableLiveInMemory(ast.NodeTransformer):
    """Enable only the notebook switches in the compiled test copy."""

    def visit_Assign(self, node):
        if any(isinstance(target, ast.Name) and
               target.id in ("RUN_LIVE", "RUN_TRAFFIC")
               for target in node.targets):
            node.value = ast.Constant(value=True)
        return node


def response(status, body, headers=None):
    return invoke.InvocationResult(
        status, headers or {"content-type": "application/json"},
        json.dumps(body),
    )


class MockedNotebookLiveTests(unittest.TestCase):
    """Validate successful live-branch wiring, not platform behaviour."""

    def execute_mocked(self, filename, responses, summary=None):
        path = MODULE / "beginner" / filename
        original = path.read_bytes()
        notebook = json.loads(original)
        local = MODULE / "config/lab.local.json"
        real_loader = lab_config.load_config
        config = real_loader(MODULE / "config/lab.example.json", require_live=False)
        config["live_test_enabled"] = True
        config["load"]["requests"] = 3

        def loader(path, require_live=True):
            if Path(path) == local:
                return copy.deepcopy(config)
            return real_loader(path, require_live=require_live)

        previous_cwd = Path.cwd()
        previous_path = sys.path[:]
        self.addCleanup(os.chdir, previous_cwd)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous_path))
        os.chdir(MODULE / "beginner")
        namespace = {"__name__": "__main__"}

        with (
            patch.object(lab_config, "load_config", autospec=True, side_effect=loader),
            patch.object(invoke, "invoke", autospec=True, side_effect=responses) as request,
            patch.object(traffic, "run_traffic", autospec=True, return_value=summary) as batch,
            patch.object(invoke, "build_opener", side_effect=AssertionError("HTTP blocked")),
            patch.object(socket.socket, "connect", side_effect=AssertionError("Network blocked")),
            patch.object(socket, "create_connection", side_effect=AssertionError("Network blocked")),
            patch.object(subprocess, "Popen", side_effect=AssertionError("Commands blocked")),
            patch.object(os, "system", side_effect=AssertionError("Shell blocked")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            for cell in notebook["cells"]:
                if cell["cell_type"] != "code":
                    continue
                tree = EnableLiveInMemory().visit(ast.parse("".join(cell["source"])))
                ast.fix_missing_locations(tree)
                exec(compile(tree, f"{filename}:{cell['id']}", "exec"), namespace)
            requests = request.call_args_list[:]
            batches = batch.call_args_list[:]

        self.assertEqual(path.read_bytes(), original)
        self.assertIs(namespace["RUN_LIVE"], True)
        return local, namespace, requests, batches

    def test_notebook1_invocation_wiring(self):
        results = [
            response(200, {"message": "Hello Ada, your function is live!"}),
            response(400, {"error": "invalid_name"}),
            response(400, {"error": "invalid_name"}),
            response(400, {"error": "expected_json_object"}),
            response(405, {"error": "method_not_allowed"}, {"allow": "POST"}),
            invoke.InvocationResult(400, {"content-type": "text/html"}, "Bad Request"),
        ]
        local, _, requests, batches = self.execute_mocked(
            "01-explore-and-invoke.ipynb", results
        )
        self.assertEqual(requests, [
            call(local, "prepared_greeting", {"name": "Ada"}),
            call(local, "prepared_greeting", {"name": ""}, method="POST"),
            call(local, "prepared_greeting", {"name": 7}, method="POST"),
            call(local, "prepared_greeting", [], method="POST"),
            call(local, "prepared_greeting", None, method="GET"),
            call(local, "prepared_greeting", b"{broken"),
        ])
        self.assertEqual(batches, [])

    def test_notebook3_invocation_and_traffic_wiring(self):
        weather = {"city": "Amsterdam", "temperature_c": 12.5, "condition": "Cloudy"}
        expected = dict(weather, message="Weather in Amsterdam: 12.5°C, Cloudy.")
        summary = {
            "completed_requests": 3, "status_counts": {200: 3},
            "client_latency_seconds": {"minimum": 0.1, "mean": 0.2, "maximum": 0.3},
        }
        local, namespace, requests, batches = self.execute_mocked(
            "03-data-and-observability.ipynb",
            [response(200, expected), response(400, {"error": "invalid_temperature"})],
            summary,
        )
        self.assertEqual(requests, [
            call(local, "weather", weather),
            call(local, "weather", dict(weather, temperature_c="12.5")),
        ])
        self.assertEqual(batches, [call(local, "weather", weather)])
        self.assertIs(namespace["RUN_TRAFFIC"], True)
        self.assertEqual(namespace["traffic_summary"], summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
