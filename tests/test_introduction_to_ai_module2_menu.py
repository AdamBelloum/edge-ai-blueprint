"""Offline regression checks for Introduction to AI Module 2 readiness routing."""

import os
from pathlib import Path
import pty
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "scripts/workshops/introduction-to-ai/course-main.sh"
HELPER = str(COURSE.parent / "module2.sh")

# Source the actual course controller but replace its execution boundary.
# No module helper, deployment context, SSH, or Kubernetes command is executed.
HARNESS = r'''
set -euo pipefail
source "$1"
run_introduction_to_ai_module() {
  printf 'CALL:%s\n' "$@"
  return "${STUB_STATUS:-0}"
}
workshop_ui_heading() { :; }
workshop_ui_section() { :; }
workshop_ui_option() { :; }
workshop_ui_prompt() { :; }
case "$2" in
  wrapper) run_introduction_to_ai_module2_check ;;
  menu) run_introduction_to_ai_module_menu 2 ;;
  *) exit 99 ;;
esac
'''


class Module2ReadinessMenuTests(unittest.TestCase):
    def run_controller(self, *, action="wrapper", mode=None,
                       terminal_input=None, stub_status=0):
        environment = os.environ.copy()
        environment.pop("INTRODUCTION_TO_AI_MODE", None)
        environment["STUB_STATUS"] = str(stub_status)
        if mode is not None:
            environment["INTRODUCTION_TO_AI_MODE"] = mode

        command = ["bash", "-c", HARNESS, "menu-test", str(COURSE), action]
        options = dict(
            cwd=ROOT, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
        )
        if terminal_input is None:
            return subprocess.run(command, stdin=subprocess.DEVNULL, **options)

        # A real terminal is needed for the wrapper's '-t 0' guard.
        # Keep the master open during execution so stdin remains a terminal.
        master, slave = pty.openpty()
        try:
            os.write(master, terminal_input.encode())
            return subprocess.run(command, stdin=slave, **options)
        finally:
            os.close(slave)
            os.close(master)

    def assert_dispatch(self, result, action, mode=None, returncode=0):
        arguments = [HELPER, action]
        if mode is not None:
            arguments += ["--mode", mode]
        self.assertEqual(result.returncode, returncode, result.stderr)
        self.assertEqual(
            [line for line in result.stdout.splitlines() if line.strip()],
            [f"CALL:{argument}" for argument in arguments],
        )

    def test_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(COURSE)], text=True,
            capture_output=True, timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_environment_modes(self):
        for mode in ("beginner", "advanced"):
            with self.subTest(mode=mode):
                result = self.run_controller(mode=mode)
                self.assert_dispatch(result, "check", mode)
                self.assertNotIn("Select an option:", result.stderr)

    def test_missing_noninteractive_mode_rejects_without_dispatch(self):
        result = self.run_controller()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("non-interactive shell", result.stderr)

    def test_invalid_environment_mode_rejects_without_dispatch(self):
        for mode in ("intermediate", "solutions", "BEGINNER"):
            with self.subTest(mode=mode):
                result = self.run_controller(mode=mode)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout.strip(), "")
                self.assertIn("no check started", result.stderr)

    def test_interactive_track_selection(self):
        for choice, mode in (("1", "beginner"), ("2", "advanced")):
            with self.subTest(mode=mode):
                result = self.run_controller(terminal_input=f"{choice}\n")
                self.assert_dispatch(result, "check", mode)
                self.assertIn("does not publish", result.stderr)

    def test_interactive_back_does_not_dispatch(self):
        result = self.run_controller(terminal_input="0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_invalid_choice_reprompts_before_dispatch(self):
        result = self.run_controller(terminal_input="9\n1\n")
        self.assert_dispatch(result, "check", "beginner")
        self.assertIn("Choose 0, 1, or 2.", result.stderr)
        self.assertEqual(result.stderr.count("Select an option:"), 2)

    def test_helper_failure_is_preserved(self):
        result = self.run_controller(mode="beginner", stub_status=7)
        self.assert_dispatch(result, "check", "beginner", returncode=7)

    def test_actual_module2_menu_readiness_routes_both_tracks(self):
        for choice, mode in (("1", "beginner"), ("2", "advanced")):
            with self.subTest(mode=mode):
                # Main Module 2 option 1, track selection, then back.
                result = self.run_controller(
                    action="menu", terminal_input=f"1\n{choice}\n0\n",
                )
                self.assert_dispatch(result, "check", mode)

    def test_actual_menu_returns_after_cancel_without_dispatch(self):
        result = self.run_controller(action="menu", terminal_input="1\n0\n0\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_publication_and_release_routes_remain_separate(self):
        for choice, action, mode in (
            ("2", "activate", "beginner"),
            ("3", "activate", "advanced"),
            ("4", "release-solutions", None),
        ):
            with self.subTest(choice=choice):
                result = self.run_controller(
                    action="menu", terminal_input=f"{choice}\n0\n",
                )
                self.assert_dispatch(result, action, mode)


if __name__ == "__main__":
    unittest.main()
