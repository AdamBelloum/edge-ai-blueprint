import json
import pytest
from ninja_badge_issuer import Config, MockNinjaBadgeClient, issue_badges
from ninja_badge_issuer.cli import main

NOSLEEP = dict(sleep=lambda s: None, min_interval_s=0)


def test_dry_run_assigns_badges_links_and_handles_errors():
    people = [
        {"Name": "Ada Lovelace", "E-mail": "ada@x.com", "Assessment Status": "Passed"},
        {"name": "Alan Turing", "email": "alan+flaky@x.com", "status": "FAIL"},
        {"name": "Grace Hopper", "email": "grace+fail@x.com"},
        {"name": "", "email": "bad"},
        ("Dup One", "d@x.com"), ("Dup Two", "D@x.com"),
        {"name": "Ana", "email": "ana@x.com"},                                     # < 5 chars
        {"name": "Edsger Dijkstra", "email": "e@x.com", "status": "FAIL", "badge": "PASS"},  # override
    ]
    rep = issue_badges(people, "WS", "2026-11-20", dry_run=True, config=Config(), **NOSLEEP)
    r = rep.results
    assert (r[0].status, r[0].badge) == ("issued", "PASS")
    assert r[0].badge_url == f"https://badges.ninja/awards/{r[0].award_id}"
    assert r[0].pdf_url.endswith(f"/certify-badge/award/{r[0].award_id}/pdf")
    assert (r[1].status, r[1].badge, r[1].attempts) == ("issued", "PARTICIPATION", 2)
    assert r[2].status == "failed" and r[2].badge_url == ""
    assert [x.status for x in r[3:7]] == ["invalid"] * 4
    assert "5 characters" in r[6].error
    assert (r[7].status, r[7].badge) == ("issued", "PASS")
    assert rep.mode == "mock" and not rep.ok and rep.summary["issued"] == 3


def test_send_email():
    mock = MockNinjaBadgeClient()
    rep = issue_badges([("Ada Lovelace", "ada@x.com", "PASS")], "WS", "2026-11-20",
                       client=mock, config=Config(), send_email=True, **NOSLEEP)
    assert rep.results[0].email_sent == "yes"
    assert mock.sent_emails == [(rep.results[0].award_id, "ada@x.com")]


def test_live_requires_config():
    with pytest.raises(ValueError, match="api_key"):
        issue_badges([("Ada Lovelace", "a@x.com")], "WS", "2026-11-20", config=Config())


def test_ledger_skips_and_returns_stored_link(tmp_path):
    class LiveLikeMock(MockNinjaBadgeClient):
        mode = "live"
    cfg = Config(api_key="k", pass_template_id="P", participation_template_id="Q")
    kw = dict(config=cfg, client=LiveLikeMock(), ledger_path=tmp_path / "l.json", **NOSLEEP)
    r1 = issue_badges([("Ada Lovelace", "a@x.com", "PASS")], "WS", "2026-11-20", **kw)
    r2 = issue_badges([("Ada Lovelace", "a@x.com", "PASS"), ("Bob Brown", "b@x.com")], "WS", "2026-11-20", **kw)
    assert r1.results[0].template_id == "P"
    assert [x.status for x in r2.results] == ["skipped", "issued"]
    assert r2.results[0].badge_url == r1.results[0].badge_url != ""
    assert r2.results[1].template_id == "Q" and r2.ok


def test_cli_dry_run(tmp_path, capsys):
    f = tmp_path / "p.csv"
    f.write_text("name,email,assessment_status\nAda Lovelace,ada@x.com,PASS\nAlan Turing,alan@x.com,\n")
    out = tmp_path / "report.csv"
    code = main([str(f), "-n", "WS", "-d", "2026-11-20", "--dry-run", "-q", "-o", str(out)])
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data["summary"]["pass_badges"] == 1 and data["summary"]["participation_badges"] == 1
    assert data["results"][0]["badge_url"].startswith("https://badges.ninja/awards/")
    assert "badge_url" in out.read_text().splitlines()[0]


def test_cli_errors(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("name,email\nAda Lovelace,a@x.com\n")
    assert main([str(f), "-n", "WS", "-d", "20/11/2026", "--dry-run", "-q"]) == 2
    assert main([str(f), "--dry-run", "-q"]) == 2   # missing workshop name/date


def test_cli_list_badges_dry_run(capsys):
    assert main(["--list-badges", "--dry-run"]) == 0
    assert "mock-pass-badge" in capsys.readouterr().out
