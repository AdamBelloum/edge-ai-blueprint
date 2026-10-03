#!/usr/bin/env bash
# Cohort workflow entry point for DIGITAfrica workshop organisers.
#
# This script owns participant identity provisioning, credential issuance,
# participant-account status, and participant/workshop reset dispatch.  The
# underlying identity and reset scripts remain lower-level helpers.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSHOP_SCRIPT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
REPOSITORY_ROOT="$(cd -- "$WORKSHOP_SCRIPT_DIR/../.." && pwd)"

ACCOUNT_HELPER="$SCRIPT_DIR/create-participant-accounts.sh"
RESET_HELPER="$WORKSHOP_SCRIPT_DIR/federated-learning/reset-federated-learning-workshop.sh"
PARTICIPANT_RESET_HELPER="$SCRIPT_DIR/reset-participant-environment.sh"
WORKSHOP_CONTEXT="$WORKSHOP_SCRIPT_DIR/lib/workshop-context.sh"
COMMON_HELPER="$REPOSITORY_ROOT/scripts/lib/common.sh"

ACTION="menu"

SERVER_URL="${KEYCLOAK_SERVER_URL:-}"
REALM="${KEYCLOAK_REALM:-digitafrica}"
ADMIN_REALM="${KEYCLOAK_ADMIN_REALM:-}"
ADMIN_USER="${KEYCLOAK_ADMIN_USER:-}"
ADMIN_CLIENT_ID="${KEYCLOAK_ADMIN_CLIENT_ID:-}"
ADMIN_CLIENT_SECRET_FILE="${KEYCLOAK_ADMIN_CLIENT_SECRET_FILE:-}"

ADMIN_PASSWORD_SESSION_FILE=""
ADMIN_PASSWORD_SESSION_FILE_OWNED=false
ADMIN_PASSWORD_SESSION_VERIFIED=false

usage() {
  cat <<'USAGE'
Usage:
  cohort-workshop.sh [OPTIONS] [ACTION]

Actions:
  menu                    Show the participant-cohort workflow menu. Default.
  initialise-identities   Provision participant identities and groups only.
  issue-credentials       Issue temporary passwords and write a protected TSV export.
  status                  Show expected participant-account status.
  require-complete        Exit successfully only when the participant cohort is complete.
  reset                   Reset the active workshop cycle and participant cohort.
  reset-participants      Remove participant identities and credential exports only.

Options:
  --server-url URL
  --realm NAME
  --admin-user USER
  --admin-realm NAME
  --admin-client-id ID --admin-client-secret-file FILE
  -h, --help

The Keycloak URL is derived from the active inventory when it is not supplied.
Administrator-password authentication is requested privately only when a
service-account credential pair is not supplied.
USAGE
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 2
}

clear_admin_password_session() {
  if [[ "$ADMIN_PASSWORD_SESSION_FILE_OWNED" == true ]] &&
    [[ -n "$ADMIN_PASSWORD_SESSION_FILE" ]]; then
    rm -f -- "$ADMIN_PASSWORD_SESSION_FILE"
    unset KEYCLOAK_ADMIN_PASSWORD_FILE
  fi
  ADMIN_PASSWORD_SESSION_FILE=""
  ADMIN_PASSWORD_SESSION_FILE_OWNED=false
  ADMIN_PASSWORD_SESSION_VERIFIED=false
}

trap clear_admin_password_session EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

create_admin_password_session() {
  local password

  ADMIN_PASSWORD_SESSION_FILE="$(
    mktemp "${TMPDIR:-/tmp}/digitafrica-keycloak-admin.XXXXXX"
  )" || fail 'Could not create a protected temporary Keycloak password file.'
  ADMIN_PASSWORD_SESSION_FILE_OWNED=true
  chmod 600 "$ADMIN_PASSWORD_SESSION_FILE" ||
    fail 'Could not protect the temporary Keycloak password file.'

  if ! IFS= read -r -s \
    -p "Keycloak administrator password for ${ADMIN_USER} in realm ${ADMIN_REALM:-master}: " \
    password </dev/tty; then
    printf '\n' >&2
    clear_admin_password_session
    fail 'Could not read the Keycloak administrator password.'
  fi
  printf '\n' >&2

  if [[ -z "$password" ]]; then
    clear_admin_password_session
    return 10
  fi

  printf '%s\n' "$password" >"$ADMIN_PASSWORD_SESSION_FILE"
  unset password
  export KEYCLOAK_ADMIN_PASSWORD_FILE="$ADMIN_PASSWORD_SESSION_FILE"
}

