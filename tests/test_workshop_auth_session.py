"""Offline tests of actual authentication functions with mocked dependencies."""
import os
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROLLERS = [
    ROOT / "scripts/workshops/organizer-main.sh",
    ROOT / "scripts/workshops/identity/cohort-workshop.sh",
    ROOT / "scripts/workshops/lib/reset-auth-session.sh",
]

MOCKS = r'''
unset KEYCLOAK_ADMIN_PASSWORD_FILE
ADMIN_CLIENT_ID=""
ADMIN_CLIENT_SECRET_FILE=""
ADMIN_PASSWORD_SESSION_VERIFIED=false
ADMIN_PASSWORD_SESSION_FILE_OWNED=false
ACCOUNT_ARGS=()
ACCOUNT_HELPER=mock_account
account_calls=0

fail() {
  printf 'FAIL %s\n' "$*" >&2
  exit 2
}
create_admin_password_session() {
  printf 'EVENT create\n'
  ADMIN_PASSWORD_SESSION_FILE_OWNED=true
}
clear_admin_password_session() {
  printf 'EVENT clear\n'
  ADMIN_PASSWORD_SESSION_FILE_OWNED=false
  ADMIN_PASSWORD_SESSION_VERIFIED=false
}
mock_account() {
  account_calls=$((account_calls + 1))
  printf 'EVENT account\n' >&2
  if [[ "$account_calls" -eq 1 ]]; then
    return "$FIRST_STATUS"
  fi
  return "$LATER_STATUS"
}
'''


def run_functions(path, setup, action, first=0, later=0):
    source = path.read_text()
    functions = []
    for name in ("ensure_admin_password_session", "run_account_helper"):
        matches = re.findall(
            rf"(?ms)^{name}\(\) \{{\n.*?^\}}", source
        )
        if len(matches) != 1:
            raise RuntimeError(f"Expected one {name} definition in {path}")
        functions.append(matches[0])

    env = dict(os.environ, FIRST_STATUS=str(first), LATER_STATUS=str(later))
    script = (
        "set -euo pipefail\n" + MOCKS + "\n"
        + "\n".join(functions) + "\n" + setup + "\n" + action + "\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        text=True, capture_output=True, env=env, timeout=10,
    )


class AuthenticationSessionTests(unittest.TestCase):
    def check(self, setup, action, first, later, status,
              creates, clears, accounts, message=None):
        for path in CONTROLLERS:
            with self.subTest(controller=str(path.relative_to(ROOT))):
                result = run_functions(path, setup, action, first, later)
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, status, output)
                self.assertEqual(output.count("EVENT create\n"), creates, output)
                self.assertEqual(output.count("EVENT clear\n"), clears, output)
                self.assertEqual(output.count("EVENT account\n"), accounts, output)
                if message:
                    self.assertIn(message, output)

    def test_interactive_authentication_retries_rejected_password(self):
        self.check("", "ensure_admin_password_session",
                   10, 0, 0, 2, 1, 2)

    def test_three_rejections_stop_authentication(self):
        self.check("", "ensure_admin_password_session",
                   10, 10, 2, 3, 3, 3, "after 3 attempts")

    def test_external_password_rejection_is_not_retried(self):
        self.check(
            'export KEYCLOAK_ADMIN_PASSWORD_FILE=/mock/external-password',
            "ensure_admin_password_session",
            10, 0, 2, 0, 0, 1, "rejected by Keycloak",
        )

    def test_non_authentication_failure_is_preserved(self):
        self.check(
            "ADMIN_PASSWORD_SESSION_VERIFIED=true",
            "run_account_helper --status",
            7, 0, 7, 0, 0, 1,
        )

    def test_cached_owned_password_rejection_refreshes_session(self):
        self.check(
            "ADMIN_PASSWORD_SESSION_VERIFIED=true\n"
            "ADMIN_PASSWORD_SESSION_FILE_OWNED=true",
            "run_account_helper --status",
            10, 0, 0, 1, 1, 3,
        )

    def test_service_account_failure_is_preserved_without_password_prompt(self):
        self.check(
            'ADMIN_CLIENT_ID=mock-client\nADMIN_CLIENT_SECRET_FILE=/mock/secret',
            "run_account_helper --status",
            1, 0, 1, 0, 0, 1,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
