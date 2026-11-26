"""Organiser thank-you emails that contain each participant's badge link.

Works from the reviewed report CSV. Only rows with status=issued, a badge_url and
thanks_sent empty/"no" are emailed; the report is rewritten after every email, so
reruns never double-send. Modes: dry-run preview, .eml drafts, test mail, real SMTP.
"""
from __future__ import annotations

import configparser
import csv
import os
import re
import smtplib
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from string import Template
from typing import Callable, Iterable, Optional

from .notify import _write

REQUIRED = ("status", "email", "badge_url")
PENDING = ("", "no")                       # "yes" = done, "unknown" = needs manual check
NEW_COLS = ("thanks_sent", "thanks_sent_at", "thanks_error")

DEFAULT_SUBJECT = "Thank you for participating in $workshop_name - your badge"
DEFAULT_BODY = """Dear $name,

Thank you for taking part in the $workshop_name on $workshop_date.

$badge_sentence

You can view, download and share your badge here:

$badge_url

${pdf_line}\
The badge is a digital credential that you can add to your CV or professional profiles. \
If you have questions, or feedback on the workshop, simply reply to this email.

Kind regards,
$signature
"""


@dataclass
class MailConfig:
    host: str = ""
    port: int = 587
    security: str = "starttls"
    username: str = ""
    password: str = ""
    from_name: str = ""
    from_address: str = ""
    reply_to: str = ""
    signature: str = ""


def find_mail_config(path: Optional[str] = None) -> Path:
    cands = [path] if path else ["mail.ini", "secrets/mail.ini", "~/.ninja_mail.ini"]
    for c in cands:
        if c and Path(c).expanduser().is_file():
            return Path(c).expanduser()
    raise ValueError("mail config not found; tried: " + ", ".join(str(c) for c in cands))


def load_mail_config(path: Optional[str] = None, need_smtp: bool = True) -> MailConfig:
    p = find_mail_config(path)
    if os.name == "posix" and (p.stat().st_mode & 0o077):
        print(f"warning: {p} is readable by other users; run: chmod 600 {p}", file=sys.stderr)
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(p, encoding="utf-8")
    s, m = (cp["smtp"] if cp.has_section("smtp") else {}), (cp["message"] if cp.has_section("message") else {})
    cfg = MailConfig(
        host=(s.get("host", "") or "").strip(),
        port=int(s.get("port", "587") or 587),
        security=(s.get("security", "starttls") or "starttls").strip().lower(),
        username=(s.get("username", "") or "").strip(),
        password=os.environ.get("NINJA_SMTP_PASSWORD") or (s.get("password", "") or ""),
        from_name=(m.get("from_name", "") or "").strip(),
        from_address=(m.get("from_address", "") or "").strip(),
        reply_to=(m.get("reply_to", "") or "").strip(),
        signature=(m.get("signature", "") or m.get("from_name", "") or "").strip(),
    )
    if not cfg.from_address:
        raise ValueError(f"{p}: [message] from_address is required")
    if cfg.security not in ("starttls", "ssl", "none"):
        raise ValueError(f"{p}: security must be starttls, ssl or none")
    if need_smtp:
        if not cfg.host:
            raise ValueError(f"{p}: [smtp] host is required")
        if cfg.security == "none" and cfg.username:
            raise ValueError(f"{p}: refusing to send a password without TLS (security = none)")
    return cfg


def _read(path: str):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields, rows = list(reader.fieldnames or []), list(reader)
    missing = [c for c in REQUIRED if c not in fields]
    if missing:
        raise ValueError(f"{path}: not a badge report CSV (missing column(s): {', '.join(missing)})")
    for c in NEW_COLS:
        if c not in fields:
            fields.append(c)
    return fields, rows


def _is_pending(row: dict) -> bool:
    return (
        (row.get("status") or "").strip() == "issued"
        and bool((row.get("badge_url") or "").strip())
        and bool((row.get("email") or "").strip())
        and (row.get("dry_run") or "").strip().lower() != "true"
        and (row.get("thanks_sent") or "").strip().lower() in PENDING
    )


def _clean(s: str) -> str:
    return re.sub(r"[\r\n]+", " ", s or "").strip()


def build_message(row: dict, cfg: MailConfig, subject_tpl: str = DEFAULT_SUBJECT,
                  body_tpl: str = DEFAULT_BODY, *, to: Optional[str] = None,
                  subject_prefix: str = "") -> EmailMessage:
    email = _clean(to or row.get("email", ""))
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError(f"invalid email address: {email!r}")
    badge = (row.get("badge") or "").strip().upper()
    sentence = ("You successfully completed the workshop and earned the PASS badge."
                if badge == "PASS" else
                "You have earned the Participation badge for taking part in the workshop.")
    pdf = _clean(row.get("pdf_url", ""))
    vals = {
        "name": _clean(row.get("name", "")) or "participant",
        "email": email,
        "workshop_name": _clean(row.get("workshop_name", "")),
        "workshop_date": _clean(row.get("workshop_date", "")),
        "badge": badge or "PARTICIPATION",
        "badge_sentence": sentence,
        "badge_url": _clean(row.get("badge_url", "")),
        "pdf_line": f"PDF certificate: {pdf}\n\n" if pdf else "",
        "signature": cfg.signature,
    }
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.from_name, cfg.from_address))
    msg["To"] = email
    msg["Subject"] = subject_prefix + _clean(Template(subject_tpl).safe_substitute(vals))
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg.from_address.split("@")[-1])
    if cfg.reply_to:
        msg["Reply-To"] = cfg.reply_to
    msg.set_content(Template(body_tpl).safe_substitute(vals))
    return msg


