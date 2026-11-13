#!/usr/bin/env python3
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import module3_endpoints as m

GOOD_AUTH = "10.42.1.1:5001"
GOOD_SHORT = "10.42.1.1:5000"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "state" / "digitafrica" / "module3-runtime" / "endpoints.tsv"

    def tearDown(self):
        self._tmp.cleanup()

    def lines(self):
        return self.path.read_text(encoding="utf-8").splitlines()

    def test_save_creates_header_and_private_permissions(self):
        m.save_record(self.path, m.make_record("inv-a", "group_01", "tier2-worker-1", GOOD_AUTH, GOOD_SHORT))
        self.assertEqual(self.lines()[0], "\t".join(m.HEADER))
        self.assertEqual(len(self.lines()), 2)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.path.parent).st_mode), 0o700)

    def test_update_same_identity_replaces_endpoints(self):
        rec = m.make_record("inv-a", "group_01", "tier2-worker-1", GOOD_AUTH, GOOD_SHORT)
        m.save_record(self.path, rec)
        m.save_record(self.path, m.make_record("inv-a", "group_01", "tier2-worker-1", "10.42.9.1:5001", "10.42.9.1:5000"))
        self.assertEqual(len(self.lines()), 2)
        self.assertIn("10.42.9.1:5001", self.lines()[1])

    def test_same_group_and_alias_in_separate_inventories_coexist(self):
        m.save_record(self.path, m.make_record("inv-a", "group_01", "w1", GOOD_AUTH, GOOD_SHORT))
        m.save_record(self.path, m.make_record("inv-b", "group_01", "w1", "10.42.2.1:5001", "10.42.2.1:5000"))
        self.assertEqual(len(m.read_store(self.path)), 2)
        removed = m.forget_records(self.path, [("inv-a", "group_01", "w1")])
        self.assertEqual(removed, 1)
        remaining = m.read_store(self.path)
        self.assertEqual(remaining, [("inv-b", "group_01", "w1", "10.42.2.1:5001", "10.42.2.1:5000")])

    def test_group_reassignment_replaces_conflicting_record(self):
        m.save_record(self.path, m.make_record("inv-a", "group_01", "w1", GOOD_AUTH, GOOD_SHORT))
        replaced = m.save_record(self.path, m.make_record("inv-a", "group_02", "w1", "10.42.2.1:5001", "10.42.2.1:5000"))
        self.assertEqual(len(replaced), 1)
        self.assertEqual([r[1] for r in m.read_store(self.path)], ["group_02"])

    def test_forget_exact_identity_preserves_unverified(self):
        m.save_record(self.path, m.make_record("inv-a", "group_01", "w1", GOOD_AUTH, GOOD_SHORT))
        m.save_record(self.path, m.make_record("inv-a", "group_02", "w2", "10.42.2.1:5001", "10.42.2.1:5000"))
        self.assertEqual(m.forget_records(self.path, [("inv-a", "group_01", "w1")]), 1)
        self.assertEqual([r[1] for r in m.read_store(self.path)], ["group_02"])

    def test_forget_wrong_inventory_removes_nothing(self):
        m.save_record(self.path, m.make_record("inv-a", "group_01", "w1", GOOD_AUTH, GOOD_SHORT))
        self.assertEqual(m.forget_records(self.path, [("inv-z", "group_01", "w1")]), 0)
        self.assertEqual(len(m.read_store(self.path)), 1)

    def test_forget_last_record_deletes_file(self):
        m.save_record(self.path, m.make_record("inv-a", "group_01", "w1", GOOD_AUTH, GOOD_SHORT))
        m.forget_records(self.path, [("inv-a", "group_01", "w1")])
        self.assertFalse(self.path.exists())

    def test_forget_on_missing_file_creates_nothing(self):
        self.assertEqual(m.forget_records(self.path, [("inv-a", "group_01", "w1")]), 0)
        self.assertFalse(self.path.exists())

    def test_invalid_inputs_are_rejected(self):
        bad_cases = [
            ("inv-a", "group_01", "w1", "10.42.1.1:5000", GOOD_SHORT),  # wrong auth port
            ("inv-a", "group_01", "w1", GOOD_AUTH, "10.42.1.1:5001"),  # wrong shortener port
            ("inv-a", "group_01", "w1", "10.42.1.256:5001", GOOD_SHORT),
            ("inv-a", "group_01", "w1", "0.0.0.0:5001", GOOD_SHORT),
            ("inv-a", "group_01", "w1", "10.42.1.1:5001\n", GOOD_SHORT),
            ("inv-a", "group_01", "w1\n", GOOD_AUTH, GOOD_SHORT),
            ("inv-a", "group_01", "w\t1", GOOD_AUTH, GOOD_SHORT),
            ("inv-a", "group_1", "w1", GOOD_AUTH, GOOD_SHORT),
            ("", "group_01", "w1", GOOD_AUTH, GOOD_SHORT),
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(m.StoreError):
                    m.make_record(*case)
        self.assertFalse(self.path.exists())

    def test_malformed_existing_file_is_rejected_and_untouched(self):
        self.path.parent.mkdir(parents=True)
        original = "\t".join(m.HEADER) + "\ninv-a\tgroup_01\tw1\t10.42.1.1:5001\n"  # 4 columns
        self.path.write_text(original, encoding="utf-8")
        with self.assertRaises(m.StoreError):
            m.save_record(self.path, m.make_record("inv-a", "group_02", "w2", GOOD_AUTH, GOOD_SHORT))
        with self.assertRaises(m.StoreError):
            m.forget_records(self.path, [("inv-a", "group_01", "w1")])
        self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    def test_duplicate_records_in_file_are_rejected(self):
        self.path.parent.mkdir(parents=True)
        row = "inv-a\tgroup_01\tw1\t10.42.1.1:5001\t10.42.1.1:5000\n"
        self.path.write_text("\t".join(m.HEADER) + "\n" + row + row, encoding="utf-8")
        with self.assertRaises(m.StoreError):
            m.read_store(self.path)

    def test_failed_replace_keeps_old_file_and_leaves_no_temp(self):
        m.save_record(self.path, m.make_record("inv-a", "group_01", "w1", GOOD_AUTH, GOOD_SHORT))
        before = self.path.read_text(encoding="utf-8")
        with mock.patch("module3_endpoints.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                m.save_record(self.path, m.make_record("inv-a", "group_02", "w2", "10.42.2.1:5001", "10.42.2.1:5000"))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        leftovers = [p for p in self.path.parent.iterdir() if p.name.startswith(".endpoints.")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
