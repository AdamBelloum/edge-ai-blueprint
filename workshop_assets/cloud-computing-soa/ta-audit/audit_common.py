"""Shared parts of the TA audit scripts: checks, HTTP client, report.

A check is a function registered with @check. It receives a context and calls
ctx.problem() for every problem it finds (with the HTTP exchange as
evidence), ctx.observe() for facts worth knowing, or ctx.skip() when it
cannot run. The check's severity applies to its problems; observations make
an INFO check report, and are shown with the problems of other checks:

    FAIL  the service breaks the assignment's specification or has a bug
          (crash, data loss, security hole): grounds for a deduction
    WARN  questionable or debatable behaviour: ask in the oral exam, deduct
          only if the explanation does not convince
    INFO  observations to know before the oral exam

Run this file (python audit_common.py) to rewrite CHECKS.md, the list of
every check, after adding or changing one.
"""
import json
import math
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List
from urllib.parse import unquote

import requests

SEVERITIES = ("FAIL", "WARN", "INFO")
ORDER = {"FAIL": 0, "ERROR": 1, "WARN": 2, "INFO": 3, "SKIP": 4, "PASS": 5}
ALPHABET62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
# A PEM private key: the BEGIN line, base64 (with the headers of an encrypted
# key, or with "\n" escapes in JSON and environment variables), the END line.
# Code that only names the markers, as the cryptography library does, does
# not match.
PEM_PRIVATE_KEY = re.compile(
    rb"-----BEGIN ([A-Z0-9 ]*)PRIVATE KEY-----(?:\\n|\s)+[A-Za-z0-9+/=\s:,\\-]{64,}?-----END \1PRIVATE KEY-----")


@dataclass
class Check:
    id: str
    area: str
    title: str
    severity: str
    why: str
    ask: str
    function: Callable


@dataclass
class Result:
    check: Check
    status: str  # PASS, FAIL, WARN, INFO, SKIP or ERROR
    problems: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def details(self):
        return self.problems + self.notes


class SkipCheck(Exception):
    """The check cannot run, for example because an earlier step failed."""


class ServiceUnreachable(Exception):
    pass


def registry():
    """A list and a decorator that adds checks to it."""
    checks = []

    def check(check_id, area, title, severity="FAIL", why="", ask=""):
        if severity not in SEVERITIES:
            raise ValueError(severity)

        def register(function):
            checks.append(Check(check_id, area, title, severity, why, ask, function))
            return function
        return register
    return checks, check


def shorten(text, limit=160):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


class Response:
    """An HTTP answer plus a one-line description of the exchange."""

    def __init__(self, method, url, sent, raw):
        self.raw = raw
        self.status = raw.status_code
        self.text = raw.text
        self.headers = raw.headers
        location = raw.headers.get("Location")
        received = f"{self.status} {shorten(self.text, 120)}".strip()
        if location:
            received += f" [Location: {shorten(location, 80)}]"
        self.exchange = f"{method} {url} {sent}-> {received}"

    def json(self):
        try:
            return self.raw.json()
        except ValueError:
            return None

    @property
    def ok(self):
        return 200 <= self.status < 300


class Client:
    """Sends requests to one service and records every exchange."""

    def __init__(self, base_url, headers=None, timeout=(5, 30)):
        self.base_url = base_url.rstrip("/")
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.log = []
        self.texts = []  # full answer bodies, for checks that search them

    def with_headers(self, headers):
        return Client(self.base_url, headers, self.timeout)

    def request(self, method, path, json_body=None, data=None, headers=None, has_body=None):
        all_headers = dict(self.headers)
        all_headers.update(headers or {})
        kwargs = {"headers": all_headers, "timeout": self.timeout, "allow_redirects": False}
        sent = ""
        if has_body is None:
            has_body = json_body is not None
        if data is not None:
            kwargs["data"] = data
            sent = f"{shorten(data if isinstance(data, str) else repr(data), 100)} "
        elif has_body:
            kwargs["json"] = json_body
            sent = f"{shorten(json.dumps(json_body, ensure_ascii=False), 100)} "
        url = self.base_url + path
        try:
            raw = requests.request(method, url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as error:
            raise ServiceUnreachable(f"{method} {url}: {type(error).__name__}") from None
        response = Response(method, path, sent, raw)
        self.log.append(response.exchange)
        self.texts.append(raw.text[:100000])
        return response

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, body=None, **kwargs):
        return self.request("POST", path, json_body=body, **kwargs)

    def put(self, path, body=None, **kwargs):
        return self.request("PUT", path, json_body=body, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)


