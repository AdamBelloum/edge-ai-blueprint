"""Mocked shared submission-lock tests; no production filesystem access."""
from contextlib import ExitStack
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_spark_teardown_directory import directory


class SubmissionLockTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.mocks = {}
        for name in ("open", "close", "geteuid", "fstat"):
            self.mocks[name] = stack.enter_context(patch.object(directory.os, name))
        self.mocks["geteuid"].return_value = 0
        self.mocks["open"].side_effect = list(range(10, 17))
        self.stats = [SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
                      for _ in range(6)] + [
            SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1)
        ]
        self.mocks["fstat"].side_effect = self.stats
        self.lock = stack.enter_context(patch.object(directory.fcntl, "flock"))

    def closed(self):
        return [call.args[0] for call in self.mocks["close"].call_args_list]

    def test_uses_exact_runner_lock_without_unlinking_or_replacing(self):
        with directory.locked_submission_runtime() as fd:
            self.assertEqual(fd, 16)
            self.mocks["close"].assert_not_called()
        self.assertEqual(self.closed(), list(range(16, 9, -1)))
        calls = self.mocks["open"].call_args_list
        self.assertEqual([call.args[0] for call in calls],
                         ["/", *directory.SUBMISSION_COMPONENTS, ".direct-run.lock"])
        last = calls[-1]
        self.assertEqual(last.kwargs, {"dir_fd": 15})
        self.assertEqual(last.args[2], 0o600)
        self.assertTrue(last.args[1] & directory.os.O_NOFOLLOW)
        self.assertFalse(last.args[1] & directory.os.O_TRUNC)
        self.lock.assert_called_once_with(
            16, directory.fcntl.LOCK_EX | directory.fcntl.LOCK_NB)

    def test_active_submission_is_refused_and_descriptors_close(self):
        self.lock.side_effect = BlockingIOError()
        with self.assertRaisesRegex(RuntimeError, "submission holds"):
            with directory.locked_submission_runtime():
                self.fail("Unexpected entry")
        self.assertEqual(self.closed(), list(range(16, 9, -1)))

    def test_non_root_is_refused_before_open(self):
        self.mocks["geteuid"].return_value = 1000
        with self.assertRaises(PermissionError):
            with directory.locked_submission_runtime():
                self.fail("Unexpected entry")
        self.mocks["open"].assert_not_called()

    def test_missing_runtime_is_not_created(self):
        self.mocks["open"].side_effect = [10, FileNotFoundError()]
        with directory.locked_submission_runtime() as fd:
            self.assertIsNone(fd)
        self.assertEqual(self.closed(), [10])
        self.lock.assert_not_called()

    def test_symlink_open_failure_is_not_treated_as_missing(self):
        self.mocks["open"].side_effect = [10, OSError("symlink refused")]
        with self.assertRaisesRegex(OSError, "symlink refused"):
            with directory.locked_submission_runtime():
                self.fail("Unexpected entry")
        self.assertEqual(self.closed(), [10])
        self.lock.assert_not_called()

    def test_unsafe_ancestor_prevents_lock(self):
        self.mocks["fstat"].side_effect = [
            SimpleNamespace(st_mode=stat.S_IFDIR | 0o777, st_uid=0)]
        with self.assertRaisesRegex(ValueError, "ancestor"):
            with directory.locked_submission_runtime():
                self.fail("Unexpected entry")
        self.assertEqual(self.closed(), [10])
        self.lock.assert_not_called()

    def test_unsafe_lock_file_prevents_flock(self):
        for info in (
            SimpleNamespace(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_nlink=1),
            SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=1000, st_nlink=1),
            SimpleNamespace(st_mode=stat.S_IFDIR | 0o600, st_uid=0, st_nlink=1),
            SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=2),
        ):
            with self.subTest(info=info):
                self.mocks["open"].side_effect = list(range(10, 17))
                self.mocks["fstat"].side_effect = self.stats[:6] + [info]
                self.mocks["close"].reset_mock()
                with self.assertRaisesRegex(ValueError, "submission lock"):
                    with directory.locked_submission_runtime():
                        self.fail("Unexpected entry")
                self.assertEqual(self.closed(), list(range(16, 9, -1)))
        self.lock.assert_not_called()

    def test_caller_failure_releases_descriptors(self):
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            with directory.locked_submission_runtime():
                raise RuntimeError("cleanup failed")
        self.assertEqual(self.closed(), list(range(16, 9, -1)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
