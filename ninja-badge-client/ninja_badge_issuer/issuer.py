"""
Core batch issuance: participants in -> list of results out.

    from ninja_badge_issuer import issue_badges

    report = issue_badges(
        [{"name": "Ada Lovelace", "email": "ada@example.com", "status": "PASS"}],
        workshop_name="Advanced Cloud Architecture",
        workshop_date="2026-11-20",
    )
    for r in report.results:
        print(r.email, r.status, r.badge, r.badge_url, r.error)
"""
from __future__ import annotations

import csv
import io
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

from .api import (MIN_NAME_LENGTH, IssueBadgePayload, LiveNinjaBadgeClient,
                  MockNinjaBadgeClient, NinjaApiError, NinjaBadgeClient, links_for)
from .config import Config, load_config
from .rules import (PASS_BADGE, PARTICIPATION_BADGE, assessment_outcome, badge_for_outcome,
                    is_valid_email, is_valid_iso_date)

# Result statuses
ISSUED, FAILED, SKIPPED, INVALID = "issued", "failed", "skipped", "invalid"


@dataclass
class Participant:
    name: str
    email: str
    status: Optional[str] = None      # e.g. PASS / FAIL / NOT_TAKEN / "No Show"
    score: Optional[str] = None       # used when passing_score is set
    badge: Optional[str] = None       # explicit override: PASS | PARTICIPATION


@dataclass
class BadgeResult:
    name: str
    email: str
    assessment_outcome: str
    badge: str                        # PASS | PARTICIPATION
    template_id: str
    status: str                       # issued | failed | skipped | invalid
    award_id: str = ""                # BADGES.ninja award GUID
    badge_url: str = ""               # public page to share with the participant
    pdf_url: str = ""                 # PDF certificate
    assertion_url: str = ""           # Open Badge v2.0 JSON-LD (machine verification)
    issued_at: str = ""
    email_sent: str = ""              # "yes" | "no" | "" (not requested)
    error: str = ""
    attempts: int = 0
    dry_run: bool = False


@dataclass
class IssuanceReport:
    workshop_name: str
    workshop_date: str
    mode: str                         # live | mock
    results: list[BadgeResult] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        s = {"total": len(self.results), ISSUED: 0, FAILED: 0, SKIPPED: 0, INVALID: 0,
             "pass_badges": 0, "participation_badges": 0}
        for r in self.results:
            s[r.status] += 1
            if r.status == ISSUED:
                s["pass_badges" if r.badge == PASS_BADGE else "participation_badges"] += 1
        return s

    @property
    def ok(self) -> bool:
        return all(r.status in (ISSUED, SKIPPED) for r in self.results)

    def to_dict(self) -> dict:
        return {"workshop_name": self.workshop_name, "workshop_date": self.workshop_date,
                "mode": self.mode, "summary": self.summary,
                "results": [asdict(r) for r in self.results]}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_csv(self) -> str:
        buf = io.StringIO()
        fields = ["workshop_name", "workshop_date"] + list(BadgeResult.__dataclass_fields__)
        w = csv.DictWriter(buf, fieldnames=fields)
        w.writeheader()
        for r in self.results:
            w.writerow({"workshop_name": self.workshop_name, "workshop_date": self.workshop_date, **asdict(r)})
        return buf.getvalue()


# --------------------------------------------------------------------------
# Duplicate-issuance ledger (JSON file, live mode only)
# --------------------------------------------------------------------------

class Ledger:
    def __init__(self, path: Optional[Union[str, Path]]):
        self.path = Path(path).expanduser() if path else None
        self.data: dict = {}
        if self.path and self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.data = {}

    @staticmethod
    def key(workshop: str, date: str, email: str) -> str:
        return f"{workshop.strip().lower()}|{date}|{email.strip().lower()}"

    def get(self, workshop, date, email):
        return self.data.get(self.key(workshop, date, email))

    def record(self, workshop, date, email, entry: dict):
        if not self.path:
            return
        self.data[self.key(workshop, date, email)] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        tmp.replace(self.path)


# --------------------------------------------------------------------------
# Input helpers
# --------------------------------------------------------------------------

