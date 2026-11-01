"""Disposable-file and fake-command tests; no production files or Docker."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

old_path = list(sys.path)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                         "scripts/workshops/big-data/spark"))
    import livy_candidate_compose as adapter
finally:
    sys.path[:] = old_path


class ComposeNormalizationTests(unittest.TestCase):
    def test_normalization_uses_stdin_fixed_root_and_both_profiles(self):
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout='{"name":"digitafrica-spark"}')
        text = b"name: digitafrica-spark\nservices: {}\n"
        self.assertEqual(adapter.compose_config(text, run=run),
                         {"name": "digitafrica-spark"})
        argv, kwargs = calls[0]
        self.assertEqual(argv, [
            "docker", "compose", "--project-name", "digitafrica-spark",
            "--project-directory", adapter.ROOT,
            "--env-file", "/dev/null",
            "--profile", "participant-direct",
            "--profile", "participant-livy",
            "--file", "-", "config", "--format", "json"])
        self.assertEqual(kwargs["input"], text.decode())
        self.assertEqual(kwargs["timeout"], 30)
        self.assertFalse(kwargs["check"])

    def test_command_failure_and_invalid_configuration_are_refused(self):
        for code, output in ((1, ""), (0, "[]"), (0, "not-json")):
            with self.subTest(code=code, output=output), self.assertRaises(ValueError):
                adapter.compose_config(b"trusted", run=lambda *a, **k:
                    SimpleNamespace(returncode=code, stdout=output))

    def test_empty_or_oversized_input_is_refused_before_command(self):
        def forbidden(*args, **kwargs):
            self.fail("Command executed for invalid input")
        for text in (b"", b"x" * (adapter.MAX_COMPOSE_BYTES + 1)):
            with self.subTest(size=len(text)), self.assertRaises(ValueError):
                adapter.compose_config(text, run=forbidden)


class ProtectedBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)
        self.path = self.root / "compose.yaml"
        self.path.write_bytes(b"existing reviewed compose")
        self.path.chmod(0o640)

    def read(self):
        return adapter.read_baseline(self.fd, owner_uid=os.getuid())

    def test_read_preserves_content_and_inode(self):
        inode = self.path.stat().st_ino
        self.assertEqual(self.read(), b"existing reviewed compose")
        self.assertEqual(self.path.stat().st_ino, inode)

    def test_missing_baseline_is_not_created(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.read()
        self.assertFalse(self.path.exists())

    def test_symlink_is_refused_without_following_target(self):
        target = self.root / "outside"
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.read()
        self.assertEqual(target.read_bytes(), b"existing reviewed compose")

    def test_hardlink_is_refused(self):
        os.link(self.path, self.root / "held")
        with self.assertRaises(ValueError):
            self.read()

    def test_wrong_permissions_are_refused(self):
        self.path.chmod(0o666)
        with self.assertRaises(ValueError):
            self.read()


if __name__ == "__main__":
    unittest.main()