ensure_admin_password_session() {
  local attempt status

  [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]] && return 0
  [[ "$ADMIN_PASSWORD_SESSION_VERIFIED" == true ]] && return 0

  if [[ -n "${KEYCLOAK_ADMIN_PASSWORD_FILE:-}" ]] &&
    [[ "$ADMIN_PASSWORD_SESSION_FILE_OWNED" != true ]]; then
    if "$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" --status >/dev/null; then
      ADMIN_PASSWORD_SESSION_VERIFIED=true
      return 0
    fi
    status=$?
    [[ "$status" -eq 10 ]] &&
      fail 'The supplied KEYCLOAK_ADMIN_PASSWORD_FILE was rejected by Keycloak.'
    fail 'Could not validate the supplied Keycloak administrator password file.'
  fi

  for attempt in 1 2 3; do
    if create_admin_password_session; then
      if "$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" --status >/dev/null; then
        ADMIN_PASSWORD_SESSION_VERIFIED=true
        return 0
      fi
      status=$?
    else
      status=$?
    fi

    [[ "$status" -eq 10 ]] ||
      fail 'Could not validate the Keycloak administrator password.'

    clear_admin_password_session
    if (( attempt < 3 )); then
      printf '[WARN] Keycloak authentication failed (%d/3 attempts used). Check the password and try again.\n' \
        "$attempt" >&2
    fi
  done

  fail 'Keycloak authentication failed after 3 attempts; the participant-account operation was not performed.'
}

run_account_helper() {
  local status

  ensure_admin_password_session
  if "$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" "$@"; then
    return 0
  fi

  status=$?
  if [[ "$status" -ne 10 ]] ||
    [[ "$ADMIN_PASSWORD_SESSION_FILE_OWNED" != true ]]; then
    return "$status"
  fi

  printf '[WARN] The cached Keycloak administrator password was rejected; please enter it again.\n' >&2
  clear_admin_password_session
  ensure_admin_password_session
  "$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" "$@"
}

derive_keycloak_public_url() {
  local discovered_url

  discovered_url="$(
    ansible-inventory -i "$DIGITAFRICA_INVENTORY" --list |
      python3 -c '
import json
import sys

inventory = json.load(sys.stdin)
group = sys.argv[1]
hosts = inventory.get(group, {}).get("hosts", [])

if len(hosts) != 1:
    raise SystemExit(
        f"Expected exactly one control-plane host in inventory group {group!r}; "
        f"found {len(hosts)}."
    )

host = hosts[0]
hostvars = inventory.get("_meta", {}).get("hostvars", {})
if host not in hostvars:
    raise SystemExit(f"Inventory has no host variables for control-plane host {host!r}.")

def keycloak_urls(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "keycloak_public_url" and isinstance(item, str):
                yield item
            yield from keycloak_urls(item)
    elif isinstance(value, list):
        for item in value:
            yield from keycloak_urls(item)

urls = sorted(set(keycloak_urls(hostvars[host])))
if len(urls) != 1:
    raise SystemExit(
        f"Expected exactly one keycloak_public_url for control-plane host {host!r}; "
        f"found {len(urls)}."
    )

print(urls[0])
' "$DIGITAFRICA_DEPLOYMENT_GROUP"
  )" || fail 'Could not derive the public Keycloak URL from the active workshop inventory.'

  printf '%s\n' "$discovered_url"
}

prompt_for_server_url() {
  local default_url entered_url

  if [[ -z "$SERVER_URL" ]]; then
    default_url="$(derive_keycloak_public_url)"
    if [[ "$NON_INTERACTIVE" == true ]]; then
      SERVER_URL="$default_url"
    else
      printf 'Public Keycloak URL [%s]: ' "$default_url"
      read -r entered_url
      SERVER_URL="${entered_url:-$default_url}"
    fi
  fi

  [[ "$SERVER_URL" =~ ^https:// ]] ||
    fail 'A public HTTPS Keycloak URL is required.'
}

while (($#)); do
  case "$1" in
    --server-url)
      SERVER_URL="${2:-}"
      shift 2
      ;;
    --realm)
      REALM="${2:-}"
      shift 2
      ;;
    --admin-user)
      ADMIN_USER="${2:-}"
      shift 2
      ;;
    --admin-realm)
      ADMIN_REALM="${2:-}"
      shift 2
      ;;
    --admin-client-id)
      ADMIN_CLIENT_ID="${2:-}"
      shift 2
      ;;
    --admin-client-secret-file)
      ADMIN_CLIENT_SECRET_FILE="${2:-}"
      shift 2
      ;;
    menu|initialise-identities|issue-credentials|status|require-complete|reset|reset-participants)
      [[ "$ACTION" == menu ]] || fail 'Specify one action only.'
      ACTION="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown option or action: $1"
      ;;
  esac
done

[[ -r "$WORKSHOP_CONTEXT" ]] ||
  fail "Missing workshop context helper: $WORKSHOP_CONTEXT"
# shellcheck source=../lib/workshop-context.sh
source "$WORKSHOP_CONTEXT"
load_workshop_context

[[ -r "$COMMON_HELPER" ]] ||
  fail "Missing shared helper: $COMMON_HELPER"
# shellcheck source=../../lib/common.sh
source "$COMMON_HELPER"

for helper in \
  "$ACCOUNT_HELPER" \
  "$RESET_HELPER" \
  "$PARTICIPANT_RESET_HELPER"; do
  [[ -x "$helper" ]] || fail "Missing executable helper: $helper"
done

