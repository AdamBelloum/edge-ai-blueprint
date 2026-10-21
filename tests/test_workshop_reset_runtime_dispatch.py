"""Offline saved-context dispatch tests; operational commands are fake."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESET = ROOT / (
    "scripts/workshops/federated-learning/"
    "reset-federated-learning-workshop.sh"
)
SOURCE = RESET.read_text()
START = "# BEGIN SAVED-CONTEXT RUNTIME DISPATCH"
END = "# END SAVED-CONTEXT RUNTIME DISPATCH"
if SOURCE.count(START) != 1 or SOURCE.count(END) != 1:
    raise RuntimeError("Expected unique runtime dispatch boundaries")
BLOCK = SOURCE.split(START, 1)[1].split(END, 1)[0]


def run_dispatch(data, teardown_status=0, remote_status=0, duplicate=False):
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        script_dir = directory / "federated-learning"
        script_dir.mkdir()
        spark_dir = directory / "big-data/spark"
        spark_dir.mkdir(parents=True)
        fake_bin = directory / "bin"
        fake_bin.mkdir()
        log = directory / "teardown.log"

        wrapper = spark_dir / "teardown-runtime.sh"
        wrapper.write_text(
            '#!/bin/sh\n'
            'printf "%s\\n" "$*" >> "$MOCK_TEARDOWN_LOG"\n'
            'exit "$MOCK_TEARDOWN_STATUS"\n'
        )
        wrapper.chmod(0o700)

        k3s = fake_bin / "k3s"
        k3s.write_text(
            '#!/bin/sh\n'
            'printf "%s\\n" "$MOCK_STATE"\n'
        )
        k3s.chmod(0o700)

        environment = os.environ.copy()
        environment.pop("BASH_ENV", None)
        environment.pop("ENV", None)
        environment.update({
            "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
            "SCRIPT_DIR": str(script_dir),
            "DIGITAFRICA_NAMESPACE": "mock-namespace",
            "MOCK_STATE": json.dumps({"data": data}),
            "MOCK_TEARDOWN_LOG": str(log),
            "MOCK_TEARDOWN_STATUS": str(teardown_status),
            "MOCK_REMOTE_STATUS": str(remote_status),
            "MOCK_DUPLICATE": "yes" if duplicate else "no",
        })

        setup = r'''
set -euo pipefail
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
run_deployment_remote() {
  if [[ "$MOCK_REMOTE_STATUS" != 0 ]]; then
    return "$MOCK_REMOTE_STATUS"
  fi
  bash -c "$1" || return "$?"
  if [[ "$MOCK_DUPLICATE" == yes ]]; then
    printf 'RESET_RUNTIME_ROUTE=spark\n'
  fi
}
'''
        result = subprocess.run(
            ["bash", "-c", setup + BLOCK +
             "\nprintf 'EVENT workspace-boundary\\n'\n"],
            env=environment, capture_output=True, text=True, timeout=10,
        )
        calls = log.read_text().splitlines() if log.exists() else []
        return result, calls


def spark_context():
    return {
        "workshop_type": "none",
        "workshop_module": "none",
        "cleanup_status": "in_progress",
        "cleanup_workshop_type": "big-data",
        "cleanup_workshop_module": "spark",
    }


class RuntimeDispatchTests(unittest.TestCase):
    def test_saved_spark_context_executes_after_neutral_selection(self):
        result, calls = run_dispatch(spark_context())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["--execute"])
        self.assertIn("cleanup verified", result.stdout)
        self.assertIn("EVENT workspace-boundary", result.stdout)

    def test_current_spark_selection_does_not_override_saved_context(self):
        data = spark_context()
        data.update({
            "workshop_type": "big-data",
            "workshop_module": "spark",
            "cleanup_workshop_type": "hpc",
            "cleanup_workshop_module": "module1",
        })
        result, calls = run_dispatch(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        self.assertIn("no Spark teardown dispatched", result.stdout)

    def test_teardown_failure_stops_before_workspace_boundary(self):
        result, calls = run_dispatch(spark_context(), teardown_status=7)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(calls, ["--execute"])
        self.assertNotIn("EVENT workspace-boundary", result.stdout)
        self.assertIn("cleanup remains in_progress", result.stderr)

    def test_invalid_saved_context_blocks_dispatch(self):
        cases = [
            {"cleanup_status": "complete"},
            {"cleanup_status": "failed"},
            {"cleanup_workshop_type": "unsupported"},
            {"cleanup_workshop_module": ""},
            {"cleanup_workshop_module": None},
            {"cleanup_workshop_module": "unsupported-big-data-module"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                data = spark_context()
                data.update(changes)
                result, calls = run_dispatch(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])
                self.assertNotIn("EVENT workspace-boundary", result.stdout)

    def test_missing_saved_context_blocks_dispatch(self):
        result, calls = run_dispatch({
            "cleanup_status": "in_progress",
            "workshop_type": "big-data",
            "workshop_module": "spark",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertNotIn("EVENT workspace-boundary", result.stdout)

    def test_remote_failure_propagates_without_teardown(self):
        result, calls = run_dispatch(spark_context(), remote_status=9)
        self.assertEqual(result.returncode, 9)
        self.assertEqual(calls, [])
        self.assertNotIn("EVENT workspace-boundary", result.stdout)

    def test_duplicate_route_is_refused(self):
        result, calls = run_dispatch(spark_context(), duplicate=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertNotIn("EVENT workspace-boundary", result.stdout)
        self.assertIn("uniquely determine", result.stderr)

    def test_dispatch_order_and_completion_remain_blocked(self):
        start = SOURCE.index(START)
        end = SOURCE.index(END)
        self.assertLess(
            SOURCE.index('"cleanup_status": "in_progress"'), start
        )
        self.assertLess(
            SOURCE.index('\nstop_selected_participant_servers\n'), start
        )
        self.assertLess(
            end, SOURCE.index('"$COHORT_HELPER" "${workspace_args[@]}"')
        )
        self.assertNotIn('"cleanup_status": "complete"', SOURCE)
        self.assertIn(
            "fail 'Participant reset finished and selection is neutral",
            SOURCE,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
