"""
BADGES.ninja REST API client (standard library only).

Based on the official docs:
  https://badges.ninja/docs/api/awards
  https://badges.ninja/docs/api/badges
  https://badges.ninja/docs/api/errors

  Base URL : https://api.badges.ninja
  Auth     : X-Api-Key: <key>          (keys look like "bws_...")
  Body     : request fields wrapped in {"parameters": {...}}

  POST /awards                     issue a credential  -> {"awardId": "<url or guid>"}
  POST /awards/{awardGuid}/send    email the credential to the recipient
  GET  /badges                     list badge classes (templates)

Shareable links are derived from the award GUID (last path segment of awardId):
  public page (share this) : https://badges.ninja/awards/<guid>
  Open Badge JSON-LD       : https://api.badges.ninja/certify-badge/award/<guid>
  PDF certificate          : https://api.badges.ninja/certify-badge/award/<guid>/pdf

A MockNinjaBadgeClient with the same interface is provided for dry runs.
"""
from __future__ import annotations

import json
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

DEFAULT_BASE_URL = "https://api.badges.ninja"
PUBLIC_SITE_URL = "https://badges.ninja"

ENDPOINTS = {
    "list_badges": "/badges",                      # GET
    "issue": "/awards",                            # POST
    "send": "/awards/{award_guid}/send",           # POST
}

REQUEST_TIMEOUT_S = 30
MIN_NAME_LENGTH = 5          # API rejects recipient names shorter than this (HTTP 400)


# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------

@dataclass
class IssueBadgePayload:
    badge_template_id: str              # badge GUID (or full badge URL from GET /badges)
    recipient_name: str
    recipient_email: str
    issued_on: str                      # YYYY-MM-DD
    expires: Optional[str] = None       # YYYY-MM-DD (optional)


@dataclass
class IssueResult:
    award_id: str                       # GUID
    badge_url: str                      # public page to share with the participant
    assertion_url: str                  # Open Badge v2.0 JSON-LD
    pdf_url: str                        # PDF certificate
    issued_at: str
    raw: Any = field(default=None, repr=False)


@dataclass
class BadgeTemplate:
    id: str                             # GUID
    name: str
    description: Optional[str] = None
    url: Optional[str] = None           # full badge class URL