_ALIASES = {
    "name": "name", "fullname": "name", "participant": "name", "participantname": "name",
    "email": "email", "emailaddress": "email", "mail": "email",
    "assessmentstatus": "status", "status": "status", "result": "status", "outcome": "status",
    "score": "score", "grade": "score", "mark": "score", "points": "score",
    "badge": "badge", "badgeoverride": "badge",
}


def _canon(h: str) -> str:
    return "".join(ch for ch in h.lower() if ch.isalnum())


def to_participant(obj: Union[Participant, dict, tuple, list]) -> Participant:
    if isinstance(obj, Participant):
        return obj
    if isinstance(obj, (tuple, list)):
        vals = list(obj) + [None] * 3
        return Participant(name=str(vals[0] or ""), email=str(vals[1] or ""), status=vals[2])
    if isinstance(obj, dict):
        m = {}
        for k, v in obj.items():
            f = _ALIASES.get(_canon(str(k)))
            if f and f not in m:
                m[f] = None if v is None else str(v).strip()
        return Participant(name=m.get("name") or "", email=m.get("email") or "",
                           status=m.get("status"), score=m.get("score"),
                           badge=(m.get("badge") or "").upper() or None)
    raise TypeError(f"Unsupported participant type: {type(obj).__name__}")


def load_participants(path: Union[str, Path]) -> list[Participant]:
    """Load from .csv or .json (list of objects). Use '-' for JSON/CSV on stdin."""
    import sys
    if str(path) == "-":
        text = sys.stdin.read()
        is_json = text.lstrip().startswith(("[", "{"))
    else:
        p = Path(path)
        text = p.read_text(encoding="utf-8-sig")
        is_json = p.suffix.lower() == ".json"
    if is_json:
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("participants", [])
        return [to_participant(x) for x in data]
    rows = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [to_participant(r) for r in rows if any((v or "").strip() for v in r.values())]


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def _with_retries(fn, *, max_retries, backoff_s, min_interval_s, sleep, state):
    """Call fn() with rate limiting and retries on retryable NinjaApiError. Returns (value, attempts)."""
    for attempt in range(max_retries + 1):
        wait = min_interval_s - (time.monotonic() - state["last_start"])
        if wait > 0:
            sleep(wait)
        state["last_start"] = time.monotonic()
        try:
            return fn(), attempt + 1
        except NinjaApiError as e:
            if not e.retryable or attempt >= max_retries:
                e.attempts = attempt + 1  # type: ignore[attr-defined]
                raise
            sleep(e.retry_after_s if e.retry_after_s else backoff_s * 2 ** attempt)
    raise AssertionError("unreachable")