build_account_args() {
  prompt_for_server_url
  ACCOUNT_ARGS=(--server-url "$SERVER_URL" --realm "$REALM")

  [[ -z "$ADMIN_USER" || -z "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]] ||
    fail 'Choose either --admin-user or service-account authentication, not both.'

  [[ -n "$ADMIN_REALM" ]] && ACCOUNT_ARGS+=(--admin-realm "$ADMIN_REALM")

  if [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]]; then
    [[ -n "$ADMIN_CLIENT_ID" && -n "$ADMIN_CLIENT_SECRET_FILE" ]] ||
      fail 'Both --admin-client-id and --admin-client-secret-file are required.'
    ACCOUNT_ARGS+=(
      --admin-client-id "$ADMIN_CLIENT_ID"
      --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE"
    )
  else
    ADMIN_USER="${ADMIN_USER:-admin}"
    ACCOUNT_ARGS+=(--admin-user "$ADMIN_USER")
  fi
}

participant_credentials_file() {
  local host
  host="${SERVER_URL#https://}"
  host="${host%%/*}"
  printf '%s/secrets/workshops/%s-participant-credentials.tsv\n' \
    "$REPOSITORY_ROOT" "$host"
}

check_participant_accounts() {
  local status_output status_file status

  build_account_args
  status_file="$(
    mktemp "${TMPDIR:-/tmp}/digitafrica-participant-status.XXXXXX"
  )" || fail 'Could not create a temporary participant-status file.'

  if run_account_helper --status >"$status_file"; then
    status_output="$(<"$status_file")"
  else
    status=$?
    rm -f -- "$status_file"
    return "$status"
  fi
  rm -f -- "$status_file"

  printf '%s\n' "$status_output"

  PARTICIPANT_ACCOUNT_STATUS="$(
    sed -n 's/^participant_account_status=\([^ ]*\).*/\1/p' <<<"$status_output"
  )"

  case "$PARTICIPANT_ACCOUNT_STATUS" in
    absent|complete|inconsistent) ;;
    *) fail 'Could not determine participant-account status.' ;;
  esac
}

run_initialise_identities() {
  check_participant_accounts

  case "$PARTICIPANT_ACCOUNT_STATUS" in
    absent)
      printf '%s\n' \
        'Provisioning participant identities and matching groups without passwords.' \
        'Participants cannot log in until credentials are issued explicitly.'
      run_account_helper --provision-only
      ;;
    complete)
      printf '%s\n' \
        'Participant identities and groups are already complete.' \
        'No change was made.'
      ;;
    inconsistent)
      fail 'Participant accounts are inconsistent. Repair or reset participant identities before proceeding.'
      ;;
  esac
}

run_issue_credentials() {
  local credentials_output

  check_participant_accounts
  [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
    fail 'Provision complete participant identities and groups before issuing credentials.'


  credentials_output="$(participant_credentials_file)"
  run_account_helper \
    --reset-all-passwords \
    --credentials-output "$credentials_output"

  printf 'Protected participant credentials are available locally (mode 0600): %s\n' \
    "$credentials_output"
}

run_reset() {
  build_account_args
  "$RESET_HELPER" "${ACCOUNT_ARGS[@]}"
}

run_reset_participants() {
  build_account_args
  "$PARTICIPANT_RESET_HELPER" "${ACCOUNT_ARGS[@]}"
}

run_initialisation_menu() {
  local choice

  while true; do
    printf '\nManage participant cohort\n\n'
    printf '  1) Provision participant identities and groups\n'
    printf '  2) Issue and export participant credentials\n'
    printf '  3) Show participant-account status\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) run_initialise_identities ;;
      2) run_issue_credentials ;;
      3) check_participant_accounts ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, or 3.\n' >&2 ;;
    esac
  done
}

run_reset_menu() {
  local choice

  while true; do
    printf '\nReset active workshop cycle\n\n'
    printf '  1) Reset active workshop and participant cohort\n'
    printf '  2) Remove participant identities and credential exports only\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) run_reset ;;
      2) run_reset_participants ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, or 2.\n' >&2 ;;
    esac
  done
}

case "$ACTION" in
  menu)
    [[ -t 0 ]] || fail 'Use an explicit action in a non-interactive shell.'
    while true; do
      printf '\nParticipant cohort\n\n'
      printf '  1) Manage participant identities and credentials\n'
      printf '  2) Reset active workshop cycle\n'
      printf '  0) Back\n\n'
      printf 'Selection: '
      read -r choice
      case "$choice" in
        1) run_initialisation_menu ;;
        2) run_reset_menu ;;
        0) exit 0 ;;
        *) printf 'Choose 0, 1, or 2.\n' >&2 ;;
      esac
    done
    ;;
  initialise-identities) run_initialise_identities ;;
  issue-credentials) run_issue_credentials ;;
  status) check_participant_accounts ;;
  require-complete)
    check_participant_accounts
    [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
      fail 'Provision complete participant identities and groups before continuing.'
    ;;
  reset) run_reset ;;
  reset-participants) run_reset_participants ;;
esac
