"""Mocked evidence-directory tests; no production filesystem access."""
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_spark_teardown_evidence import evidence

sys.modules["teardown_evidence"] = evidence
path = Path(__file__).resolve().parents[1] / (
    "scripts/workshops/big-data/spark/teardown_directory.py"
)
spec = importlib.util.spec_from_file_location("teardown_directory", path)
directory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directory)


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.mocks = {}
        for name in ("open", "mkdir", "fsync", "close", "geteuid", "fstat"):
            self.mocks[name] = stack.enter_context(
                patch.object(directory.os, name)
            )
        self.mocks["geteuid"].return_value = 0
        self.mocks["open"].side_effect = [10, 11, 12, 13]
        self.mocks["fstat"].side_effect = [
            SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
            for _ in range(3)
        ] + [
            SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=0)
        ]
        self.lock = stack.enter_context(
            patch.object(directory.fcntl, "flock")
        )

    def closed(self):
        return [call.args[0] for call in self.mocks["close"].call_args_list]

    def test_secure_creation_lock_and_reverse_cleanup(self):
        with directory.locked_evidence_directory() as fd:
            self.assertEqual(fd, 13)
            self.mocks["close"].assert_not_called()
        self.assertEqual(self.closed(), [13, 12, 11, 10])
        self.mocks["mkdir"].assert_called_once_with(
            directory.NAME, mode=0o700, dir_fd=12
        )
        self.mocks["fsync"].assert_called_once_with(12)
        self.lock.assert_called_once_with(
            13, directory.fcntl.LOCK_EX | directory.fcntl.LOCK_NB
        )
        calls = self.mocks["open"].call_args_list
        self.assertEqual([call.args[0] for call in calls],
                         ["/", "var", "lib", directory.NAME])
        for call in calls:
            self.assertEqual(call.args[1], directory.FLAGS)
            self.assertTrue(call.args[1] & directory.os.O_NOFOLLOW)

    def test_non_root_is_rejected_before_open(self):
        self.mocks["geteuid"].return_value = 1000
        with self.assertRaises(PermissionError):
            with directory.locked_evidence_directory():
                self.fail("Unexpected entry")
        self.mocks["open"].assert_not_called()

    def test_existing_directory_is_validated_without_chmod(self):
        self.mocks["mkdir"].side_effect = FileExistsError()
        with directory.locked_evidence_directory():
            pass
        self.mocks["fsync"].assert_not_called()
        self.assertEqual(self.closed(), [13, 12, 11, 10])

    def test_unsafe_ancestor_is_rejected(self):
        for uid, mode in ((1000, 0o755), (0, 0o777)):
            with self.subTest(uid=uid, mode=mode):
                self.mocks["open"].side_effect = [10]
                self.mocks["fstat"].side_effect = [
                    SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=uid)
                ]
                self.mocks["close"].reset_mock()
                with self.assertRaisesRegex(ValueError, "ancestor"):
                    with directory.locked_evidence_directory():
                        self.fail("Unexpected entry")
                self.assertEqual(self.closed(), [10])
        self.lock.assert_not_called()

    def test_symlink_open_failure_closes_ancestors(self):
        self.mocks["open"].side_effect = [
            10, 11, 12, OSError("simulated O_NOFOLLOW rejection")
        ]
        with self.assertRaises(OSError):
            with directory.locked_evidence_directory():
                self.fail("Unexpected entry")
        self.assertEqual(self.closed(), [12, 11, 10])
        self.lock.assert_not_called()

    def test_unsafe_evidence_directory_is_rejected_before_lock(self):
        self.mocks["fstat"].side_effect = [
            SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
            for _ in range(4)
        ]
        with self.assertRaisesRegex(ValueError, "0700"):
            with directory.locked_evidence_directory():
                self.fail("Unexpected entry")
        self.assertEqual(self.closed(), [13, 12, 11, 10])
        self.lock.assert_not_called()

    def test_lock_contention_closes_all_descriptors(self):
        self.lock.side_effect = BlockingIOError()
        with self.assertRaisesRegex(RuntimeError, "holds the evidence lock"):
            with directory.locked_evidence_directory():
                self.fail("Unexpected entry")
        self.assertEqual(self.closed(), [13, 12, 11, 10])

    def test_caller_failure_closes_all_descriptors(self):
        with self.assertRaisesRegex(RuntimeError, "caller failure"):
            with directory.locked_evidence_directory():
                raise RuntimeError("caller failure")
        self.assertEqual(self.closed(), [13, 12, 11, 10])


if __name__ == "__main__":
    unittest.main(verbosity=2)
