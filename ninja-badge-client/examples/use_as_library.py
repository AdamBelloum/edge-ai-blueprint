"""Calling the issuer from another Python program."""
from ninja_badge_issuer import issue_badges

participants = [
    {"name": "Ada Lovelace", "email": "ada@example.com", "status": "PASS"},
    {"name": "Grace Hopper", "email": "grace@example.com"},          # no result -> PARTICIPATION
    ("Alan Turing", "alan@example.com", "FAIL"),                       # tuples work too
]

report = issue_badges(participants, "Advanced Cloud Architecture", "2026-11-20", dry_run=True)

print(report.summary)
for r in report.results:
    print(r.status, r.badge, r.email, r.badge_url or r.error)
