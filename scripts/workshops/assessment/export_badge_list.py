#!/usr/bin/env python3
"""Export a reviewed grading summary as a participant list for ninja-badge-client.

Run this only after the organiser has verified every grade. It reads the
private summary.csv written by grade_exam.py and writes a CSV with the columns
the badge client expects: name, email, status. It never calls the badge API.

Refuses to write anything while any selected row is unresolved (PENDING REVIEW
or incomplete), lacks an explicit participant name or email, or shares an
email address with another row.
"""
import argparse
import csv
import os
import sys
from pathlib import Path

OUTCOME_TO_STATUS = {"PASS": "PASS", "NO PASS": "FAIL"}
REQUIRED_COLUMNS = ("participant", "participant_name", "participant_email",
                    "assessment_stem", "status", "outcome")
FIELDS = ["name", "email", "status"]


class ExportError(Exception):
    pass


def build_rows(summary_rows, stem=None):
    """Return client rows, or raise ExportError listing every problem found."""
    unresolved, missing_name, missing_email, rows = [], [], [], []
    owners = {}
    duplicates = []
    selected = 0

    for row in summary_rows:
        if stem is not None and (row.get("assessment_stem") or "") != stem:
            continue
        selected += 1
        label = (row.get("participant") or "(unknown)").strip() or "(unknown)"
        outcome = (row.get("outcome") or "").strip()
        state = (row.get("status") or "").strip()
        if outcome not in OUTCOME_TO_STATUS or state != "COMPLETE":
            unresolved.append(label)
            continue
        name = (row.get("participant_name") or "").strip()
        email = (row.get("participant_email") or "").strip()
        if not name:
            missing_name.append(label)
            continue
        if not email:
            missing_email.append(label)
            continue
        key = email.lower()
        if key in owners:
            duplicates.append(label)
            continue
        owners[key] = label
        rows.append({"name": name, "email": email,
                     "status": OUTCOME_TO_STATUS[outcome]})

    problems = []
    if selected == 0:
        problems.append("No summary rows selected (check --stem).")
    if unresolved:
        problems.append("Unresolved outcome (PENDING REVIEW or incomplete): "
                        + ", ".join(unresolved))
    if missing_name:
        problems.append("No explicit participant name: " + ", ".join(missing_name))
    if missing_email:
        problems.append("No participant email: " + ", ".join(missing_email))
    if duplicates:
        problems.append("Duplicate email address: " + ", ".join(duplicates))
    if problems:
        raise ExportError("\n".join(problems))
    return rows


def read_summary(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ExportError("summary.csv lacks required column(s): " + ", ".join(missing))
        return list(reader)


def write_private_csv(path, rows):
    path = Path(path)
    if path.exists():
        raise ExportError("Output already exists; refusing to overwrite: %s" % path)
    if not path.parent.is_dir():
        raise ExportError("Output directory does not exist: %s" % path.parent)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, help="reviewed summary.csv from grade_exam.py")
    parser.add_argument("--out", required=True, help="new private badge list CSV to create")
    parser.add_argument("--stem", help="only export this assessment_stem")
    parser.add_argument("--confirm-reviewed", action="store_true",
                        help="confirm that the organiser has verified every grade")
    args = parser.parse_args()

    if not args.confirm_reviewed:
        parser.error("--confirm-reviewed is required: export only after all grades are verified.")
    try:
        rows = build_rows(read_summary(args.summary), args.stem)
        write_private_csv(args.out, rows)
    except (ExportError, OSError, csv.Error) as exc:
        print("error: " + str(exc), file=sys.stderr)
        return 2

    passes = sum(r["status"] == "PASS" for r in rows)
    print("Badge list rows: %d (PASS: %d; FAIL: %d)" % (len(rows), passes, len(rows) - passes))
    print("Private badge list written to: %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
