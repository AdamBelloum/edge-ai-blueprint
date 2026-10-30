import os
import re
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark/module-main.sh"


class OrganizerRuntimeMenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.record = self.directory / "calls.txt"
        for name in ("prepare-runtime.sh", "build-livy-image.sh", "start-livy-runtime.sh"):
            path = self.directory / name
            path.write_text(
                '#!/usr/bin/env bash\n'
                'printf "run:%s:%s\\n" "${0##*/}" "$*" >> "$TEST_RECORD"\n'
                'exit "${HELPER_RC:-0}"\n'
            )
            path.chmod(0o755)

    def invoke(self, action, input_text=None, **settings):
        env = os.environ.copy()
        env.update(TEST_RECORD=str(self.record), TEST_HELPER_DIR=str(self.directory),
                   GUARD_RC="0", CONFIRM_RC="0", HELPER_RC="0", DIGITAFRICA_ASSUME_YES="false")
        env.update(settings)
        script = 'source ' + shlex.quote(str(SOURCE)) + r'''
BIG_DATA_SPARK_MODULE_DIR="$TEST_HELPER_DIR"
ensure_workshop_activation_allowed() {
  printf 'guard:%s\n' "$*" >> "$TEST_RECORD"
  return "$GUARD_RC"
}
confirm() {
  printf 'confirm\n' >> "$TEST_RECORD"
  return "$CONFIRM_RC"
}
'''
        if settings.get('USE_REAL_CONFIRM') == '1':
            common = SOURCE.parents[3] / 'lib/common.sh'
            match = re.search(r'^confirm\(\) \{\n.*?^\}', common.read_text(),
                              re.MULTILINE | re.DOTALL)
            if match is None:
                raise AssertionError('Production confirm() definition not found')
            script += '\n' + match.group(0) + '\n'
        script += '\nbig_data_spark_runtime_action ' + shlex.quote(action) + '\n'
        if settings.get('USE_REAL_CONFIRM') == '1':
            script += r"""
status=$?
printf 'assume_yes_after:%s\n' "$DIGITAFRICA_ASSUME_YES"
exit "$status"
"""
        result = subprocess.run(["bash", "-c", script], env=env, input=input_text, text=True, capture_output=True)
        calls = self.record.read_text().splitlines() if self.record.exists() else []
        return result, calls

    def test_prepare_uses_livy_and_exactly_one_worker(self):
        result, calls = self.invoke("prepare")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ["guard:big-data", "confirm", "run:prepare-runtime.sh:livy 1"])

    def test_build_and_start_are_separate_existing_helpers(self):
        for action, name in (("build", "build-livy-image.sh"), ("start", "start-livy-runtime.sh")):
            with self.subTest(action=action):
                if self.record.exists():
                    self.record.unlink()
                result, calls = self.invoke(action)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, ["guard:big-data", "confirm", "run:" + name + ":"])
                self.assertIn("execution readiness remain unverified", result.stdout)

    def test_cleanup_guard_failure_prevents_confirmation_and_execution(self):
        result, calls = self.invoke("start", GUARD_RC="23")
        self.assertEqual(result.returncode, 23)
        self.assertEqual(calls, ["guard:big-data"])

    def test_declined_confirmation_runs_no_helper_even_with_assume_yes(self):
        result, calls = self.invoke("start", CONFIRM_RC="1", DIGITAFRICA_ASSUME_YES="true")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls, ["guard:big-data", "confirm"])
        self.assertIn("was not performed", result.stdout)

    def test_failure_propagates_without_success_claim(self):
        result, calls = self.invoke("start", HELPER_RC="19")
        self.assertEqual(result.returncode, 19)
        self.assertEqual(calls[-1], "run:start-livy-runtime.sh:")
        self.assertNotIn("completed successfully", result.stdout)
        self.assertIn("Inspect before retrying", result.stderr)

    def test_invalid_action_never_reaches_guard_or_helper(self):
        result, calls = self.invoke("unexpected")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_missing_helper_prevents_guard_and_execution(self):
        (self.directory / "start-livy-runtime.sh").unlink()
        result, calls = self.invoke("start")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(calls, [])

    def test_menu_routes_new_actions_and_returns_without_live_helpers(self):
        env = os.environ.copy()
        env["TEST_RECORD"] = str(self.record)
        script = 'source ' + shlex.quote(str(SOURCE)) + r'''
workshop_ui_heading() { :; }
workshop_ui_section() { :; }
workshop_ui_option() { :; }
workshop_ui_prompt() { :; }
big_data_spark_runtime_action() { printf '%s\n' "$1" >> "$TEST_RECORD"; }
run_big_data_spark_menu
'''
        result = subprocess.run(["bash", "-c", script], env=env,
                                input="4\n1\n2\n3\n0\n0\n", text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record.read_text().splitlines(), ["prepare", "build", "start"])


    def test_real_confirmation_requires_input_and_preserves_auto_yes_setting(self):
        for response in ('n\n', '\n', '', 'y\n'):
            with self.subTest(response=response):
                if self.record.exists():
                    self.record.unlink()
                result, calls = self.invoke('start', input_text=response,
                    USE_REAL_CONFIRM='1', DIGITAFRICA_ASSUME_YES='true')
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = ['guard:big-data']
                if response == 'y\n':
                    expected.append('run:start-livy-runtime.sh:')
                self.assertEqual(calls, expected)
                self.assertIn('assume_yes_after:true', result.stdout)
                self.assertNotIn('Automatically confirmed', result.stdout)


if __name__ == "__main__":
    unittest.main()
