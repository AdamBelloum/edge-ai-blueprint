# Ninja Badge Issuer (Python client for BADGES.ninja)

Give it a list of participants (name and email, plus an optional assessment result). It issues a **PASS** or **PARTICIPATION** badge to each person through the [BADGES.ninja](https://badges.ninja) REST API and returns, for each person:

- the **public badge link to share with the participant**: `https://badges.ninja/awards/<award-id>`
- a link to the PDF certificate
- the award ID and the issue status

It can also ask BADGES.ninja to **email each participant their badge** (`--send-email`).

- Python 3.9 or later, **standard library only** (nothing to `pip install`).
- The API key comes from a **config file or environment variables**. The tool never prompts for it.
- It can be used as a **command-line program** or as a **Python function**.

## 1. Configure (once)

1. In the BADGES.ninja dashboard, create the two badges (PASS and PARTICIPATION) and an API key. Keys start with `bws_`.
2. Copy `ninja_badge.example.ini` to `ninja_badge.ini` (in the folder you run from) or to `~/.ninja_badge.ini`, and fill in the key:

   ```ini
   [ninja_badge]
   api_key = bws_xxxxxxxxxxxxxxxx
   base_url = https://api.badges.ninja
   pass_template_id = <PASS badge id>
   participation_template_id = <PARTICIPATION badge id>
   ```

3. Find the two badge IDs with:

   ```bash
   python -m ninja_badge_issuer --list-badges
   ```

   Either the bare ID or the full `https://api.badges.ninja/certify-badge/badge/<id>` URL works.

Instead of the file, you can use these environment variables: `NINJA_BADGE_API_KEY`, `NINJA_BADGE_API_BASE_URL`, `NINJA_BADGE_PASS_TEMPLATE_ID`, `NINJA_BADGE_PARTICIPATION_TEMPLATE_ID`. They override the file. `--config` or `NINJA_BADGE_CONFIG` can point to any other config file.

## 2. Input

You can give a CSV file, a JSON file, or `-` to read CSV or JSON from stdin.

```csv
name,email,assessment_status
Ada Lovelace,ada@example.com,PASS
Alan Turing,alan@example.com,FAIL
Grace Hopper,grace@example.com,
```

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | recipient name. **At least 5 characters** (a BADGES.ninja rule) |
| `email` | yes | recipient email (validated; duplicates in a batch are rejected) |
| `status` / `assessment_status` | no | `PASS`, `FAIL` or `NOT_TAKEN`. Variants such as `Passed`, `Failed`, `No Show` and `Absent` are also accepted |
| `score` | no | used instead of `status` when `--passing-score` is given |
| `badge` | no | force `PASS` or `PARTICIPATION` for this person |

**Badge rule:** a person gets the PASS badge only if they passed. Anyone who failed, didn't take the assessment or has no status gets the PARTICIPATION badge.

## 3. Run: command line (for a menu item or script)

```bash
python -m ninja_badge_issuer participants.csv \
    --workshop-name "Advanced Cloud Architecture" --date 2026-11-20 \
    --send-email -o badges_report.csv
```

| Option | |
|---|---|
| `-n/--workshop-name`, `-d/--date` | **required**; the date (`YYYY-MM-DD`) becomes the badge's issue date |
| `--send-email` | BADGES.ninja emails each participant their badge |
| `--expires YYYY-MM-DD` | optional badge expiry date |
| `--dry-run` | simulate the calls and issue nothing (no API key needed) |
| `--passing-score 70` | grade by `score` (pass if >= 70) instead of `status` |
| `-o report.csv` / `-o report.json` | also save the report to a file |
| `--format csv` | print CSV instead of JSON on stdout |
| `-c/--config path` | config file location |
| `--ledger path` / `--no-ledger` | duplicate-protection file (default `~/.ninja_badge_ledger.json`) |
| `--min-interval 0.3` | seconds between API calls |
| `-q` | no progress output on stderr |
| `--list-badges` | list your badge templates and their IDs, then exit |

### What it returns

- **Exit code:**
  - `0`: everyone was issued, or skipped because they already had the badge.
  - `1`: at least one person failed or was invalid. See `results[].error`.
  - `2`: bad arguments, missing configuration or an unreadable input file. Nothing was issued.
- **stdout:** the JSON report (or CSV with `--format csv`).
- **stderr:** one progress line per person, including their badge link, then a summary.

```json
{
  "workshop_name": "Advanced Cloud Architecture",
  "workshop_date": "2026-11-20",
  "mode": "live",
  "summary": {"total": 3, "issued": 2, "failed": 1, "skipped": 0, "invalid": 0,
              "pass_badges": 1, "participation_badges": 1},
  "results": [
    {
      "name": "Ada Lovelace", "email": "ada@example.com",
      "assessment_outcome": "PASS", "badge": "PASS", "template_id": "b1c2d3e4-...",
      "status": "issued",
      "award_id": "c1d2e3f4-a5b6-7890-cdef-123456789012",
      "badge_url": "https://badges.ninja/awards/c1d2e3f4-a5b6-7890-cdef-123456789012",
      "pdf_url": "https://api.badges.ninja/certify-badge/award/c1d2e3f4-a5b6-7890-cdef-123456789012/pdf",
      "assertion_url": "https://api.badges.ninja/certify-badge/award/c1d2e3f4-a5b6-7890-cdef-123456789012",
      "issued_at": "2026-11-20T10:00:00+00:00",
      "email_sent": "yes", "error": "", "attempts": 1, "dry_run": false
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `badge_url` | **public page to share with the participant.** It shows the badge and has buttons to share it on LinkedIn (including "Add to Profile"), X, Facebook and so on. Anyone can verify it without an account |
| `pdf_url` | printable PDF certificate |
| `assertion_url` | machine-readable Open Badge v2.0 record, for automated verification |
| `email_sent` | `yes` / `no` when `--send-email` was used, empty otherwise. If the email fails, the badge stays issued and `error` explains the email problem |
| `status` | `issued`; `failed` (API error, see `error`); `invalid` (bad input, no API call made); `skipped` (already issued for this workshop and date; the stored `badge_url` is still returned) |

**To retry the failures**, run the same command again. People who already got their badge are skipped, and their existing link is returned.

## 4. Run: as a Python library

```python
from ninja_badge_issuer import issue_badges

report = issue_badges(
    [{"name": "Ada Lovelace", "email": "ada@example.com", "status": "PASS"},
     ("Grace Hopper", "grace@example.com")],
    workshop_name="Advanced Cloud Architecture",
    workshop_date="2026-11-20",
    send_email=True,            # optional
)
for r in report.results:
    print(r.name, r.badge, r.status, r.badge_url)
```

## Behaviour and safety

- **Rate limiting:** calls are made one at a time, at least `--min-interval` seconds apart.
- **Retries:**
  - Server errors (5xx), 429 errors and connections that failed before being sent are retried up to 3 times with backoff.
  - Other 4xx errors are not retried: 400 (invalid data), 401 (bad key), 402 (out of credits) and 404 (badge not found).
- **Timeouts are not retried.** If a request times out, BADGES.ninja may already have issued the badge, and a second call would issue a duplicate. The row is marked `failed` with a message asking you to check the dashboard first.
- **Duplicate protection:** in live mode, each issued badge (with its link) is recorded in `~/.ninja_badge_ledger.json`, keyed by workshop, date and email. The ledger is a local file, so badges issued from another computer or from the dashboard aren't known to it.
- **Workshop name:** BADGES.ninja's issue call has no field for it. It appears in the report, and the badge's own name and description (set in the dashboard) describe the workshop.
- **Credits:** each issued badge uses one credit from your BADGES.ninja plan.

### Dry run

`--dry-run` issues nothing and needs no key. It returns links in the real format, but they point to badges that don't exist. Two special email patterns let you test error handling:

- An email containing `+fail` always fails.
- An email containing `+flaky` fails once, then succeeds when retried.

## API reference used

This client implements the official BADGES.ninja API ([awards](https://badges.ninja/docs/api/awards), [badges](https://badges.ninja/docs/api/badges), [errors](https://badges.ninja/docs/api/errors)):

| Call | Purpose |
|---|---|
| `POST /awards` with `{"parameters": {"badgeId", "recipient": {"name", "email"}, "issuedOn", "expires"?}}` | issue a badge; returns `{"awardId": ...}` |
| `POST /awards/{id}/send` with `{"parameters": {"awardId", "email"}}` | email the badge to the participant |
| `GET /badges` | list badge templates |

Authentication is the header `X-Api-Key: <key>`. All API-specific code is in `ninja_badge_issuer/api.py`.

## Tests

```bash
python -m pytest -q
```

The tests cover the badge rules, validation, the share links, email sending, the ledger and the command line. They also exercise the live HTTP code (auth header, request format, 503 retry, 402 not retried, both forms of `awardId`) against a local fake BADGES.ninja server.
