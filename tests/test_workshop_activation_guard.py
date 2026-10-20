#!/usr/bin/env python3
"""Activation-policy tests with mocked runtime state; no deployment access."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts/workshops/lib/organizer-runtime.sh"
WORKSHOPS = (
    "introduction-to-ai", "federated-learning",
    "cloud-computing-soa", "big-data", "hpc",
)


def activate(current, workspace_status, requested, cleanup="legacy"):
    return subprocess.run(
        [
            "bash", "-c",
            """
            set -euo pipefail
            source "$1"
            # The mock takes state from this shell's positional arguments.
            check_workshop_runtime_state() {
                WORKSHOP_TYPE="$CURRENT"
                PARTICIPANT_WORKSPACE_STATUS="$WORKSPACES"
                WORKSHOP_CLEANUP_STATUS="$CLEANUP"
            }
            CURRENT="$2"
            WORKSPACES="$3"
            CLEANUP="$5"
            ensure_workshop_activation_allowed "$4"
            """,
            "activation-test", str(GUARD),
            current, workspace_status, requested, cleanup,
        ],
        text=True, capture_output=True,
    )


class ActivationGuardTests(unittest.TestCase):
    def test_neutral_state_allows_workshop_selection(self):
        for requested in WORKSHOPS:
            with self.subTest(requested=requested):
                result = activate("none", "clean", requested)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_same_workshop_allows_module_or_mode_changes(self):
        for current in WORKSHOPS:
            for status in ("clean", "present"):
                with self.subTest(current=current, status=status):
                    result = activate(current, status, current)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_different_workshop_requires_cleanup_even_without_pvcs(self):
        for current in WORKSHOPS:
            for requested in WORKSHOPS:
                if current == requested:
                    continue
                for status in ("clean", "present"):
                    with self.subTest(
                        current=current, requested=requested, status=status
                    ):
                        result = activate(current, status, requested)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(
                            "before completing workshop cleanup", result.stderr
                        )

    def test_incomplete_cleanup_blocks_all_activation(self):
        for cleanup in ("in_progress", "failed"):
            for current in ("none",) + WORKSHOPS:
                for requested in WORKSHOPS:
                    with self.subTest(
                        cleanup=cleanup, current=current, requested=requested
                    ):
                        result = activate(current, "clean", requested, cleanup)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("cleanup is incomplete", result.stderr)

    def test_invalid_or_empty_cleanup_status_blocks_activation(self):
        for cleanup in ("", "unknown", "unexpected"):
            with self.subTest(cleanup=cleanup):
                result = activate("none", "clean", "hpc", cleanup)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cleanup status", result.stderr)

    def test_completed_cleanup_allows_neutral_activation(self):
        for requested in WORKSHOPS:
            with self.subTest(requested=requested):
                result = activate("none", "clean", requested, "complete")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_completed_marker_does_not_allow_cross_workshop_switch(self):
        result = activate("big-data", "clean", "hpc", "complete")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("before completing workshop cleanup", result.stderr)

    def test_unsupported_workshop_is_rejected(self):
        result = activate("none", "clean", "unsupported")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported workshop type", result.stderr)



def read_runtime_state(cleanup="", pvc="", fail_remote=False):
    return subprocess.run(
        [
            "bash", "-c",
            r"""
            set -euo pipefail
            source "$1"
            DIGITAFRICA_NAMESPACE="test-workshop"
            export MOCK_CLEANUP="$2" MOCK_PVC="$3" MOCK_FAIL="$4"

            run_deployment_remote() {
                # Execute the real generated script in an isolated shell.
                bash -s <<SCRIPT
set -euo pipefail
k3s() {
    if [[ "\$MOCK_FAIL" == yes ]]; then
        printf 'Mock Kubernetes failure\n' >&2
        return 7
    fi
    case "\$*" in
        *jsonpath=*cleanup_status*)
            printf '%s' "\$MOCK_CLEANUP"
            ;;
        *jsonpath=*workshop_type*)
            printf '%s' none
            ;;
        *"get pvc"*)
            printf '%s\n' "\$MOCK_PVC"
            ;;
        *)
            printf 'Unexpected mock command: %s\n' "\$*" >&2
            return 9
            ;;
    esac
}
$1
SCRIPT
            }

            check_workshop_runtime_state
            printf 'PARSED:%s:%s:%s\n' \
                "$WORKSHOP_TYPE" \
                "$PARTICIPANT_WORKSPACE_STATUS" \
                "$WORKSHOP_CLEANUP_STATUS"
            """,
            "reader-test", str(GUARD), cleanup, pvc,
            "yes" if fail_remote else "no",
        ],
        text=True, capture_output=True,
    )


class RuntimeStateReaderTests(unittest.TestCase):
    def test_absent_cleanup_marker_is_legacy_not_complete(self):
        result = read_runtime_state()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PARSED:none:clean:legacy", result.stdout)

    def test_explicit_cleanup_status_is_preserved(self):
        for cleanup in ("complete", "in_progress", "failed", "unexpected"):
            with self.subTest(cleanup=cleanup):
                result = read_runtime_state(cleanup)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    f"PARSED:none:clean:{cleanup}", result.stdout
                )

    def test_participant_workspace_is_detected(self):
        result = read_runtime_state(
            "in_progress", "claim-group-01---example"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PARSED:none:present:in_progress", result.stdout)

    def test_administrator_workspace_does_not_count_as_participant(self):
        result = read_runtime_state("complete", "claim-admin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PARSED:none:clean:complete", result.stdout)

    def test_kubernetes_failure_is_not_reported_as_neutral_success(self):
        result = read_runtime_state(fail_remote=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Mock Kubernetes failure", result.stderr)
        self.assertNotIn("PARSED:", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