def issue_badges(
    participants: Iterable[Union[Participant, dict, tuple, list]],
    workshop_name: str,
    workshop_date: str,
    *,
    config: Optional[Config] = None,
    client: Optional[NinjaBadgeClient] = None,
    dry_run: bool = False,
    passing_score: Optional[float] = None,
    send_email: bool = False,
    expires: Optional[str] = None,
    ledger_path: Optional[Union[str, Path]] = "~/.ninja_badge_ledger.json",
    min_interval_s: float = 0.3,
    max_retries: int = 3,
    backoff_s: float = 1.0,
    on_progress: Optional[Callable[[int, int, BadgeResult], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> IssuanceReport:
    """
    Issue a PASS or PARTICIPATION badge to every participant and return, for
    each one, the public badge URL to share (badge_url), the PDF link and the
    award ID.

    Rules: PASS badge if the assessment was passed (status PASS, or score >=
    passing_score when given); otherwise PARTICIPATION. A participant 'badge'
    field overrides the rule.

    send_email=True also asks BADGES.ninja to email each participant their badge.

    Never raises for per-participant problems: each one gets a BadgeResult
    with status issued / failed / skipped / invalid. Raises ValueError only
    for bad batch-level input (workshop name/date, missing config for live).
    """
    if not (workshop_name or "").strip():
        raise ValueError("workshop_name is required")
    if not is_valid_iso_date(workshop_date):
        raise ValueError("workshop_date must be YYYY-MM-DD")
    if expires and not is_valid_iso_date(expires):
        raise ValueError("expires must be YYYY-MM-DD")

    cfg = config or load_config()
    if client is None:
        if dry_run:
            client = MockNinjaBadgeClient()
        else:
            missing = cfg.missing_for_live()
            if missing:
                raise ValueError(f"Missing configuration for live mode: {', '.join(missing)} "
                                 f"(set them in ninja_badge.ini or environment variables, or use dry_run=True)")
            client = LiveNinjaBadgeClient(cfg.api_key, cfg.base_url)

    is_mock = client.mode == "mock"
    pass_tid = cfg.pass_template_id or ("mock-pass-badge" if is_mock else "")
    part_tid = cfg.participation_template_id or ("mock-participation-badge" if is_mock else "")
    ledger = Ledger(None if is_mock else ledger_path)

    people = [to_participant(p) for p in participants]
    seen: dict[str, int] = {}
    for p in people:
        k = p.email.strip().lower()
        seen[k] = seen.get(k, 0) + 1

    report = IssuanceReport(workshop_name.strip(), workshop_date, client.mode)
    state = {"last_start": 0.0}
    retry = dict(max_retries=max_retries, backoff_s=backoff_s, min_interval_s=min_interval_s,
                 sleep=sleep, state=state)
    total = len(people)

    def done(i, res):
        report.results.append(res)
        if on_progress:
            on_progress(i, total, res)

    for idx, p in enumerate(people, 1):
        name, email = p.name.strip(), p.email.strip()
        outcome = assessment_outcome(p.status, p.score, passing_score)
        badge = p.badge if p.badge in (PASS_BADGE, PARTICIPATION_BADGE) else badge_for_outcome(outcome)
        tid = pass_tid if badge == PASS_BADGE else part_tid
        res = BadgeResult(name, email, outcome, badge, tid, status=INVALID, dry_run=is_mock)

        # --- validation
        if not name:
            res.error = "Name is required"
        elif len(name) < MIN_NAME_LENGTH:
            res.error = f"Name must be at least {MIN_NAME_LENGTH} characters (BADGES.ninja rule)"
        elif not is_valid_email(email):
            res.error = "Invalid email address"
        elif seen[email.lower()] > 1:
            res.error = "Duplicate email in this batch"
        if res.error:
            done(idx, res)
            continue

        # --- duplicate guard: already issued for this workshop/date -> return the stored link
        prev = ledger.get(workshop_name, workshop_date, email)
        if prev:
            res.status = SKIPPED
            res.award_id = prev.get("award_id", "")
            res.issued_at = prev.get("issued_at", "")
            if res.award_id:
                for k, v in links_for(res.award_id).items():
                    setattr(res, k, v)
            res.error = f"Already issued {prev.get('badge')} badge (ledger)"
            done(idx, res)
            continue

        payload = IssueBadgePayload(tid, name, email, workshop_date, expires)

        # --- issue
        try:
            r, res.attempts = _with_retries(lambda: client.issue_badge(payload), **retry)
        except NinjaApiError as e:
            res.status, res.error, res.attempts = FAILED, str(e), getattr(e, "attempts", 1)
            done(idx, res)
            continue
        except Exception as e:  # unexpected - record and move on
            res.status, res.error, res.attempts = FAILED, f"{type(e).__name__}: {e}", 1
            done(idx, res)
            continue

        res.status, res.issued_at = ISSUED, r.issued_at
        res.award_id, res.badge_url, res.pdf_url, res.assertion_url = r.award_id, r.badge_url, r.pdf_url, r.assertion_url
        ledger.record(workshop_name, workshop_date, email,
                      {"badge": badge, "award_id": r.award_id, "badge_url": r.badge_url, "issued_at": r.issued_at})

        # --- optional: let BADGES.ninja email the participant (failure doesn't undo the badge)
        if send_email:
            try:
                _with_retries(lambda: client.send_award_email(r.award_id, email), **retry)
                res.email_sent = "yes"
            except Exception as e:
                res.email_sent = "no"
                res.error = f"Badge issued, but email failed: {e}"

        done(idx, res)

    return report
