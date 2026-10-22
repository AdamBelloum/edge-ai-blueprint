"""Offline saved-context dispatch tests; operational commands are fake."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESET = ROOT / "scripts/workshops/reset-workshops.sh"
SOURCE = RESET.read_text()
START = "# BEGIN SAVED-CONTEXT RUNTIME DISPATCH"
END = "# END SAVED-CONTEXT RUNTIME DISPATCH"
if SOURCE.count(START) != 1 or SOURCE.count(END) != 1:
    raise RuntimeError("Expected unique runtime dispatch boundaries")
BLOCK = SOURCE.split(START, 1)[1].split(END, 1)[0]


def run_dispatch(data, teardown_status=0, remote_status=0, duplicate=False,
                 fl_cleanup_status=0, local_cleanup_status=None):
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        script_dir = directory
        (script_dir / "federated-learning").mkdir()
        # Optional fake local helper for extended wiring tests only.
        if local_cleanup_status is not None:
            (script_dir / "federated-learning" / "reset_fl_partitions.py").write_text(
                'import os, sys\n'
                'with open(os.environ["MOCK_TEARDOWN_LOG"], "a") as log:\n'
                '    log.write("FL_LOCAL " + " ".join(sys.argv[1:]) + "\\n")\n'
                'sys.exit(int(os.environ["MOCK_LOCAL_CLEANUP_STATUS"]))\n'
            )
        fake_bin = directory / "bin"
        fake_bin.mkdir()
        log = directory / "teardown.log"

        playbooks = directory / "playbooks"
        playbooks.mkdir()
        (playbooks / "reset-fl-worker-data.yml").write_text("---\n")

        ansible = fake_bin / "ansible-playbook"
        ansible.write_text(
            '#!/bin/sh\n'
            'printf "FL_DATA %s\\n" "$*" >> "$MOCK_TEARDOWN_LOG"\n'
            'exit "$MOCK_FL_CLEANUP_STATUS"\n'
        )
        ansible.chmod(0o700)

        for workshop in (
            "big-data", "hpc", "introduction-to-ai", "cloud-computing-soa"
        ):
            workshop_dir = directory / workshop
            workshop_dir.mkdir()
            wrapper = workshop_dir / "reset-workshop.sh"
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
            "REPOSITORY_ROOT": str(directory),
            "INVENTORY_PATH": "mock-inventory",
            "WORKER_GROUP": "mock-workers",
            "MOCK_FL_CLEANUP_STATUS": str(fl_cleanup_status),
            "MOCK_LOCAL_CLEANUP_STATUS": str(local_cleanup_status),
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
    printf 'RESET_RUNTIME_ROUTE=big-data:spark\n'
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
        self.assertEqual(calls, ["--runtime-only --module spark"])
        self.assertIn("runtime reset stage returned successfully", result.stdout)
        self.assertIn("EVENT workspace-boundary", result.stdout)

    def test_current_spark_selection_does_not_override_saved_context(self):
        data = spark_context()
        data.update({
            "workshop_type": "big-data",
            "workshop_module": "spark",
            "cleanup_workshop_type": "hpc",
            "cleanup_workshop_module": "openmp-01-basics",
        })
        result, calls = run_dispatch(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["--runtime-only --module openmp-01-basics"])
        self.assertIn("hpc / openmp-01-basics", result.stdout)

    def test_teardown_failure_stops_before_workspace_boundary(self):
        result, calls = run_dispatch(spark_context(), teardown_status=7)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(calls, ["--runtime-only --module spark"])
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


    def test_all_selected_workshops_delegate_saved_modules(self):
        cases = {
            "hpc": ("openmp-01-basics",),
            "introduction-to-ai": ("module1", "module2", "module3"),
            "cloud-computing-soa": (
                "module1", "module2", "module3", "module4", "module5"
            ),
        }
        for workshop, modules in cases.items():
            for module in modules:
                with self.subTest(workshop=workshop, module=module):
                    data = spark_context()
                    data.update(
                        cleanup_workshop_type=workshop,
                        cleanup_workshop_module=module,
                    )
                    result, calls = run_dispatch(data)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        calls, ["--runtime-only --module " + module]
                    )
                    self.assertIn(workshop + " / " + module, result.stdout)

    def test_neutral_skips_cleanup_and_fl_dispatches_only_data_cleanup(self):
        for workshop in ("none", "federated-learning"):
            with self.subTest(workshop=workshop):
                data = spark_context()
                data.update(
                    cleanup_workshop_type=workshop,
                    cleanup_workshop_module="none",
                )
                result, calls = run_dispatch(data)
                self.assertEqual(result.returncode, 0, result.stderr)
                if workshop == "none":
                    self.assertEqual(calls, [])
                else:
                    self.assertEqual(len(calls), 1)
                    self.assertTrue(
                        calls[0].startswith("FL_DATA -i mock-inventory ")
                    )
                    self.assertTrue(calls[0].endswith(
                        "/playbooks/reset-fl-worker-data.yml "
                        "-e fl_reset_worker_group=mock-workers"
                    ))
                    self.assertIn(
                        "FL worker-data cleanup verified", result.stdout
                    )
                self.assertIn("EVENT workspace-boundary", result.stdout)

    def test_fl_data_cleanup_failure_blocks_workspace_deletion(self):
        data = spark_context()
        data.update(
            cleanup_workshop_type="federated-learning",
            cleanup_workshop_module="none",
        )
        result, calls = run_dispatch(data, fl_cleanup_status=8)
        self.assertEqual(result.returncode, 8)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("FL_DATA "))
        self.assertNotIn("EVENT workspace-boundary", result.stdout)
        self.assertIn("cleanup remains in_progress", result.stderr)

    def test_cloud_cleanup_refusal_blocks_workspace_deletion(self):
        for module in ("module3", "module4"):
            with self.subTest(module=module):
                data = spark_context()
                data.update(
                    cleanup_workshop_type="cloud-computing-soa",
                    cleanup_workshop_module=module,
                )
                result, calls = run_dispatch(data, teardown_status=3)
                self.assertEqual(result.returncode, 3)
                self.assertEqual(
                    calls, ["--runtime-only --module " + module]
                )
                self.assertNotIn("EVENT workspace-boundary", result.stdout)
                self.assertIn("cleanup remains in_progress", result.stderr)

    def test_unknown_modules_are_rejected_before_helper_execution(self):
        for workshop in (
            "none", "federated-learning", "hpc",
            "introduction-to-ai", "cloud-computing-soa",
        ):
            with self.subTest(workshop=workshop):
                data = spark_context()
                data.update(
                    cleanup_workshop_type=workshop,
                    cleanup_workshop_module="unsupported",
                )
                result, calls = run_dispatch(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])
                self.assertNotIn("EVENT workspace-boundary", result.stdout)

    def test_dispatch_order_and_completion_follow_reconciliation(self):
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
        completion = SOURCE.index(
            '{"op":"replace","path":"/data/cleanup_status","value":"complete"}'
        )
        reconciliation = SOURCE.index(
            '"$RECONCILIATION_HELPER" --neutral-for-reset'
        )
        self.assertLess(end, reconciliation)
        self.assertLess(reconciliation, completion)
        self.assertNotIn(
            "fail 'Participant reset finished and selection is neutral",
            SOURCE,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
