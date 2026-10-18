"""Offline OpenFaaS routing tests; no platform or deployment validation."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENTRY = Path("scripts/workshops/organizer-main.sh")
MODULE = Path("scripts/workshops/cloud-computing-soa/openfaas/module-main.sh")


class OpenFaaSOrganizerTests(unittest.TestCase):
    """Exercise routing with all infrastructure dependencies absent."""

    def setUp(self):
        """Copy only the entry point and module into a disposable checkout."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for relative in (ENTRY, MODULE):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def run_action(self, *arguments):
        """Run from outside the checkout and bound execution time."""
        return subprocess.run(
            ["bash", str(self.root / ENTRY), *arguments],
            cwd="/",
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_status_bypasses_missing_deployment_context(self):
        """Report authoring status without loading infrastructure helpers."""
        result = self.run_action("cloud-module5-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pre-live authoring", result.stdout)
        self.assertIn("remain unvalidated", result.stdout)

    def test_publish_is_blocked_without_deployment_context(self):
        """Reject publication before any infrastructure dependency loads."""
        result = self.run_action("cloud-module5-publish")
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLOCKED:", result.stderr)
        self.assertIn("No workshop selection", result.stderr)

    def test_check_fails_when_assets_are_absent(self):
        """Missing teaching assets must never count as successful validation."""
        result = self.run_action("cloud-module5-check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Pre-live checker is not yet staged", result.stderr)
        self.assertIn(str(self.root / "workshop_assets"), result.stderr)

    def test_invalid_options_are_rejected_before_offline_dispatch(self):
        """Preserve the existing action-specific option validation."""
        result = self.run_action("--mode", "beginner", "cloud-module5-status")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--mode is valid only with fl-prepare", result.stderr)
        self.assertNotIn("pre-live authoring", result.stdout)

    def test_missing_controller_fails_clearly(self):
        """Do not silently succeed if the module controller is missing."""
        (self.root / MODULE).unlink()
        result = self.run_action("cloud-module5-status")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing OpenFaaS module controller", result.stderr)

    def test_menu_status_and_back_need_no_shared_helpers(self):
        """Exercise the module menu without context or authentication."""
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; run_cloud_module5_menu',
             "_", str(self.root / MODULE)],
            input="2\n0\n",
            cwd="/",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pre-live authoring", result.stdout)
        self.assertNotIn("Activate beginner", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
