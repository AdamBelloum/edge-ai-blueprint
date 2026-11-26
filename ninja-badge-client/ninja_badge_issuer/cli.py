"""
Command-line entry point.

    python -m ninja_badge_issuer participants.csv \
        --workshop-name "Advanced Cloud Architecture" --date 2026-11-20 [--send-email] [--dry-run]

    python -m ninja_badge_issuer --list-badges      # show your badge IDs for the config file

stdout : JSON report (or CSV with --format csv)
stderr : progress / errors
exit   : 0 = all issued (or skipped as already issued)
         1 = at least one participant failed or was invalid
         2 = bad arguments / configuration / input file
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .issuer import issue_badges, load_participants


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ninja-badge-issuer",
                                description="Issue Ninja Badge PASS / PARTICIPATION badges to workshop participants.")
    p.add_argument("input", nargs="?", help="participants file (.csv or .json), or '-' for stdin")
    p.add_argument("-n", "--workshop-name")
    p.add_argument("-d", "--date", help="workshop date, YYYY-MM-DD")
    p.add_argument("--send-email", action="store_true",
                   help="ask BADGES.ninja to email each participant their badge")
    p.add_argument("--expires", help="optional badge expiry date, YYYY-MM-DD")
    p.add_argument("--list-badges", action="store_true",
                   help="list the badge templates in your account (IDs for ninja_badge.ini) and exit")
    p.add_argument("-c", "--config", help="path to ninja_badge.ini (default: ./ninja_badge.ini, ~/.ninja_badge.ini)")
    p.add_argument("--dry-run", action="store_true", help="simulate API calls, issue nothing")
    p.add_argument("--passing-score", type=float,
                   help="grade by numeric 'score' column (>= this passes) instead of 'status'")
    p.add_argument("-o", "--output", help="also write the report to a file (.csv or .json)")
    p.add_argument("--format", choices=["json", "csv"], default="json", help="stdout format (default json)")
    p.add_argument("--ledger", default="~/.ninja_badge_ledger.json",
                   help="file recording live issuances to prevent duplicates")
    p.add_argument("--no-ledger", action="store_true", help="disable the duplicate-issuance ledger")
    p.add_argument("--min-interval", type=float, default=0.3, help="seconds between API calls (default 0.3)")
    p.add_argument("-q", "--quiet", action="store_true", help="no progress on stderr")
    p.add_argument("--send-from-report", metavar="REPORT",
                   help="email recipients from a reviewed report CSV (status=issued, not yet emailed), then exit")
    p.add_argument("--skip", action="append", metavar="EMAIL",
                   help="exclude this email from --send-from-report (repeatable)")
    p.add_argument("--yes", action="store_true",
                   help="do not prompt before sending with --send-from-report")
    p.add_argument("--send-thanks", metavar="REPORT",
                   help="send organiser thank-you emails with badge links from a reviewed report CSV")
    p.add_argument("--thanks-template", metavar="FILE",
                   help="thank-you text file; optional first line 'Subject: ...', then the body")
    p.add_argument("--mail-config", metavar="FILE",
                   help="SMTP/sender config (default: mail.ini, secrets/mail.ini, ~/.ninja_mail.ini)")
    p.add_argument("--eml-dir", metavar="DIR",
                   help="with --send-thanks: write one .eml draft per participant instead of sending")
    p.add_argument("--test-to", metavar="ADDR",
                   help="with --send-thanks: send one [TEST] message to ADDR; the report is not changed")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def list_badges(args) -> int:
    from .api import LiveNinjaBadgeClient, MockNinjaBadgeClient, NinjaApiError
    try:
        cfg = load_config(args.config)
        client = MockNinjaBadgeClient() if args.dry_run else LiveNinjaBadgeClient(cfg.api_key, cfg.base_url)
        templates = client.list_templates()
    except (OSError, ValueError, NinjaApiError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps([{"id": t.id, "name": t.name} for t in templates], indent=2, ensure_ascii=False))
    return 0


def send_report_emails(args) -> int:
    from .api import LiveNinjaBadgeClient, MockNinjaBadgeClient
    from .notify import send_from_report
    err = sys.stderr
    try:
        cfg = load_config(args.config)
        client = MockNinjaBadgeClient() if args.dry_run else LiveNinjaBadgeClient(cfg.api_key, cfg.base_url)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=err)
        return 2

    def confirm(n):
        if args.yes:
            return True
        ans = input(f"Send {n} email(s) from {args.send_from_report}? Type 'yes' to continue: ")
        return ans.strip().lower() == "yes"

    def progress(i, total, row, outcome):
        if not args.quiet:
            print(f"[{i}/{total}] {outcome.upper():10} {row.get('email', '')}", file=err)

    try:
        s = send_from_report(args.send_from_report, client, skip=args.skip or [],
                             dry_run=args.dry_run, min_interval_s=args.min_interval,
                             confirm=confirm, on_progress=progress)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=err)
        return 2
    print(json.dumps(s, indent=2), file=err)
    return 0 if s["failed"] == 0 and s["unknown"] == 0 and not s["aborted"] else 1


def send_thanks_cmd(args) -> int:
    import configparser
    from .thanks import DEFAULT_BODY, DEFAULT_SUBJECT, load_mail_config, send_thanks
    err = sys.stderr
    if args.send_from_report:
        print("error: use either --send-thanks or --send-from-report, not both", file=err)
        return 2
    subject_tpl, body_tpl = DEFAULT_SUBJECT, DEFAULT_BODY
    try:
        if args.thanks_template:
            text = Path(args.thanks_template).read_text(encoding="utf-8")
            first, _, rest = text.partition("\n")
            if first.lower().startswith("subject:"):
                subject_tpl, body_tpl = first[len("subject:"):].strip(), rest.lstrip("\n")
            else:
                body_tpl = text
        needs_smtp = not (args.dry_run or args.eml_dir)
        cfg = load_mail_config(args.mail_config, need_smtp=needs_smtp)
    except (OSError, ValueError, configparser.Error) as e:
        print(f"error: {e}", file=err)
        return 2

    def confirm(n):
        if args.yes:
            return True
        ans = input(f"Send {n} thank-you email(s) from {cfg.from_address}? Type 'yes' to continue: ")
        return ans.strip().lower() == "yes"

    def progress(i, total, row, outcome):
        if not args.quiet:
            print(f"[{i}/{total}] {outcome.upper():10} {row.get('email', '')}", file=err)

    try:
        s = send_thanks(args.send_thanks, cfg, subject_tpl=subject_tpl, body_tpl=body_tpl,
                        skip=args.skip or [], dry_run=args.dry_run, eml_dir=args.eml_dir,
                        test_to=args.test_to, min_interval_s=args.min_interval,
                        confirm=confirm, on_progress=progress)
    except (OSError, ValueError, Exception) as e:
        print(f"error: {e}", file=err)
        return 2
    if args.dry_run and s.get("preview"):
        print("--- preview of the first message ---", file=err)
        print(s["preview"], file=err)
    s.pop("preview", None)
    print(json.dumps(s, indent=2), file=err)
    ok = s["failed"] == 0 and s["unknown"] == 0 and not s["aborted"] and "error" not in s
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    err = sys.stderr

    if args.send_thanks:
        return send_thanks_cmd(args)

    if args.send_from_report:
        return send_report_emails(args)

    if args.list_badges:
        return list_badges(args)
    missing = [n for n, v in (("input", args.input), ("--workshop-name", args.workshop_name),
                              ("--date", args.date)) if not v]
    if missing:
        print(f"error: missing required argument(s): {', '.join(missing)}", file=err)
        return 2

    try:
        cfg = load_config(args.config)
        participants = load_participants(args.input)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=err)
        return 2
    if not participants:
        print("error: no participants found in input", file=err)
        return 2

    def progress(i, total, r):
        if not args.quiet:
            extra = r.badge_url or r.error
            if r.badge_url and r.error:
                extra += f"  ({r.error})"
            print(f"[{i}/{total}] {r.status.upper():8} {r.badge:13} {r.email}  {extra}", file=err)

    try:
        report = issue_badges(
            participants, args.workshop_name, args.date,
            config=cfg, dry_run=args.dry_run, passing_score=args.passing_score,
            send_email=args.send_email, expires=args.expires,
            ledger_path=None if args.no_ledger else args.ledger,
            min_interval_s=args.min_interval, on_progress=progress,
        )
    except ValueError as e:
        print(f"error: {e}", file=err)
        return 2

    if args.output:
        out = Path(args.output)
        out.write_text(report.to_csv() if out.suffix.lower() == ".csv" else report.to_json(), encoding="utf-8")
    sys.stdout.write(report.to_csv() if args.format == "csv" else report.to_json() + "\n")

    if not args.quiet:
        s = report.summary
        print(f"{report.mode} mode: {s['issued']} issued ({s['pass_badges']} PASS, "
              f"{s['participation_badges']} PARTICIPATION), {s['failed']} failed, "
              f"{s['invalid']} invalid, {s['skipped']} skipped", file=err)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