class NinjaApiError(Exception):
    def __init__(self, message: str, status: int = 0, retryable: bool = False,
                 retry_after_s: Optional[float] = None, maybe_issued: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.retry_after_s = retry_after_s
        # True when the request may have reached the server (e.g. timeout):
        # retrying could create a duplicate award.
        self.maybe_issued = maybe_issued


class NinjaBadgeClient(Protocol):
    mode: str  # "live" | "mock"

    def list_templates(self) -> list[BadgeTemplate]: ...
    def issue_badge(self, payload: IssueBadgePayload) -> IssueResult: ...
    def send_award_email(self, award_id: str, email: str) -> None: ...


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def guid_from(value: str) -> str:
    """'https://api.badges.ninja/certify-badge/award/<guid>' or '<guid>' -> '<guid>'."""
    return (value or "").strip().rstrip("/").rsplit("/", 1)[-1]


def links_for(award_guid: str) -> dict[str, str]:
    g = urllib.parse.quote(award_guid, safe="")
    return {
        "badge_url": f"{PUBLIC_SITE_URL}/awards/{g}",
        "assertion_url": f"{DEFAULT_BASE_URL}/certify-badge/award/{g}",
        "pdf_url": f"{DEFAULT_BASE_URL}/certify-badge/award/{g}/pdf",
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _issue_result(raw: Any) -> IssueResult:
    award = raw.get("awardId") if isinstance(raw, dict) else None
    if not award:
        raise NinjaApiError(f"Unexpected response from BADGES.ninja (no awardId): {str(raw)[:200]}",
                            200, retryable=False)
    guid = guid_from(str(award))
    return IssueResult(award_id=guid, issued_at=_now(), raw=raw, **links_for(guid))


# --------------------------------------------------------------------------
# Live client
# --------------------------------------------------------------------------

class LiveNinjaBadgeClient:
    mode = "live"

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL):
        if not api_key:
            raise ValueError("BADGES.ninja API key is required for live mode")
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    def _request(self, method: str, path: str, parameters: Optional[dict] = None) -> Any:
        data = json.dumps({"parameters": parameters}).encode() if parameters is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json",
                     "X-Api-Key": self.api_key},
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                text = resp.read().decode()
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            try:
                b = json.loads(body)
                detail = (b.get("message") or b.get("error") or b.get("detail") or body) if isinstance(b, dict) else body
            except ValueError:
                detail = body[:300] or e.reason
            ra = e.headers.get("Retry-After") if e.headers else None
            try:
                retry_after = float(ra) if ra else None
            except ValueError:
                retry_after = None
            # Per docs: retry only server-side errors; 429 means "not processed", also safe.
            raise NinjaApiError(f"BADGES.ninja API {e.code}: {detail}", e.code,
                                retryable=e.code == 429 or e.code >= 500,
                                retry_after_s=retry_after) from None
        except (socket.timeout, TimeoutError):
            # The request may have been processed: do NOT auto-retry (could duplicate).
            raise NinjaApiError("Request timed out: the badge MAY have been issued; "
                                "check the BADGES.ninja dashboard before retrying",
                                0, retryable=False, maybe_issued=True) from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, (socket.timeout, TimeoutError)):
                raise NinjaApiError("Request timed out: the badge MAY have been issued; "
                                    "check the BADGES.ninja dashboard before retrying",
                                    0, retryable=False, maybe_issued=True) from None
            # Connection failed before sending (DNS, refused): safe to retry.
            raise NinjaApiError(f"Network error: {e.reason}", 0, retryable=True) from None
        try:
            return json.loads(text) if text else None
        except ValueError:
            return text  # e.g. plain "email sent"

    def list_templates(self) -> list[BadgeTemplate]:
        data = self._request("GET", ENDPOINTS["list_badges"])
        items = data if isinstance(data, list) else (data or {}).get("items", [])
        return [BadgeTemplate(id=guid_from(str(b.get("id", ""))), name=str(b.get("name", "")),
                              description=b.get("description"), url=b.get("id"))
                for b in items if b.get("id")]

    def issue_badge(self, payload: IssueBadgePayload) -> IssueResult:
        params: dict[str, Any] = {
            "badgeId": guid_from(payload.badge_template_id),
            "recipient": {"name": payload.recipient_name, "email": payload.recipient_email},
            "issuedOn": payload.issued_on,
        }
        if payload.expires:
            params["expires"] = payload.expires
        return _issue_result(self._request("POST", ENDPOINTS["issue"], params))

    def send_award_email(self, award_id: str, email: str) -> None:
        guid = guid_from(award_id)
        path = ENDPOINTS["send"].format(award_guid=urllib.parse.quote(guid, safe=""))
        self._request("POST", path, {"awardId": guid, "email": email})


# --------------------------------------------------------------------------
# Mock client (dry run)
# --------------------------------------------------------------------------

class MockNinjaBadgeClient:
    """
    Simulates BADGES.ninja. Test hooks:
      - email containing "+fail"  -> permanent 400 error
      - email containing "+flaky" -> 503 on first attempt, then success
    Returned links follow the real URL pattern but point to non-existent awards.
    """
    mode = "mock"

    def __init__(self, latency_s: float = 0.0):
        self.latency_s = latency_s
        self._flaky_seen: set[str] = set()
        self.sent_emails: list[tuple[str, str]] = []

    def list_templates(self) -> list[BadgeTemplate]:
        return [BadgeTemplate("mock-pass-badge", "Workshop PASS Badge"),
                BadgeTemplate("mock-participation-badge", "Workshop PARTICIPATION Badge")]

    def issue_badge(self, payload: IssueBadgePayload) -> IssueResult:
        if self.latency_s:
            time.sleep(self.latency_s * (0.5 + random.random()))
        email = payload.recipient_email.lower()
        if "+fail" in email:
            raise NinjaApiError("BADGES.ninja API 400: recipient rejected (mock)", 400)
        if "+flaky" in email:
            key = f"{payload.badge_template_id}|{email}"
            if key not in self._flaky_seen:
                self._flaky_seen.add(key)
                raise NinjaApiError("BADGES.ninja API 503: service unavailable (mock)", 503, retryable=True)
        guid = str(uuid.uuid4())
        return _issue_result({"awardId": f"{DEFAULT_BASE_URL}/certify-badge/award/{guid}"})

    def send_award_email(self, award_id: str, email: str) -> None:
        self.sent_emails.append((award_id, email))
