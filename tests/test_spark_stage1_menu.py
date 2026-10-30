"""Stage 1 orchestration tests: mocked helpers, no deployment or credentials."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'scripts/workshops/big-data/spark/module-main.sh'


class Stage1MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = self.root / 'calls.txt'
        self.helpers = self.root / 'helpers'
        self.helpers.mkdir()
        self.cohort = self.helpers / 'cohort-workshop.sh'
        scripts = {
            'cohort-workshop.sh': r'''printf 'cohort:%s\n' "$*" >> "$TEST_RECORD"
exit "${MOCK_COHORT_RC:-0}"
''',
            'participant-direct-runtime.sh': r'''printf 'direct:%s\n' "$*" >> "$TEST_RECORD"
exit "${MOCK_DIRECT_RC:-0}"
''',
            'participant-credentials.sh': r'''printf 'credentials:%s\n' "$*" >> "$TEST_RECORD"
case "$1" in
  plan) exit "${MOCK_PLAN_RC:-0}" ;;
  apply) exit "${MOCK_APPLY_RC:-0}" ;;
  verify) exit "${MOCK_VERIFY_RC:-0}" ;;
  *) exit 99 ;;
esac
''',
        }
        for name, script in scripts.items():
            path = self.helpers / name
            path.write_text('#!/usr/bin/env bash\n' + script)
            path.chmod(0o755)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        ansible = self.bin / 'ansible-playbook'
        ansible.write_text('#!/usr/bin/env bash\nprintf "UNEXPECTED_ANSIBLE\\n" >> "$TEST_RECORD"\nexit 99\n')
        ansible.chmod(0o755)

    def invoke(self, entry, input_text='', readonly=False, **settings):
        if self.record.exists():
            self.record.unlink()
        env = os.environ.copy()
        env.update(
            TEST_RECORD=str(self.record), TEST_HELPERS=str(self.helpers),
            TEST_COHORT=str(self.cohort),
            DIGITAFRICA_INVENTORY=str(self.root / 'fixture.ini'),
            DIGITAFRICA_DEPLOYMENT_GROUP='tier2_server',
            DIGITAFRICA_DEPLOYMENT_WORKER_GROUP='tier2_agents',
            DIGITAFRICA_NAMESPACE='digitafrica',
            MOCK_GUARD_RC='0', MOCK_COHORT_RC='0', MOCK_DIRECT_RC='0',
            MOCK_PLAN_RC='0', MOCK_APPLY_RC='0', MOCK_VERIFY_RC='0',
            MOCK_CONFIRM_RC='0', MOCK_RECONCILE_RC='0',
            ASSUME_YES='true', DIGITAFRICA_ASSUME_YES='true',
        )
        env.update(settings)
        env['PATH'] = str(self.bin) + os.pathsep + env.get('PATH', '')
        script = 'set -e\nsource ' + shlex.quote(str(MODULE)) + r'''
BIG_DATA_SPARK_MODULE_DIR="$TEST_HELPERS"
BIG_DATA_COHORT_WORKFLOW="$TEST_COHORT"
ensure_workshop_activation_allowed() {
  printf 'guard:%s\n' "$*" >> "$TEST_RECORD"
  return "$MOCK_GUARD_RC"
}
workshop_ui_heading() { printf 'HEADING:%s\n' "$*"; }
workshop_ui_section() { printf 'SECTION:%s\n' "$*"; }
workshop_ui_option() { printf 'OPTION:%s:%s\n' "$1" "$2"; }
workshop_ui_prompt() { :; }
big_data_spark_show_status() { printf 'selection-status\n' >> "$TEST_RECORD"; }
confirm() { printf 'confirm:publication\n' >> "$TEST_RECORD"; return "$MOCK_CONFIRM_RC"; }
log() { :; }
big_data_spark_prepare_workspace() { printf 'publish-assets\n' >> "$TEST_RECORD"; }
run_deployment_remote() { printf 'remote-state\n' >> "$TEST_RECORD"; }
run_application_reconciliation() { printf 'reconcile\n' >> "$TEST_RECORD"; return "$MOCK_RECONCILE_RC"; }
big_data_spark_runtime_action() { printf 'UNEXPECTED_LIVY\n' >> "$TEST_RECORD"; return 99; }
big_data_spark_computation_test() { printf 'UNEXPECTED_ORGANISER_TEST\n' >> "$TEST_RECORD"; return 99; }
'''
        if readonly:
            script += 'readonly DIGITAFRICA_INVENTORY DIGITAFRICA_DEPLOYMENT_GROUP DIGITAFRICA_DEPLOYMENT_WORKER_GROUP DIGITAFRICA_NAMESPACE\n'
        result = subprocess.run(
            ['bash', '-c', script + '\n' + entry + '\n'],
            env=env, input=input_text, text=True, capture_output=True, timeout=10,
        )
        calls = self.record.read_text().splitlines() if self.record.exists() else []
        return result, calls

    def test_preflight_reuses_readonly_context_and_existing_cohort_guard(self):
        result, calls = self.invoke('big_data_spark_stage1_action check', readonly=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['guard:big-data', 'cohort:require-complete'])
        self.assertIn('does not verify bind addresses', result.stdout)

    def test_prepare_and_start_delegate_only_to_direct_helper(self):
        for action in ('prepare', 'start'):
            with self.subTest(action=action):
                result, calls = self.invoke('big_data_spark_stage1_action ' + action)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, ['guard:big-data', 'cohort:require-complete', 'direct:' + action])
                self.assertIn('readiness remains unverified', result.stdout)

    def test_credentials_run_plan_before_apply(self):
        result, calls = self.invoke('big_data_spark_stage1_action credentials')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['guard:big-data', 'cohort:require-complete', 'credentials:plan', 'credentials:apply'])
        self.assertIn('publication and participant validation are still required', result.stdout)

    def test_failed_plan_prevents_apply(self):
        result, calls = self.invoke('big_data_spark_stage1_action credentials', MOCK_PLAN_RC='17')
        self.assertEqual(result.returncode, 17)
        self.assertEqual(calls[-1], 'credentials:plan')
        self.assertNotIn('credentials:apply', calls)
        self.assertNotIn('Credential staging completed', result.stdout)

    def test_failed_or_cancelled_apply_does_not_claim_completion(self):
        result, calls = self.invoke('big_data_spark_stage1_action credentials', MOCK_APPLY_RC='1')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls[-1], 'credentials:apply')
        self.assertNotIn('Credential staging completed', result.stdout)
        self.assertIn('failed/cancelled', result.stderr)

    def test_guard_and_cohort_failures_block_runtime(self):
        for settings, expected, calls_expected in (
            ({'MOCK_GUARD_RC': '23'}, 23, ['guard:big-data']),
            ({'MOCK_COHORT_RC': '19'}, 19, ['guard:big-data', 'cohort:require-complete']),
        ):
            with self.subTest(settings=settings):
                result, calls = self.invoke('big_data_spark_stage1_action start', **settings)
                self.assertEqual(result.returncode, expected)
                self.assertEqual(calls, calls_expected)

    def test_bad_context_blocks_all_helpers(self):
        for settings in (
            {'DIGITAFRICA_INVENTORY': ''},
            {'DIGITAFRICA_DEPLOYMENT_GROUP': 'all:*'},
            {'DIGITAFRICA_DEPLOYMENT_WORKER_GROUP': 'workers,outsiders'},
            {'DIGITAFRICA_NAMESPACE': 'Bad_Namespace'},
            {'DIGITAFRICA_NAMESPACE': 'a' * 64},
        ):
            with self.subTest(settings=settings):
                result, calls = self.invoke('big_data_spark_stage1_action prepare', **settings)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(calls, [])

    def test_missing_helper_blocks_preflight(self):
        (self.helpers / 'participant-credentials.sh').unlink()
        result, calls = self.invoke('big_data_spark_stage1_action check')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_direct_failure_propagates_without_success_claim(self):
        result, calls = self.invoke('big_data_spark_stage1_action start', MOCK_DIRECT_RC='19')
        self.assertEqual(result.returncode, 19)
        self.assertEqual(calls[-1], 'direct:start')
        self.assertNotIn('helper completed', result.stdout)
        self.assertIn('Inspect current state', result.stderr)

    def test_removed_and_invalid_actions_are_blocked_without_side_effects(self):
        for action in ('validate', 'unexpected'):
            with self.subTest(action=action):
                result, calls = self.invoke('big_data_spark_stage1_action ' + action)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(calls, [])
                self.assertIn('Unsupported Stage 1 action', result.stderr)

    def test_menu_displays_workflow_order_without_actions(self):
        result, calls = self.invoke('big_data_spark_stage1_menu', input_text='0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        labels = [
            'OPTION:1:Check selected context and participant cohort',
            'OPTION:2:Prepare direct runtime and credential exports',
            'OPTION:3:Start direct runtime and apply network access',
            'OPTION:4:Plan, confirm and stage participant credentials',
            'OPTION:5:Publish Step 1 after credential verification',
            'OPTION:7:Show existing workshop selection status (not readiness)',
        ]
        positions = [result.stdout.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('OPTION:6:', result.stdout)
        self.assertIn('Participant readiness is NOT validated', result.stdout)
        self.assertIn('teardown is not a normal stop', result.stdout)
        self.assertEqual(calls, [])

    def test_menu_routes_actions_and_verifies_before_publication_without_livy(self):
        result, calls = self.invoke('big_data_spark_stage1_menu', input_text='1\n2\n3\n4\n5\n7\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            'guard:big-data', 'cohort:require-complete',
            'guard:big-data', 'cohort:require-complete', 'direct:prepare',
            'guard:big-data', 'cohort:require-complete', 'direct:start',
            'guard:big-data', 'cohort:require-complete', 'credentials:plan', 'credentials:apply',
            'cohort:require-complete', 'guard:big-data', 'credentials:verify',
            'confirm:publication', 'publish-assets', 'remote-state', 'reconcile',
            'selection-status',
        ])
        self.assertIn('execution readiness remain unverified', result.stdout)
        self.assertEqual(result.stderr, '')

    def test_removed_menu_option_is_rejected_without_helpers(self):
        result, calls = self.invoke('big_data_spark_stage1_menu', input_text='6\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])
        self.assertNotIn('OPTION:6:', result.stdout)
        self.assertIn('Choose 0, 1, 2, 3, 4, 5 or 7.', result.stderr)

    def test_failed_verification_blocks_publication_before_confirmation(self):
        result, calls = self.invoke('big_data_spark_stage1_action publish', MOCK_VERIFY_RC='2')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, ['cohort:require-complete', 'guard:big-data', 'credentials:verify'])
        self.assertNotIn('publish-assets', calls)

    def test_canonical_republication_uses_the_same_gate(self):
        result, calls = self.invoke('big_data_spark_activate_selected_mode beginner', MOCK_VERIFY_RC='2')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls[-1], 'credentials:verify')
        self.assertNotIn('confirm:publication', calls)
        self.assertNotIn('remote-state', calls)

    def test_declined_publication_does_not_mutate_even_with_auto_yes(self):
        result, calls = self.invoke('big_data_spark_stage1_action publish', MOCK_CONFIRM_RC='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['cohort:require-complete', 'guard:big-data', 'credentials:verify', 'confirm:publication'])
        self.assertNotIn('publish-assets', calls)

    def test_successful_publication_does_not_claim_execution_readiness(self):
        result, calls = self.invoke('big_data_spark_stage1_action publish')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['cohort:require-complete', 'guard:big-data', 'credentials:verify', 'confirm:publication', 'publish-assets', 'remote-state', 'reconcile'])
        self.assertIn('publication completed', result.stdout)
        self.assertIn('execution readiness remain unverified', result.stdout)

    def test_reconciliation_failure_reports_partial_publication(self):
        result, calls = self.invoke('big_data_spark_stage1_action publish', MOCK_RECONCILE_RC='19')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls[-2:], ['remote-state', 'reconcile'])
        self.assertIn('selection was written, but application reconciliation failed', result.stderr)
        self.assertNotIn('publication completed', result.stdout)

    def test_primary_menu_enters_real_stage1_submenu_without_helpers(self):
        result, calls = self.invoke('run_big_data_spark_menu', input_text='1\n0\n0\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('HEADING:Spark / Stage 1 - Direct submission', result.stdout)
        self.assertEqual(result.stdout.count('HEADING:Big Data / Spark Beginner'), 2)
        self.assertEqual(calls, [])

    def test_menu_eof_exits_without_helpers(self):
        result, calls = self.invoke('big_data_spark_stage1_menu')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
