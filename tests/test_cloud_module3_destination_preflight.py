"""Local preflight tests; no copying, real ownership or live pod validation."""
from pathlib import Path
import shutil
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import test_cloud_module3_preflight as source_tests

ROOT = source_tests.ROOT


class Module3DestinationPreflightTests(source_tests.Module3PreflightTests):
    # Inherit source tests to verify they also hold with destination preflight.
    def setUp(self):
        super().setUp()
        environment = Environment(
            loader=FileSystemLoader(str(ROOT / "roles/k8s_apps/templates")),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )
        destination = environment.get_template(
            "workshop-hooks/cloud-module3-destination-preflight.sh.j2"
        ).render().format(**{})
        destination = destination.replace("/home/jovyan", str(self.home))
        self.script += "\n" + destination
        self.workspace = self.home / "Cloud-Computing-SOA/Module-3"

    def run_hook(self, **settings):
        # Parent runner asserts that home is absent. Existing-home cases
        # instead verify preservation explicitly below.
        existing_home = self.home
        self.home = self.root / "never-created-sentinel"
        try:
            return super().run_hook(**settings)
        finally:
            self.home = existing_home

    def clear_home(self):
        if self.home.is_symlink():
            self.home.unlink()
        elif self.home.exists():
            shutil.rmtree(self.home)

    def test_fresh_destination_preflight_creates_nothing(self):
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("destination preflight passed", result.stdout)
        self.assertFalse(self.home.exists())

    def test_directory_symlinks_and_dangling_symlinks_fail(self):
        destinations = (
            self.home,
            self.home / "Cloud-Computing-SOA",
            self.workspace,
            self.workspace / "beginner",
            self.workspace / "beginner/containerization",
            self.workspace / "beginner/containerization/auth_service",
            self.workspace / "tests",
        )
        for dangling in (False, True):
            for path in destinations:
                with self.subTest(path=path, dangling=dangling):
                    outside = self.root / (
                        "missing-target" if dangling else "outside"
                    )
                    if not dangling:
                        outside.mkdir(exist_ok=True)
                        (outside / "sentinel").write_text("unchanged\n")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.symlink_to(outside, target_is_directory=True)
                    try:
                        result = self.run_hook()
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("directory is a symlink", result.stderr)
                        self.assertTrue(path.is_symlink())
                        if not dangling:
                            self.assertEqual(
                                (outside / "sentinel").read_text(), "unchanged\n"
                            )
                    finally:
                        path.unlink()
                        self.clear_home()

    def test_file_and_receipt_symlinks_fail(self):
        for relative in (
            "beginner/containerization/auth_service/auth.py",
            "beginner/MODULE3_DELIVERY_RECEIPT.txt",
            "tests/MODULE3_DELIVERY_RECEIPT.txt",
        ):
            for dangling in (False, True):
                with self.subTest(relative=relative, dangling=dangling):
                    outside = self.root / (
                        "missing-file" if dangling else "outside-file"
                    )
                    if not dangling:
                        outside.write_text("outside sentinel\n")
                    path = self.workspace / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.symlink_to(outside)
                    try:
                        result = self.run_hook()
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("file is a symlink", result.stderr)
                        self.assertTrue(path.is_symlink())
                        if not dangling:
                            self.assertEqual(
                                outside.read_text(), "outside sentinel\n"
                            )
                    finally:
                        self.clear_home()

    def test_conflicting_destination_objects_fail(self):
        for relative, directory in (
            ("beginner/containerization", False),
            ("beginner/containerization/auth_service/auth.py", True),
            ("tests/MODULE3_DELIVERY_RECEIPT.txt", True),
        ):
            with self.subTest(relative=relative):
                path = self.workspace / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if directory:
                    path.mkdir()
                else:
                    path.write_text("conflict sentinel\n")
                try:
                    result = self.run_hook()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("conflicting object", result.stderr)
                    self.assertTrue(path.exists())
                finally:
                    self.clear_home()

    def test_map_collisions_and_reserved_receipt_paths_fail(self):
        additions = (
            "beginner\tnew_key\tcontainerization\n",
            "beginner\tnew_key\tMODULE3_DELIVERY_RECEIPT.txt\n",
            "beginner\tnew_key\tMODULE3_DELIVERY_RECEIPT.txt/child\n",
        )
        for addition in additions:
            with self.subTest(addition=addition):
                self.write_maps(self.map_text + addition)
                (self.seed / "beginner/new_key").write_text("fixture\n")
                result = self.run_hook()
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, "collision|reserved receipt")
                self.assertFalse(self.home.exists())
        self.write_maps(self.map_text)

    def test_existing_content_and_permissions_are_untouched(self):
        directory = self.workspace / "beginner/containerization/auth_service"
        directory.mkdir(parents=True)
        directory.chmod(0o700)
        edited = directory / "auth.py"
        edited.write_text("participant edits\n")
        edited.chmod(0o600)
        receipt = self.workspace / "beginner/MODULE3_DELIVERY_RECEIPT.txt"
        receipt.write_text("original receipt\n")
        receipt.chmod(0o640)
        before = {
            str(path.relative_to(self.home)): (
                path.stat().st_mode,
                path.read_bytes() if path.is_file() else None,
            )
            for path in self.home.rglob("*")
        }
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = {
            str(path.relative_to(self.home)): (
                path.stat().st_mode,
                path.read_bytes() if path.is_file() else None,
            )
            for path in self.home.rglob("*")
        }
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
