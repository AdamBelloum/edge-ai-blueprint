"""Offline tests of the actual neutral-reset preflight expressions."""
import json
from pathlib import Path
import unittest

import yaml
from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
TASKS = yaml.safe_load(
    (ROOT / "roles/k8s_apps/tasks/install.yml").read_text()
)
GUARD_NAME = "Validate neutral-reset state before application reconciliation"
GUARD = TASKS[0]
ENVIRONMENT = Environment(undefined=StrictUndefined)
ENVIRONMENT.filters.update(FilterModule().filters())
ASSERTIONS = GUARD["block"][1]["ansible.builtin.assert"]["that"]

VALID_STATE = {
    "workshop_type": "none",
    "workshop_module": "none",
    "mode": "beginner",
    "solutions_released": "false",
    "cleanup_status": "in_progress",
}


def evaluate(state, **settings):
    context = {
        "workshop_neutral_reset_state": {
            "stdout": json.dumps({"data": state}),
        },
        **settings,
    }
    return [
        ENVIRONMENT.compile_expression(expression)(**context)
        for expression in ASSERTIONS
    ]


class NeutralResetGuardTests(unittest.TestCase):
    def test_guard_is_first_and_tagged_for_reconciliation(self):
        self.assertEqual(GUARD["name"], GUARD_NAME)
        self.assertEqual(
            GUARD["tags"], ["workshop_application_reconciliation"]
        )
        self.assertEqual(len(GUARD["block"]), 2)

    def test_ordinary_reconciliation_skips_guard(self):
        condition = ENVIRONMENT.compile_expression(GUARD["when"])
        self.assertFalse(condition())
        self.assertFalse(condition(workshop_reset_neutral=False))
        self.assertTrue(condition(workshop_reset_neutral=True))

    def test_state_read_is_required_and_read_only(self):
        read = GUARD["block"][0]
        argv = read["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[-5:], [
            "get", "configmap", "digitafrica-workshop-state", "-o", "json"
        ])
        self.assertNotIn("--ignore-not-found", argv)
        self.assertFalse(read["changed_when"])
        self.assertFalse(read["check_mode"])
        self.assertNotIn("ignore_errors", read)
        self.assertNotIn("failed_when", read)

    def test_valid_neutral_state_passes_without_optional_settings(self):
        self.assertTrue(all(evaluate(VALID_STATE)))

    def test_each_missing_or_conflicting_state_field_is_rejected(self):
        for field in VALID_STATE:
            for value in (None, "", "unexpected"):
                with self.subTest(field=field, value=value):
                    state = dict(VALID_STATE)
                    state[field] = value
                    self.assertFalse(all(evaluate(state)))
            with self.subTest(field=field, missing=True):
                state = dict(VALID_STATE)
                del state[field]
                self.assertFalse(all(evaluate(state)))

    def test_other_cleanup_statuses_are_rejected(self):
        for status in ("complete", "failed", "legacy"):
            with self.subTest(status=status):
                state = dict(VALID_STATE, cleanup_status=status)
                self.assertFalse(all(evaluate(state)))

    def test_each_optional_integration_must_be_disabled(self):
        for setting in (
            "hpc_runtime_enabled",
            "cloud_module3_delivery_enabled",
            "cloud_module5_delivery_enabled",
        ):
            with self.subTest(setting=setting):
                self.assertFalse(all(evaluate(
                    VALID_STATE, **{setting: True}
                )))
                self.assertTrue(all(evaluate(
                    VALID_STATE, **{setting: False}
                )))

    def test_malformed_json_fails_evaluation(self):
        expression = ENVIRONMENT.compile_expression(ASSERTIONS[0])
        with self.assertRaises(ValueError):
            expression(
                workshop_neutral_reset_state={"stdout": "{invalid"}
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