def _connect(cfg: MailConfig):
    ctx = ssl.create_default_context()
    if cfg.security == "ssl":
        smtp = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=30, context=ctx)
    else:
        smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=30)
        smtp.ehlo()
        if cfg.security == "starttls":
            smtp.starttls(context=ctx)
            smtp.ehlo()
    if cfg.username:
        smtp.login(cfg.username, cfg.password)
    return smtp


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def send_thanks(
    report_path: str,
    cfg: MailConfig,
    *,
    subject_tpl: str = DEFAULT_SUBJECT,
    body_tpl: str = DEFAULT_BODY,
    skip: Iterable[str] = (),
    dry_run: bool = False,
    eml_dir: Optional[str] = None,
    test_to: Optional[str] = None,
    min_interval_s: float = 0.3,
    confirm: Optional[Callable[[int], bool]] = None,
    on_progress: Optional[Callable[[int, int, dict, str], None]] = None,
) -> dict:
    fields, rows = _read(report_path)
    skip_set = {s.strip().lower() for s in skip}
    pending = [r for r in rows if _is_pending(r) and r["email"].strip().lower() not in skip_set]
    total = len(pending)
    summary = {
        "selected": total, "sent": 0, "failed": 0, "unknown": 0, "written": 0,
        "already_sent": sum(1 for r in rows if (r.get("thanks_sent") or "").strip().lower() == "yes"),
        "skipped_by_user": sum(1 for r in rows if _is_pending(r) and r["email"].strip().lower() in skip_set),
        "aborted": False, "mode": "dry-run" if dry_run else "eml" if eml_dir else "test" if test_to else "send",
    }
    if total:
        # render everything first: bad addresses/templates surface before anything is sent
        previews = []
        for r in pending:
            try:
                previews.append(build_message(r, cfg, subject_tpl, body_tpl))
            except ValueError as e:
                raise ValueError(f"{r.get('email')}: {e}")
        summary["preview"] = str(previews[0])

    if dry_run:
        for i, r in enumerate(pending, 1):
            if on_progress:
                on_progress(i, total, r, "would-send")
        return summary

    if eml_dir:
        out = Path(eml_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        for i, (r, m) in enumerate(zip(pending, previews if total else []), 1):
            name = re.sub(r"[^A-Za-z0-9._@-]+", "_", r["email"].strip()) + ".eml"
            (out / name).write_bytes(bytes(m))
            summary["written"] += 1
            if on_progress:
                on_progress(i, total, r, "written")
        return summary

    if not total:
        return summary

    if test_to:
        smtp = _connect(cfg)
        try:
            smtp.send_message(build_message(pending[0], cfg, subject_tpl, body_tpl,
                                            to=test_to, subject_prefix="[TEST] "))
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
        summary["sent"] = 1
        if on_progress:
            on_progress(1, 1, {"email": test_to}, "test-sent")
        return summary

    if confirm and not confirm(total):
        summary["aborted"] = True
        return summary

    smtp = _connect(cfg)                       # fail fast on bad host/credentials
    try:
        for i, row in enumerate(pending, 1):
            outcome, err = "sent", ""
            try:
                smtp.send_message(build_message(row, cfg, subject_tpl, body_tpl))
            except (smtplib.SMTPRecipientsRefused, smtplib.SMTPResponseException, ValueError) as e:
                outcome, err = "failed", str(e)                      # definitely not delivered
            except (smtplib.SMTPServerDisconnected, TimeoutError, socket.timeout, OSError) as e:
                outcome, err = "unknown", str(e)                     # may have been delivered
            except Exception as e:
                outcome, err = "failed", str(e)

            if outcome == "sent":
                row["thanks_sent"], row["thanks_sent_at"], row["thanks_error"] = "yes", _now(), ""
                summary["sent"] += 1
            elif outcome == "unknown":
                row["thanks_sent"], row["thanks_error"] = "unknown", f"Thanks mail failed: {err}"
                summary["unknown"] += 1
            else:
                row["thanks_sent"], row["thanks_error"] = "no", f"Thanks mail failed: {err}"
                summary["failed"] += 1
            _write(report_path, fields, rows)                        # save progress after every email
            if on_progress:
                on_progress(i, total, row, outcome)

            if outcome == "unknown":                                 # connection is suspect: reconnect or stop
                try:
                    smtp.close()
                    smtp = _connect(cfg)
                except Exception as e:
                    summary["aborted"] = True
                    summary["error"] = f"stopped after connection loss: {e}"
                    break
            if i < total:
                time.sleep(min_interval_s)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    return summary