def wait_for(*clients, seconds=15):
    """Send GET / to each client until it answers; raise ServiceUnreachable after the given time."""
    deadline = time.monotonic() + seconds
    for client in clients:
        while True:
            try:
                client.get("/")
                break
            except ServiceUnreachable:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)


class Context:
    """What a check sees. Subclasses add the clients and helpers they need."""

    def __init__(self):
        self.run = uuid.uuid4().hex[:8]
        self.result = None
        self.shared = {}

    def problem(self, text, response=None):
        self.result.problems.append(text)
        if response is not None:
            self.result.evidence.append(response.exchange)

    def observe(self, text):
        self.result.notes.append(text)

    def skip(self, reason):
        raise SkipCheck(reason)

    def url(self, name):
        """A URL that is unique for this run."""
        return f"https://example.com/audit-{self.run}/{name}"


def run_checks(checks, context, prefix, only=None, verbose=False):
    results = []
    for check in checks:
        full_id = f"{prefix}-{check.id}"
        if only and not any(full_id.startswith(pattern) for pattern in only):
            continue
        result = Result(Check(full_id, check.area, check.title, check.severity,
                              check.why, check.ask, check.function), "PASS")
        context.result = result
        started = time.monotonic()
        try:
            check.function(context)
            if result.problems:
                result.status = check.severity
            elif result.notes and check.severity == "INFO":
                result.status = "INFO"
        except SkipCheck as reason:
            result.status = "SKIP"
            result.notes.append(str(reason))
        except ServiceUnreachable as error:
            result.status = "ERROR"
            result.problems.append(f"service unreachable: {error}")
        except Exception as error:  # a broken answer must not stop the audit
            result.status = "ERROR"
            result.problems.append(f"{type(error).__name__}: {error}")
        result.seconds = time.monotonic() - started
        results.append(result)
        if verbose:
            print(f"  {result.status:<5} {full_id} {check.title}", file=sys.stderr, flush=True)
    return results


def print_report(title, target, results, stream=sys.stdout):
    counts = {status: 0 for status in ORDER}
    for result in results:
        counts[result.status] += 1
    print(f"\n{title}\n{target}\n", file=stream)
    for result in sorted(results, key=lambda r: (ORDER[r.status], r.check.id)):
        if result.status == "PASS":
            continue
        check = result.check
        print(f"{result.status:<5} {check.id}  {check.title}", file=stream)
        for detail in result.details[:8]:
            print(f"      - {shorten(detail, 300)}", file=stream)
        if len(result.details) > 8:
            print(f"      - ... {len(result.details) - 8} more", file=stream)
        for exchange in result.evidence[:4]:
            print(f"      > {shorten(exchange, 300)}", file=stream)
        if result.status in ("FAIL", "WARN") and check.why:
            print(f"      Why: {check.why}", file=stream)
        if result.status in ("FAIL", "WARN") and check.ask:
            print(f"      Ask: {check.ask}", file=stream)
        print(file=stream)
    summary = ", ".join(f"{counts[s]} {s}" for s in ("FAIL", "WARN", "ERROR", "INFO", "SKIP", "PASS"))
    print(f"Summary: {summary} ({len(results)} checks)", file=stream)


def write_markdown(path, title, target, results):
    lines = [f"# {title}", "", target, "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}.", ""]
    counts = {status: sum(r.status == status for r in results) for status in ORDER}
    lines.append(" · ".join(f"**{counts[s]}** {s}" for s in ("FAIL", "WARN", "ERROR", "INFO", "SKIP", "PASS")))
    lines += ["", "## Findings", ""]
    findings = [r for r in sorted(results, key=lambda r: (ORDER[r.status], r.check.id)) if r.status != "PASS"]
    if not findings:
        lines.append("No findings.")
    for result in findings:
        check = result.check
        lines += [f"### {result.status} · {check.id} · {check.title}", "", f"Area: {check.area}", ""]
        for detail in result.details:
            lines.append(f"- {detail}")
        if result.evidence:
            lines += ["", "Evidence:", "", "```"]
            lines += [shorten(exchange, 500) for exchange in result.evidence[:10]]
            lines.append("```")
        if result.status in ("FAIL", "WARN"):
            if check.why:
                lines += ["", f"**Why:** {check.why}"]
            if check.ask:
                lines += ["", f"**Oral exam:** {check.ask}"]
        lines.append("")
    lines += ["## All checks", "", "| Result | Check | Area | Title |", "|---|---|---|---|"]
    for result in sorted(results, key=lambda r: r.check.id):
        lines.append(f"| {result.status} | {result.check.id} | {result.check.area} | {result.check.title} |")
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def base62_length(count):
    """Characters needed to give count different identifiers with 62 symbols."""
    return max(1, math.ceil(math.log(max(count, 2), 62)))


