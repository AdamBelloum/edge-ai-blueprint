"""Offline account-choice routing tests; all operational helpers are mocked."""
import os
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTES = [
    ROOT / "scripts/workshops/controllers/cohort.sh",
    ROOT / "scripts/workshops/identity/cohort-workshop.sh",
]

MOCKS = r'''
build_account_args() {
  printf '\nCALL build\n'
  ACCOUNT_ARGS=(--server-url https://example.invalid --admin-user admin)
}
run_account_helper() {
  printf '\nCALL account'
  printf ' <%s>' "$@"
  printf '\n'
  return "$MOCK_AUTH_STATUS"
}
mock_reset() {
  printf '\nCALL reset'
  printf ' <%s>' "$@"
  printf '\n'
  return "$MOCK_RESET_STATUS"
}
RESET_HELPER=mock_reset
'''


def run_route(path, answers, auth_status=0, reset_status=0):
    matches = re.findall(
        r"(?ms)^run_reset\(\) \{\n.*?^\}", path.read_text()
    )
    if len(matches) != 1:
        raise RuntimeError(f"Expected one reset function: {path}")
    environment = dict(os.environ)
    environment.update(
        MOCK_AUTH_STATUS=str(auth_status),
        MOCK_RESET_STATUS=str(reset_status),
    )
    return subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + MOCKS + matches[0] + "\nrun_reset\n"],
        input=answers,
        text=True,
        capture_output=True,
        env=environment,
        timeout=10,
    )


class AccountChoiceTests(unittest.TestCase):
    def check_routes(self, answers, expected_calls, expected_status=0,
                     auth_status=0, reset_status=0):
        for path in ROUTES:
            with self.subTest(route=str(path.relative_to(ROOT))):
                result = run_route(path, answers, auth_status, reset_status)
                self.assertEqual(
                    result.returncode, expected_status,
                    result.stdout + result.stderr,
                )
                calls = [
                    line for line in result.stdout.splitlines()
                    if line.startswith("CALL ")
                ]
                self.assertEqual(calls, expected_calls)

    def test_empty_selection_keeps_accounts_without_keycloak(self):
        self.check_routes("\n", ["CALL reset <--accounts> <keep>"])

    def test_explicit_keep_without_keycloak(self):
        self.check_routes("1\n", ["CALL reset <--accounts> <keep>"])

    def test_confirmed_delete_checks_access_before_reset(self):
        self.check_routes("2\ny\n", [
            "CALL build",
            "CALL account <--status>",
            "CALL reset <--accounts> <delete> <--server-url> "
            "<https://example.invalid> <--admin-user> <admin>",
        ])

    def test_authentication_failure_prevents_reset(self):
        self.check_routes(
            "2\ny\n", ["CALL build", "CALL account <--status>"],
            expected_status=10, auth_status=10,
        )

    def test_other_preflight_failure_prevents_reset(self):
        self.check_routes(
            "2\ny\n", ["CALL build", "CALL account <--status>"],
            expected_status=1, auth_status=1,
        )

    def test_declined_deletion_cancels_without_helpers(self):
        self.check_routes("2\nn\n", [])

    def test_cancel_without_helpers(self):
        self.check_routes("0\n", [])

    def test_eof_cancels_without_helpers(self):
        self.check_routes("", [])
        self.check_routes("2\n", [])

    def test_invalid_selection_without_helpers(self):
        self.check_routes("unexpected\n", [], expected_status=2)

    def test_reset_failure_is_preserved(self):
        self.check_routes(
            "1\n", ["CALL reset <--accounts> <keep>"],
            expected_status=7, reset_status=7,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
