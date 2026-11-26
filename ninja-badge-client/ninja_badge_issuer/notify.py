"""Send BADGES.ninja notification emails for credentials that are already issued.

Works from a reviewed report CSV (the file written with ``-o report.csv``).
Only rows with status=issued and email_sent empty/"no" are emailed; the report is
rewritten atomically after every email, so reruns never double-send.
"""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

REQUIRED = ("status", "award_id", "email")
PENDING = ("", "no")                      # "yes" = done, "unknown" = needs manual check
ERR_PREFIXES = ("Email failed:", "Badge issued, but email failed")


def _read(path: str):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    missing = [c for c in REQUIRED if c not in fields]
    if missing:
        raise ValueError(f"{path}: not a badge report CSV (missing column(s): {', '.join(missing)})")
    for col in ("email_sent", "error", "email_sent_at"):
        if col not in fields:
            fields.append(col)
    return fields, rows


def _write(path: str, fields: list, rows: list) -> None:
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, p)


def _is_pending(row: dict) -> bool:
    return (
        (row.get("status") or "").strip() == "issued"
        and bool((row.get("award_id") or "").strip())
        and bool((row.get("email") or "").strip())
        and (row.get("dry_run") or "").strip().lower() != "true"
        and (row.get("email_sent") or "").strip().lower() in PENDING
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def send_from_report(
    report_path: str,
    client,
    *,
    skip: Iterable[str] = (),
    dry_run: bool = False,
    min_interval_s: float = 0.3,
    max_attempts: int = 3,
    confirm: Optional[Callable[[int], bool]] = None,
    on_progress: Optional[Callable[[int, int, dict, str], None]] = None,
) -> dict:
    """Email every pending recipient in the report. Returns a summary dict."""
    fields, rows = _read(report_path)
    skip_set = {s.strip().lower() for s in skip}
    pending = [r for r in rows if _is_pending(r) and r["email"].strip().lower() not in skip_set]
    summary = {
        "selected": len(pending), "sent": 0, "failed": 0, "unknown": 0,
        "already_sent": sum(1 for r in rows if (r.get("email_sent") or "").strip().lower() == "yes"),
        "skipped_by_user": sum(1 for r in rows if _is_pending(r) and r["email"].strip().lower() in skip_set),
        "aborted": False, "dry_run": dry_run,
    }
    total = len(pending)

    if dry_run:
        for i, r in enumerate(pending, 1):
            if on_progress:
                on_progress(i, total, r, "would-send")
        return summary

    if total and confirm and not confirm(total):
        summary["aborted"] = True
        return summary

    for i, row in enumerate(pending, 1):
        outcome = "failed"
        err = ""
        for attempt in range(1, max_attempts + 1):
            try:
                client.send_award_email(row["award_id"].strip(), row["email"].strip())
                outcome = "sent"
                break
            except Exception as e:  # NinjaApiError or unexpected
                err = str(e)
                if getattr(e, "maybe_issued", False):          # timeout: may have been sent
                    outcome = "unknown"
                    break
                if getattr(e, "retryable", False) and attempt < max_attempts:
                    time.sleep(getattr(e, "retry_after_s", None) or 2 ** attempt)
                    continue
                break

        if outcome == "sent":
            row["email_sent"], row["email_sent_at"] = "yes", _now()
            if (row.get("error") or "").startswith(ERR_PREFIXES):
                row["error"] = ""
            summary["sent"] += 1
        elif outcome == "unknown":
            row["email_sent"] = "unknown"
            row["error"] = f"Email failed: {err}"
            summary["unknown"] += 1
        else:
            row["email_sent"] = "no"
            row["error"] = f"Email failed: {err}"
            summary["failed"] += 1

        _write(report_path, fields, rows)                       # save progress after every email
        if on_progress:
            on_progress(i, total, row, outcome)
        if i < total:
            time.sleep(min_interval_s)

    return summary
