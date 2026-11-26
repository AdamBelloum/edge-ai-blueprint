#!/usr/bin/env bash
# Organiser tool: send participant thank-you emails with badge links.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: send-thanks.sh

Interactively send thank-you emails from a reviewed badge report CSV
(badge_issue_<UTC>.csv from create-badges.sh). Modes: preview, drafts,
test mail to yourself, or send. Only issued rows with a badge link and
thanks_sent not yet 'yes' are emailed; the report is saved after each email.

Config: secrets/mail.ini (override: NINJA_MAIL_CONFIG), or the environment
variable NINJA_SMTP_PASSWORD. Run on the machine that holds the mail config.

Exit status: 0 clean, 1 failed or unknown sends, 2 usage or missing prerequisite.
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
mail_config="${NINJA_MAIL_CONFIG:-$repository_root/secrets/mail.ini}"

[[ -t 0 ]] || {
  printf 'ERROR: An interactive terminal is required. No emails were sent.\n' >&2
  exit 2
}
command -v python3 >/dev/null 2>&1 || {
  printf 'ERROR: python3 not found.\n' >&2
  exit 2
}
[[ -d "$client_dir/ninja_badge_issuer" ]] || {
  printf 'ERROR: Badge client missing: %s\n' "$client_dir" >&2
  exit 2
}

if [[ ! -r "$mail_config" ]]; then
  {
    printf 'ERROR: No mail config at %s. No emails were sent.\n' "$mail_config"
    printf 'Create it from the example and restrict it:\n'
    printf '  mkdir -p %s\n' "$(dirname -- "$mail_config")"
    printf '  cp %s/mail.ini.example %s\n' "$client_dir" "$mail_config"
    printf '  chmod 600 %s\n' "$mail_config"
    printf 'Then edit the SMTP host, port, sender and signature. Prefer the\n'
    printf 'NINJA_SMTP_PASSWORD environment variable over a password in the file.\n'
  } >&2
  exit 2
fi
mail_args=(--mail-config "$mail_config")

read -r -p 'Path to the badge report CSV (badge_issue_*.csv): ' report
[[ -f "$report" && -r "$report" && "$report" == *.csv ]] || {
  printf 'ERROR: Not a readable CSV file: %s\n' "$report" >&2
  exit 2
}
report="$(cd -- "$(dirname -- "$report")" && pwd)/$(basename -- "$report")"
out_dir="$(dirname -- "$report")"
ts="$(date -u +%Y%m%dT%H%M%SZ)"

read -r -p 'Thank-you template file (empty = built-in text): ' template
template_args=()
if [[ -n "$template" ]]; then
  [[ -r "$template" ]] || {
    printf 'ERROR: Template not readable: %s\n' "$template" >&2
    exit 2
  }
  template_args=(--thanks-template "$template")
fi

read -r -p 'Email addresses to skip, comma-separated (empty = none): ' skip_list
skip_args=()
IFS=',' read -r -a skips <<< "$skip_list"
for s in ${skips[@]+"${skips[@]}"}; do
  s="$(printf '%s' "$s" | tr -d '[:space:]')"
  [[ -n "$s" ]] && skip_args+=(--skip "$s")
done

printf '\nModes:\n'
printf '  1) Preview the first message (no email sent, report unchanged)\n'
printf '  2) Write .eml drafts for your mail client (no email sent, report unchanged)\n'
printf '  3) Send one [TEST] message to yourself (report unchanged)\n'
printf '  4) Send thank-you emails to participants (report updated)\n'
read -r -p 'Choose mode [1-4]: ' mode

mode_args=()
case "$mode" in
  1) mode_args=(--dry-run) ;;
  2)
    drafts="$out_dir/thanks_drafts_${ts}"
    mode_args=(--eml-dir "$drafts")
    ;;
  3)
    read -r -p 'Your address for the test message: ' test_addr
    [[ "$test_addr" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || {
      printf 'ERROR: Not a valid address: %s\n' "$test_addr" >&2
      exit 2
    }
    mode_args=(--test-to "$test_addr")
    ;;
  4)
    printf '\nThis emails every pending participant. Failed and unknown rows stay retryable.\n'
    read -r -p 'Type SEND to continue: ' go
    [[ "$go" == SEND ]] || {
      printf 'Cancelled. No emails were sent.\n'
      exit 2
    }
    mode_args=(--yes)
    ;;
  *)
    printf 'ERROR: Choose 1, 2, 3 or 4.\n' >&2
    exit 2
    ;;
esac

set +e
PYTHONPATH="$client_dir" python3 -m ninja_badge_issuer --send-thanks "$report" \
  ${mail_args[@]+"${mail_args[@]}"} \
  ${template_args[@]+"${template_args[@]}"} \
  ${skip_args[@]+"${skip_args[@]}"} \
  "${mode_args[@]}"
rc=$?
set -e

case "$rc" in
  0) printf 'Done.\n' ;;
  1) printf 'Some emails failed or are unknown. Check the thanks_sent column in %s; rerunning retries only "no" rows.\n' "$report" >&2
     exit 1 ;;
  *) printf 'Thank-you step did not complete (exit code %s). See messages above.\n' "$rc" >&2
     exit 2 ;;
esac
