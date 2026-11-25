"""Exercise the real HTTP code path against a local fake BADGES.ninja server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from ninja_badge_issuer import Config, issue_badges
from ninja_badge_issuer.api import IssueBadgePayload, LiveNinjaBadgeClient, NinjaApiError

GUID = "c1d2e3f4-a5b6-7890-cdef-123456789012"


class Handler(BaseHTTPRequestHandler):
    calls = []
    fail_once = set()

    def log_message(self, *a):
        pass

    def _auth(self):
        if self.headers.get("X-Api-Key") != "bws_secret":
            self._send(401, {"message": "Invalid API key"})
            return False
        return True

    def do_GET(self):
        if not self._auth():
            return
        Handler.calls.append(("GET", self.path, None))
        self._send(200, [{"id": "https://api.badges.ninja/certify-badge/badge/b-111", "name": "PASS Badge"},
                         {"id": "https://api.badges.ninja/certify-badge/badge/b-222", "name": "Participation"}])

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.calls.append(("POST", self.path, body))
        if not self._auth():
            return
        p = body["parameters"]
        if self.path.endswith("/send"):
            return self._send(200, "email sent")
        email = p["recipient"]["email"]
        if "server" in email and email not in Handler.fail_once:
            Handler.fail_once.add(email)
            return self._send(503, {"message": "try later"})
        if "credits" in email:
            return self._send(402, {"message": "Out of credits"})
        if "guidonly" in email:
            return self._send(200, {"awardId": GUID})
        self._send(200, {"awardId": f"https://api.badges.ninja/certify-badge/award/{GUID}"})

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Handler.calls.clear()
    Handler.fail_once.clear()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_live_issue_end_to_end(server, tmp_path):
    cfg = Config(api_key="bws_secret", base_url=server,
                 pass_template_id="https://api.badges.ninja/certify-badge/badge/b-111",  # URL form accepted
                 participation_template_id="b-222")
    rep = issue_badges(
        [("Ada Lovelace", "ada@x.com", "PASS"), ("Retry Person", "server@x.com", "FAIL"),
         ("Guid Person", "guidonly@x.com"), ("No Credits", "credits@x.com")],
        "Cloud WS", "2026-11-20", config=cfg, ledger_path=tmp_path / "l.json",
        send_email=True, min_interval_s=0, sleep=lambda s: None,
    )
    r = rep.results
    assert rep.mode == "live"
    assert r[0].status == "issued" and r[0].award_id == GUID
    assert r[0].badge_url == f"https://badges.ninja/awards/{GUID}"
    assert r[0].pdf_url == f"https://api.badges.ninja/certify-badge/award/{GUID}/pdf"
    assert r[0].email_sent == "yes"
    assert (r[1].status, r[1].attempts) == ("issued", 2)           # 503 retried
    assert r[2].badge_url == f"https://badges.ninja/awards/{GUID}"  # bare-GUID response handled
    assert r[3].status == "failed" and "402" in r[3].error and r[3].attempts == 1  # 4xx not retried

    method, path, body = Handler.calls[0]
    assert (method, path) == ("POST", "/awards")
    assert body == {"parameters": {"badgeId": "b-111",
                                   "recipient": {"name": "Ada Lovelace", "email": "ada@x.com"},
                                   "issuedOn": "2026-11-20"}}
    assert Handler.calls[1] == ("POST", f"/awards/{GUID}/send",
                                {"parameters": {"awardId": GUID, "email": "ada@x.com"}})
    issue_bodies = [b for m, pth, b in Handler.calls if pth == "/awards"]
    assert issue_bodies[1]["parameters"]["badgeId"] == "b-222"


def test_list_templates(server):
    ts = LiveNinjaBadgeClient("bws_secret", server).list_templates()
    assert [(t.id, t.name) for t in ts] == [("b-111", "PASS Badge"), ("b-222", "Participation")]


def test_bad_key(server):
    with pytest.raises(NinjaApiError) as e:
        LiveNinjaBadgeClient("wrong", server).issue_badge(
            IssueBadgePayload("b-111", "Ada Lovelace", "a@x.com", "2026-11-20"))
    assert e.value.status == 401 and not e.value.retryable
