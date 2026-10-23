"""Essential local Module 3 delivery tests; ownership calls are stubbed."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined
import test_cloud_module3_preflight as fixtures

ROOT = fixtures.ROOT


class Module3DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.Module3PreflightTests(
            methodName="test_real_map_and_sources_pass_for_valid_selections"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.home = self.fixture.home
        self.workspace = self.home / "Cloud-Computing-SOA/Module-3"
        environment = Environment(
            loader=FileSystemLoader(str(ROOT / "roles/k8s_apps/templates")),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )
        script = self.fixture.script
        for name in (
            "cloud-module3-destination-preflight.sh.j2",
            "cloud-module3-seeding.sh.j2",
        ):
            script += "\n" + environment.get_template(
                "workshop-hooks/" + name
            ).render().format(**{})
        self.script = script.replace("/home/jovyan", str(self.home))

        self.bin = self.fixture.root / "bin"
        self.bin.mkdir()
        self.ownership_log = self.fixture.root / "ownership.log"
        stub = self.bin / "chown"
        stub.write_text(
            '#!/bin/sh\n'
            '[ "$#" -eq 2 ] && [ "$1" = "1000:100" ] || exit 1\n'
            'printf "%s\\n" "$2" >> "$MODULE3_OWNERSHIP_LOG"\n'
        )
        stub.chmod(0o755)

    def run_delivery(self, mode="beginner", released="false"):
        settings = {
            "workshop_type": "cloud-computing-soa",
            "workshop_module": "module3",
            "mode": mode,
            "solutions_released": released,
        }
        assignments = "\n".join(
            name + "=" + shlex.quote(value)
            for name, value in settings.items()
        )
        environment = dict(os.environ)
        environment["PATH"] = str(self.bin) + os.pathsep + environment["PATH"]
        environment["MODULE3_OWNERSHIP_LOG"] = str(self.ownership_log)
        return subprocess.run(
            ["sh", "-c", "set -eu\n" + assignments + "\n" + self.script],
            cwd=self.fixture.root, env=environment,
            capture_output=True, text=True, timeout=30,
        )

    def assert_delivery(self, selected):
        expected = set()
        for track, key, relative in self.fixture.rows:
            if track not in selected:
                continue
            path = self.workspace / track / relative
            expected.add(f"{track}/{relative}")
            self.assertEqual(
                path.read_bytes(),
                (self.fixture.seed / track / key).read_bytes(),
            )
            self.assertEqual(
                path.stat().st_mode & 0o777,
                0o755 if relative.endswith(".sh") else 0o644,
            )
            self.assertFalse(path.is_symlink())
        for track in selected:
            receipt = self.workspace / track / "MODULE3_DELIVERY_RECEIPT.txt"
            expected.add(f"{track}/MODULE3_DELIVERY_RECEIPT.txt")
            self.assertIn("runtime_readiness=NOT VALIDATED", receipt.read_text())
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o644)
        actual = {
            path.relative_to(self.workspace).as_posix()
            for path in self.workspace.rglob("*") if path.is_file()
        }
        self.assertEqual(actual, expected)
        self.assertTrue(self.ownership_log.read_text().strip())

    def test_fresh_beginner_exact_allowlist_and_permissions(self):
        result = self.run_delivery()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_delivery({"beginner", "tests"})

    def test_intermediate_and_advanced_then_explicit_solution_release(self):
        for mode in ("intermediate", "advanced"):
            with self.subTest(mode=mode):
                # Start each track from an empty home.
                shutil.rmtree(self.home, ignore_errors=True)
                self.ownership_log.unlink(missing_ok=True)
                result = self.run_delivery(mode=mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_delivery({mode, "tests"})
                result = self.run_delivery(mode=mode, released="true")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_delivery({mode, "tests", "solutions"})

    def test_repeat_preserves_edits_permissions_receipts_and_local_files(self):
        result = self.run_delivery()
        self.assertEqual(result.returncode, 0, result.stderr)
        edited = self.workspace / "beginner/containerization/auth_service/auth.py"
        edited.write_text("participant edits\n")
        edited.chmod(0o600)
        edited.parent.chmod(0o700)
        local = self.workspace / "beginner/local-config.txt"
        local.write_text("local settings\n")
        before = {
            p.relative_to(self.home).as_posix(): (
                p.stat().st_mode, p.stat().st_uid, p.stat().st_gid,
                p.read_bytes() if p.is_file() else None,
            )
            for p in self.home.rglob("*")
        }
        ownership_before = self.ownership_log.read_bytes()
        result = self.run_delivery()
        self.assertEqual(result.returncode, 0, result.stderr)
        after = {
            p.relative_to(self.home).as_posix(): (
                p.stat().st_mode, p.stat().st_uid, p.stat().st_gid,
                p.read_bytes() if p.is_file() else None,
            )
            for p in self.home.rglob("*")
        }
        self.assertEqual(after, before)
        self.assertEqual(self.ownership_log.read_bytes(), ownership_before)

    def test_missing_source_fails_before_home_creation(self):
        track, key, relative = next(
            row for row in self.fixture.rows if row[0] == "beginner"
        )
        (self.fixture.seed / track / key).unlink()
        result = self.run_delivery()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing Module 3 source", result.stderr)
        self.assertFalse(self.home.exists())

    def test_destination_symlink_fails_before_delivery(self):
        outside = self.fixture.root / "outside"
        outside.mkdir()
        target = self.workspace / "beginner"
        target.parent.mkdir(parents=True)
        target.symlink_to(outside, target_is_directory=True)
        result = self.run_delivery()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(self.ownership_log.exists())

    def test_integration_order(self):
        text = (ROOT / "roles/k8s_apps/templates/jhub-values.yaml.j2").read_text()
        names = (
            "cloud-module3-validation.sh.j2",
            "cloud-module3-preflight.sh.j2",
            "cloud-module3-destination-preflight.sh.j2",
            'mkdir -p "$workspace"',
            "cloud-module3-seeding.sh.j2",
        )
        positions = []
        for name in names:
            self.assertEqual(text.count(name), 1, name)
            positions.append(text.index(name))
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main()