def listed(value):
    """What a JSON answer lists: dictionary keys, strings, and numbers in lists."""
    if isinstance(value, dict):
        found = {str(key) for key in value}
        for item in value.values():
            found |= listed(item)
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            if isinstance(item, int) and not isinstance(item, bool):
                found.add(str(item))
            else:
                found |= listed(item)
        return found
    return {value} if isinstance(value, str) else set()


def returned_id(response):
    """The identifier in the answer to POST /, or None."""
    body = response.json()
    if isinstance(body, dict):
        for key in ("id", "key", "short_id", "shortId", "identifier", "short"):
            value = body.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
                return str(value)
        values = [value for value in body.values() if isinstance(value, str) and value]
        return values[0] if len(values) == 1 else None
    if isinstance(body, (str, int)) and not isinstance(body, bool):
        return str(body)
    text = response.text.strip()
    if body is None and text and len(text) <= 64 and not any(char.isspace() for char in text):
        return text
    return None


def target_of(response):
    """The URL a 301 answer points to: the Location header, or the URL in the body."""
    location = response.headers.get("Location")
    if location:
        return location
    return body_target(response)


def body_target(response):
    """The URL in the JSON body of a 301 answer, or None."""
    body = response.json()
    if isinstance(body, dict):
        for key in ("value", "url", "long_url", "longUrl", "target", "original_url"):
            if isinstance(body.get(key), str):
                return body[key]
        values = [value for value in body.values() if isinstance(value, str)]
        return values[0] if len(values) == 1 else None
    return body if isinstance(body, str) else None


def gives_url(response, url):
    """A 301 whose Location header or body holds url.

    Either place counts here; METHOD-04 checks the Location header on its own,
    so one wrong header does not fail every check that resolves a link.
    """
    return response.status == 301 and (
        same_url(response.headers.get("Location"), url) or same_url(body_target(response), url))


def same_url(first, second):
    """Compare URLs, ignoring percent-encoding (a Location header must be ASCII)."""
    return first is not None and second is not None and unquote(first) == unquote(second)


def is_5xx(response):
    return response.status >= 500


def holds_private_key(data):
    if isinstance(data, str):
        data = data.encode("utf-8", "replace")
    return PEM_PRIVATE_KEY.search(data) is not None


def catalogue():
    """The text of CHECKS.md: every check, with why it matters and the oral-exam question."""
    import audit_a1, audit_a2, audit_a3  # imported here because they import this module

    def cell(text):
        return " ".join(text.split()).replace("|", "\\|") or "–"

    lines = ["# TA audit checks", "",
             "Every check of the audit scripts, generated from them by `python audit_common.py`.",
             "README.md explains FAIL, WARN and INFO and how to run the scripts.", ""]
    sections = [
        ("Assignment 1: `audit_a1.py`", "A1", audit_a1.CHECKS, None),
        ("Assignment 2: `audit_a2.py`", "A2", audit_a2.CHECKS,
         "After these checks, `audit_a2.py` runs every Assignment 1 check again through the multi-user "
         "shortener, with a token, and reports them as A2-METHOD-01 and so on."),
        ("Assignment 3.1: `audit_a3.py --part 3.1`", "A3", audit_a3.CHECKS_31, None),
        ("Assignment 3.2: `audit_a3.py --part 3.2`", "A3", audit_a3.CHECKS_32, None),
    ]
    for heading, prefix, checks, note in sections:
        lines += [f"## {heading}", ""] + ([note, ""] if note else [])
        lines += ["| Check | Severity | What is checked | Why | Oral exam |", "|---|---|---|---|---|"]
        areas = {}
        for check in checks:
            areas.setdefault(check.id.rsplit("-", 1)[0], len(areas))
        for check in sorted(checks, key=lambda check: (areas[check.id.rsplit("-", 1)[0]], check.id)):
            lines.append(f"| {prefix}-{check.id} | {check.severity} | {cell(check.title)} | {cell(check.why)} "
                         f"| {cell(check.ask)} |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    from pathlib import Path
    Path(__file__).with_name("CHECKS.md").write_text(catalogue(), encoding="utf-8")
