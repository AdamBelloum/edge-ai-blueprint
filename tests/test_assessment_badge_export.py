"""Reviewed grading summaries export to the badge client's input format.

Static, offline checks: no badge API call, no cluster, no real participants.
"""
import csv
import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ASSESSMENT_DIR = ROOT / "scripts" / "workshops" / "assessment"


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ASSESSMENT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export = load("export_badge_list_under_test", "export_badge_list.py")
grader = load("grade_exam_under_test", "grade_exam.py")


def row(participant="group_01", name="Test Person", email="test.person@example.org",
        stem="exam_a", state="COMPLETE", outcome="PASS"):
    return {
        "participant": participant, "participant_name": name,
        "participant_email": email, "assessment_stem": stem,
        "status": state, "outcome": outcome,
    }


class ParticipantNameTests(unittest.TestCase):
    def test_explicit_name_is_returned(self):
        self.assertEqual("Ada Test", grader.safe_participant_name({"participant": " Ada Test "}))

    def test_slug_fallback_is_not_a_name(self):
        state = {"participant_slug": "group_01"}
        self.assertEqual("", grader.safe_participant_name(state))
        self.assertEqual("group_01", grader.safe_identity(state, "fallback"))

    def test_missing_or_invalid_state_gives_empty_name(self):
        self.assertEqual("", grader.safe_participant_name(None))
        self.assertEqual("", grader.safe_participant_name({"participant": 7}))


class BuildRowsTests(unittest.TestCase):
    def test_outcomes_map_to_client_status(self):
        rows = export.build_rows([
            row(email="a@example.org", outcome="PASS"),
            row(participant="g2", name="Bo Test", email="b@example.org", outcome="NO PASS"),
        ])
        self.assertEqual(["PASS", "FAIL"], [r["status"] for r in rows])
        self.assertEqual(["name", "email", "status"], list(rows[0]))

    def test_pending_review_blocks_whole_export(self):
        with self.assertRaises(export.ExportError) as ctx:
            export.build_rows([row(), row(participant="g2", email="b@example.org",
                                          state="INCOMPLETE", outcome="PENDING REVIEW")])
        self.assertIn("g2", str(ctx.exception))

    def test_missing_explicit_name_is_refused(self):
        with self.assertRaises(export.ExportError) as ctx:
            export.build_rows([row(participant="group_03", name="")])
        self.assertIn("group_03", str(ctx.exception))

    def test_missing_email_is_refused(self):
        with self.assertRaises(export.ExportError):
            export.build_rows([row(email="")])

    def test_duplicate_email_is_refused_case_insensitively(self):
        with self.assertRaises(export.ExportError):
            export.build_rows([row(email="A@example.org"),
                               row(participant="g2", name="Bo Test", email="a@EXAMPLE.org")])

    def test_stem_filter_selects_one_assessment(self):
        rows = export.build_rows([
            row(email="a@example.org", stem="exam_a"),
            row(email="a@example.org", stem="exam_b", outcome="NO PASS"),
        ], stem="exam_b")
        self.assertEqual(["FAIL"], [r["status"] for r in rows])

    def test_empty_selection_is_refused(self):
        with self.assertRaises(export.ExportError):
            export.build_rows([row()], stem="other")


class WriteAndMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.summary = self.dir / "summary.csv"
        with open(self.summary, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row()))
            writer.writeheader()
            writer.writerow(row())

    def run_main(self, *extra):
        out = self.dir / "badge_participants.csv"
        argv = ["export_badge_list.py", "--summary", str(self.summary),
                "--out", str(out), *extra]
        with mock.patch.object(sys, "argv", argv):
            return export.main(), out

    def test_export_writes_private_client_csv(self):
        code, out = self.run_main("--confirm-reviewed")
        self.assertEqual(0, code)
        self.assertEqual(0o600, stat.S_IMODE(out.stat().st_mode))
        with open(out, newline="", encoding="utf-8") as handle:
            self.assertEqual(
                [{"name": "Test Person", "email": "test.person@example.org", "status": "PASS"}],
                list(csv.DictReader(handle)))

    def test_confirmation_flag_is_required(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_main()
        self.assertEqual(2, ctx.exception.code)
        self.assertFalse((self.dir / "badge_participants.csv").exists())

    def test_existing_output_is_not_overwritten(self):
        existing = self.dir / "badge_participants.csv"
        existing.write_text("keep", encoding="utf-8")
        code, _ = self.run_main("--confirm-reviewed")
        self.assertEqual(2, code)
        self.assertEqual("keep", existing.read_text(encoding="utf-8"))

    def test_summary_without_required_columns_is_refused(self):
        self.summary.write_text("participant,outcome\ng1,PASS\n", encoding="utf-8")
        code, out = self.run_main("--confirm-reviewed")
        self.assertEqual(2, code)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
