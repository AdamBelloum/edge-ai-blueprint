#!/usr/bin/env bash
# Organiser tool: issue Ninja Badges from a reviewed grading summary.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: create-badges.sh

Interactively turn a reviewed grading summary.csv (from grade_exam.py) into
Ninja Badges. Steps: confirm review, export the badge list, dry run, then
typed confirmation before live issuance.

Files are written next to the summary.csv (private report directory):
  badge_list_<UTC>.csv, badge_dry_run_<UTC>.json, badge_issue_<UTC>.csv
Config: secrets/ninja_badge.ini (override: NINJA_BADGE_CONFIG) or the
environment variable NINJA_BADGE_API_KEY.
Duplicate-issuance ledger: secrets/ninja_badge_ledger.json.

Exit status: 0 clean, 1 failed, 2 usage or missing prerequisite.
USAGE
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
elif [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
context="$SCRIPT_DIR/../lib/workshop-context.sh"
[[ -r "$context" ]] || {
  printf 'ERROR: Missing workshop context helper.\n' >&2
  exit 2
}
# shellcheck source=../lib/workshop-context.sh
source "$context"
load_workshop_context

repository_root="$WORKSHOP_CONTEXT_REPOSITORY_ROOT"
client_dir="$repository_root/ninja-badge-client"
exporter="$SCRIPT_DIR/export_badge_list.py"
config="${NINJA_BADGE_CONFIG:-$repository_root/secrets/ninja_badge.ini}"
ledger="$repository_root/secrets/ninja_badge_ledger.json"

[[ -t 0 ]] || {
  printf 'ERROR: An interactive terminal is required. No badges were issued.\n' >&2
  exit 2
}
command -v python3 >/dev/null 2>&1 || {
  printf 'ERROR: python3 not found.\n' >&2
  exit 2
}
[[ -d "$client_dir/ninja_badge_issuer" && -r "$exporter" ]] || {
  printf 'ERROR: Badge client or export script missing.\n' >&2
  exit 2
}
if [[ ! -r "$config" && -z "${NINJA_BADGE_API_KEY:-}" ]]; then
  printf 'ERROR: No badge config at %s and NINJA_BADGE_API_KEY is not set.\n' "$config" >&2
  exit 2
fi
config_args=()
[[ -r "$config" ]] && config_args=(-c "$config")

read -r -p 'Path to the reviewed summary.csv: ' summary
[[ -f "$summary" && -r "$summary" ]] || {
  printf 'ERROR: Not a readable file: %s\n' "$summary" >&2
  exit 2
}
summary="$(cd -- "$(dirname -- "$summary")" && pwd)/$(basename -- "$summary")"
out_dir="$(dirname -- "$summary")"

read -r -p 'Badge workshop name (shown on the badge): ' workshop_name
[[ -n "$workshop_name" ]] || {
  printf 'ERROR: A workshop name is required.\n' >&2
  exit 2
}
default_date="$(date -u +%Y-%m-%d)"
read -r -p "Workshop date YYYY-MM-DD [$default_date]: " workshop_date
workshop_date="${workshop_date:-$default_date}"
read -r -p 'Only this assessment stem (empty = all): ' stem

printf '\nThe badge list is built from every row of the summary.\n'
read -r -p 'Have you verified every grade? Type REVIEWED to continue: ' answer
[[ "$answer" == REVIEWED ]] || {
  printf 'Cancelled. No badges were issued.\n'
  exit 2
}

ts="$(date -u +%Y%m%dT%H%M%SZ)"
badge_list="$out_dir/badge_list_${ts}.csv"
dry_report="$out_dir/badge_dry_run_${ts}.json"
live_report="$out_dir/badge_issue_${ts}.csv"
umask 077

export_args=(--summary "$summary" --out "$badge_list" --confirm-reviewed)
[[ -n "$stem" ]] && export_args+=(--stem "$stem")
python3 "$exporter" "${export_args[@]}" || {
  printf 'ERROR: Export refused or failed. No badges were issued.\n' >&2
  exit 1
}

python3 - "$badge_list" <<'PY'
import csv, collections, sys
with open(sys.argv[1], newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
counts = collections.Counter(r.get("status", "") for r in rows)
print(f"Badge list: {len(rows)} participants; " +
      ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
PY

issuer=(env "PYTHONPATH=$client_dir" python3 -m ninja_badge_issuer)
common=("$badge_list" -n "$workshop_name" -d "$workshop_date"
        "${config_args[@]}" --ledger "$ledger")

printf '\nDry run (nothing is issued):\n'
"${issuer[@]}" "${common[@]}" --dry-run -o "$dry_report" || {
  printf 'ERROR: Dry run failed. No badges were issued.\n' >&2
  exit 1
}

read -r -p 'Also email each participant their badge? [y/N]: ' mail
send_args=()
[[ "$mail" =~ ^[Yy]$ ]] && send_args=(--send-email)

read -r -p 'Type ISSUE to issue these badges now: ' go
[[ "$go" == ISSUE ]] || {
  printf 'Cancelled after dry run. No badges were issued.\n'
  exit 2
}

"${issuer[@]}" "${common[@]}" "${send_args[@]}" -o "$live_report" || {
  printf 'ERROR: Issuance reported problems. See %s\n' "$live_report" >&2
  exit 1
}
printf 'Done. Report: %s\n' "$live_report"
