"""Offline direct-reset preflight tests; operational dependencies are mocked."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESET = ROOT / (
    "scripts/workshops/reset-workshops.sh"
)
SOURCE = RESET.read_text()
START = "# Authenticate before recording cleanup or removing any runtime/workspace."
END = "# Persist retry context before the first destructive operation."

if SOURCE.count(START) != 1 or SOURCE.count(END) != 1:
    raise RuntimeError("Expected unique preflight boundaries")
PREFLIGHT = SOURCE.split(START, 1)[1].split(END, 1)[0]


def run_preflight(action, status=0, service=False):
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        account = directory / "mock-account"
        account.write_text("#!/bin/sh\nexit 99\n")
        account.chmod(0o700)
        library = directory / "mock-session.sh"
        library.write_text(r'''
printf 'EVENT library\n'
clear_admin_password_session() {
  printf 'EVENT clear\n'
}
run_account_helper() {
  printf 'EVENT account'
  printf ' <%s>' "${ACCOUNT_ARGS[@]}" "$@"
  printf '\n'
  return "$MOCK_STATUS"
}
''')
        # For keep, deliberately supply missing dependencies.
        account_path = account if action == "delete" else directory / "absent-account"
        library_path = library if action == "delete" else directory / "absent-library"
        setup = r'''
set -euo pipefail
fail() { printf 'FAIL %s\n' "$*" >&2; exit 2; }
ACCOUNT_ACTION="$1"
MOCK_STATUS="$2"
ACCOUNT_HELPER="$3"
RESET_AUTH_SESSION="$4"
SERVER_URL=https://example.invalid
REALM=digitafrica
ADMIN_REALM=master
ADMIN_USER=admin
ADMIN_CLIENT_ID=""
ADMIN_CLIENT_SECRET_FILE=""
if [[ "$5" == service ]]; then
  ADMIN_USER=""
  ADMIN_CLIENT_ID=mock-client
  ADMIN_CLIENT_SECRET_FILE=/mock/secret
fi
'''
        return subprocess.run(
            [
                "bash", "-c",
                setup + PREFLIGHT + "\nprintf 'EVENT cleanup-boundary\\n'\n",
                "preflight-test", action, str(status),
                str(account_path), str(library_path),
                "service" if service else "password",
            ],
            text=True, capture_output=True, timeout=10,
        )


class DirectPreflightTests(unittest.TestCase):
    def test_keep_skips_authentication_even_with_missing_dependencies(self):
        result = run_preflight("keep")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "EVENT cleanup-boundary\n")

    def test_password_arguments_and_exit_cleanup(self):
        result = run_preflight("delete")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "EVENT account <--server-url> <https://example.invalid> "
            "<--realm> <digitafrica> <--admin-realm> <master> "
            "<--admin-user> <admin> <--status>",
            result.stdout,
        )
        self.assertLess(
            result.stdout.index("EVENT account"),
            result.stdout.index("EVENT cleanup-boundary"),
        )
        self.assertTrue(result.stdout.endswith("EVENT clear\n"))

    def test_service_account_arguments(self):
        result = run_preflight("delete", service=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "<--admin-client-id> <mock-client> "
            "<--admin-client-secret-file> </mock/secret> <--status>",
            result.stdout,
        )
        self.assertNotIn("<--admin-user>", result.stdout)

    def test_failures_block_cleanup_and_preserve_status(self):
        for status in (1, 7, 10):
            with self.subTest(status=status):
                result = run_preflight("delete", status=status)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertNotIn("EVENT cleanup-boundary", result.stdout)
                self.assertIn("no destructive cleanup was started", result.stderr)
                self.assertTrue(result.stdout.endswith("EVENT clear\n"))

    def test_confirmation_precedes_preflight_and_marker_follows_it(self):
        confirmation = SOURCE.index('case "$answer" in y|Y|yes|YES)')
        preflight = SOURCE.index(START)
        marker = SOURCE.index(END)
        self.assertLess(confirmation, preflight)
        self.assertLess(preflight, marker)
        for operation in (
            '"$FL_RESET_HELPER" --runtime-only',
            '\nstop_selected_participant_servers\n',
            '"$COHORT_HELPER" "${workspace_args[@]}"',
            '"$IDENTITY_RESET_HELPER" "${identity_reset_args[@]}"',
        ):
            self.assertLess(marker, SOURCE.index(operation))


if __name__ == "__main__":
    unittest.main(verbosity=2)
