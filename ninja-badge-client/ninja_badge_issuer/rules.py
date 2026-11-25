"""Badge assignment rules (PRD section 3.4) and input validation."""
from __future__ import annotations

import re
from datetime import date
from typing import Optional, Union

PASS, FAIL, NOT_TAKEN = "PASS", "FAIL", "NOT_TAKEN"
PASS_BADGE, PARTICIPATION_BADGE = "PASS", "PARTICIPATION"

_PASS_WORDS = {"pass", "passed", "p", "yes", "y", "success", "successful", "completed", "true"}
_FAIL_WORDS = {"fail", "failed", "f", "no", "n", "unsuccessful", "false"}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def normalise_status(raw: Optional[str]) -> str:
    """'Passed' -> PASS, 'Failed' -> FAIL, anything else (incl. empty/'No Show') -> NOT_TAKEN."""
    s = (raw or "").strip().lower()
    if s in _PASS_WORDS:
        return PASS
    if s in _FAIL_WORDS:
        return FAIL
    return NOT_TAKEN


def parse_score(raw: Union[str, int, float, None]) -> Optional[float]:
    """Accepts 85, '85', '85%', '17/20', '69,5'. Returns None if absent/invalid."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = re.fullmatch(r"(-?\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)", s)
    if m:
        num, den = float(m[1].replace(",", ".")), float(m[2].replace(",", "."))
        return num / den * 100 if den > 0 else None
    try:
        return float(s.replace("%", "").replace(",", "."))
    except ValueError:
        return None


def assessment_outcome(status: Optional[str] = None, score=None,
                       passing_score: Optional[float] = None) -> str:
    """
    If passing_score is given, grade by score (missing score -> NOT_TAKEN);
    otherwise grade by status text.
    """
    if passing_score is not None:
        sc = parse_score(score)
        if sc is None:
            return NOT_TAKEN
        return PASS if sc >= passing_score else FAIL
    return normalise_status(status)


def badge_for_outcome(outcome: str) -> str:
    """PASS badge only for a passed assessment; FAIL / NOT_TAKEN -> PARTICIPATION."""
    return PASS_BADGE if outcome == PASS else PARTICIPATION_BADGE


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def is_valid_iso_date(s: str) -> bool:
    try:
        return date.fromisoformat(s).isoformat() == s
    except (TypeError, ValueError):
        return False
