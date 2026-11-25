import pytest
from ninja_badge_issuer.rules import (assessment_outcome, badge_for_outcome, is_valid_email,
                                      is_valid_iso_date, normalise_status, parse_score)


@pytest.mark.parametrize("raw,out", [("PASS", "PASS"), ("passed", "PASS"), (" Yes ", "PASS"),
                                     ("FAIL", "FAIL"), ("Failed", "FAIL"), ("No Show", "NOT_TAKEN"),
                                     ("", "NOT_TAKEN"), (None, "NOT_TAKEN")])
def test_normalise(raw, out):
    assert normalise_status(raw) == out


def test_scores():
    assert parse_score("85%") == 85 and parse_score("17/20") == 85 and parse_score("69,5") == 69.5
    assert parse_score("") is None and parse_score("x") is None
    assert assessment_outcome(score="70", passing_score=70) == "PASS"
    assert assessment_outcome(score="69.9", passing_score=70) == "FAIL"
    assert assessment_outcome(status="PASS", score="", passing_score=70) == "NOT_TAKEN"


def test_badge_rule():
    assert badge_for_outcome("PASS") == "PASS"
    assert badge_for_outcome("FAIL") == badge_for_outcome("NOT_TAKEN") == "PARTICIPATION"


def test_validators():
    assert is_valid_email("a@b.co") and not is_valid_email("a@b") and not is_valid_email("a b@c.de")
    assert is_valid_iso_date("2026-11-20") and not is_valid_iso_date("2026-02-30")
