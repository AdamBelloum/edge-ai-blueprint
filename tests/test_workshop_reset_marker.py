#!/usr/bin/env python3
"""Offline tests of the reset script's actual cleanup-marker builder."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESET = ROOT / (
    "scripts/workshops/reset-workshops.sh"
)
SOURCE = RESET.read_text()

START = "patch=\"\\$(printf '%s' \"\\$state\" | python3 -c '\n"
END = "\n')\""

if SOURCE.count(START) != 1:
    raise RuntimeError("Expected exactly one reset marker builder")
BUILDER = SOURCE.split(START, 1)[1].split(END, 1)[0]


def build_marker(data, version="42"):
    state = {"metadata": {"resourceVersion": version}, "data": data}
    return subprocess.run(
        [sys.executable, "-c", BUILDER],
        input=json.dumps(state),
        text=True,
        capture_output=True,
    )


class ResetMarkerTests(unittest.TestCase):
    def test_new_reset_records_current_selection(self):
        result = build_marker({
            "workshop_type": "big-data",
            "workshop_module": "spark",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        patch = json.loads(result.stdout)
        self.assertEqual(patch["metadata"]["resourceVersion"], "42")
        self.assertEqual(patch["data"], {
            "cleanup_status": "in_progress",
            "cleanup_workshop_type": "big-data",
            "cleanup_workshop_module": "spark",
        })

    def test_completed_reset_starts_new_context(self):
        result = build_marker({
            "workshop_type": "hpc",
            "workshop_module": "module1",
            "cleanup_status": "complete",
            "cleanup_workshop_type": "big-data",
            "cleanup_workshop_module": "spark",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)["data"]
        self.assertEqual(data["cleanup_workshop_type"], "hpc")
        self.assertEqual(data["cleanup_workshop_module"], "module1")

    def test_retry_preserves_original_context_after_neutral_selection(self):
        for status in ("in_progress", "failed"):
            with self.subTest(status=status):
                result = build_marker({
                    "workshop_type": "none",
                    "workshop_module": "none",
                    "cleanup_status": status,
                    "cleanup_workshop_type": "big-data",
                    "cleanup_workshop_module": "spark",
                })
                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)["data"]
                self.assertEqual(data["cleanup_status"], "in_progress")
                self.assertEqual(data["cleanup_workshop_type"], "big-data")
                self.assertEqual(data["cleanup_workshop_module"], "spark")

    def test_missing_retry_context_is_rejected_without_patch(self):
        result = build_marker({
            "workshop_type": "none",
            "cleanup_status": "in_progress",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_explicit_empty_or_null_status_is_rejected_without_patch(self):
        for status in ("", None):
            with self.subTest(status=status):
                result = build_marker({
                    "workshop_type": "hpc",
                    "workshop_module": "none",
                    "cleanup_status": status,
                })
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_unknown_status_is_rejected_without_patch(self):
        result = build_marker({
            "workshop_type": "hpc",
            "cleanup_status": "unexpected",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_invalid_workshop_or_module_is_rejected(self):
        for workshop, module in (
            ("unsupported", "none"),
            ("hpc", ""),
            ("hpc", None),
        ):
            with self.subTest(workshop=workshop, module=module):
                result = build_marker({
                    "workshop_type": workshop,
                    "workshop_module": module,
                })
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")

    def test_module3_records_delivery_scope(self):
        result = build_marker({
            "workshop_type": "cloud-computing-soa",
            "workshop_module": "module3",
            "cloud_module3_delivery_scope": "teaching-files-only",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["data"]["cleanup_cloud_module3_delivery_scope"],
            "teaching-files-only",
        )

    def test_module3_legacy_scope_is_unknown(self):
        result = build_marker({
            "workshop_type": "cloud-computing-soa",
            "workshop_module": "module3",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["data"]["cleanup_cloud_module3_delivery_scope"],
            "unknown",
        )

    def test_module3_retry_preserves_saved_scope_not_active_scope(self):
        for status in ("in_progress", "failed"):
            for saved_scope in ("unknown", "teaching-files-only"):
                with self.subTest(status=status, scope=saved_scope):
                    result = build_marker({
                        "workshop_type": "none",
                        "workshop_module": "none",
                        "cleanup_status": status,
                        "cleanup_workshop_type": "cloud-computing-soa",
                        "cleanup_workshop_module": "module3",
                        "cleanup_cloud_module3_delivery_scope": saved_scope,
                        "cloud_module3_delivery_scope": "different-active-scope",
                    })
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        json.loads(result.stdout)["data"][
                            "cleanup_cloud_module3_delivery_scope"
                        ],
                        saved_scope,
                    )

    def test_marker_precedes_destructive_actions(self):
        marker_position = SOURCE.index(START)
        confirmation_position = SOURCE.index(
            'case "$answer" in y|Y|yes|YES)'
        )
        self.assertLess(confirmation_position, marker_position)
        for action in (
            '"$FL_RESET_HELPER" --runtime-only',
            '\nstop_selected_participant_servers\n',
            '"$COHORT_HELPER" "${workspace_args[@]}"',
            '"$IDENTITY_RESET_HELPER" "${identity_reset_args[@]}"',
        ):
            self.assertLess(marker_position, SOURCE.index(action))


if __name__ == "__main__":
    unittest.main(verbosity=2)
