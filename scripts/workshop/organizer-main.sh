#!/usr/bin/env bash
# Single organiser-facing entry point for DIGITAfrica FL workshops.
# Internal helpers remain separate and are called only from this menu.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREPARE_HELPER="$SCRIPT_DIR/organizer_wizard.sh"
RESET_HELPER="$SCRIPT_DIR/reset-new-workshop.sh"
WORKSHOP_CONTEXT="$SCRIPT_DIR/workshop-context.sh"

NON_INTERACTIVE=false
ACTION="menu"
MODE=""
SERVER_URL="${KEYCLOAK_SERVER_URL:-}"
REALM="${KEYCLOAK_REALM:-digitafrica}"
CREDENTIALS_OUTPUT=""
ADMIN_REALM="${KEYCLOAK_ADMIN_REALM:-}"
ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
ADMIN_CLIENT_ID="${KEYCLOAK_ADMIN_CLIENT_ID:-}"
ADMIN_CLIENT_SECRET_FILE="${KEYCLOAK_ADMIN_CLIENT_SECRET_FILE:-}"

usage() {
  cat <<'EOF'
Usage:
  organizer-main.sh [OPTIONS] [menu|prepare|reset beginner|advanced]

The single organiser entry point for preparation and fresh-cohort reset.

Shared options:
  --non-interactive        Do not offer to start the Flower server during prepare.

Reset options (needed only for reset):
  --server-url URL         Public Keycloak base URL (or KEYCLOAK_SERVER_URL).
  --realm NAME             Participant realm. Default: digitafrica.
  --credentials-output FILE
                           New mode-0600 TSV output path.
  --admin-user USER        Keycloak administrator. Default: admin.
  --admin-realm NAME       Administrator realm, if non-default.
  --admin-client-id ID --admin-client-secret-file FILE
                           Use service-account authentication instead of admin user.

Actions:
  menu                     Show the organiser menu. Default.
  prepare                  Run the existing workshop readiness/preparation wizard.
  reset beginner|advanced  Reset participant credentials and initialise a fresh cohort.

For administrator-password authentication, the reset helper prompts privately,
or reads KEYCLOAK_ADMIN_PASSWORD_FILE when that protected file is configured.
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }

while (($#)); do
  case "$1" in
    --non-interactive) NON_INTERACTIVE=true; shift ;;
    --server-url) SERVER_URL="${2:-}"; shift 2 ;;
    --realm) REALM="${2:-}"; shift 2 ;;
    --credentials-output) CREDENTIALS_OUTPUT="${2:-}"; shift 2 ;;
    --admin-user) ADMIN_USER="${2:-}"; shift 2 ;;
    --admin-realm) ADMIN_REALM="${2:-}"; shift 2 ;;
    --admin-client-id) ADMIN_CLIENT_ID="${2:-}"; shift 2 ;;
    --admin-client-secret-file) ADMIN_CLIENT_SECRET_FILE="${2:-}"; shift 2 ;;
    menu|prepare)
      [[ "$ACTION" == menu ]] || fail 'Specify one action only.'
      ACTION="$1"; shift
      ;;
    reset)
      [[ "$ACTION" == menu ]] || fail 'Specify one action only.'
      MODE="${2:-}"
      [[ "$MODE" == beginner || "$MODE" == advanced ]] || fail 'reset requires beginner or advanced.'
      ACTION="reset"; shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option or action: $1" ;;
  esac
done

[[ -r "$WORKSHOP_CONTEXT" ]] || fail "Missing workshop context helper: $WORKSHOP_CONTEXT"
# shellcheck source=workshop-context.sh
source "$WORKSHOP_CONTEXT"
load_workshop_context

[[ -x "$PREPARE_HELPER" ]] || fail "Missing prepare helper: $PREPARE_HELPER"
[[ -x "$RESET_HELPER" ]] || fail "Missing reset helper: $RESET_HELPER"

common_args=()

run_prepare() {
  local -a args=("${common_args[@]}")
  "$NON_INTERACTIVE" && args+=(--non-interactive)
  exec "$PREPARE_HELPER" "${args[@]}"
}

run_reset() {
  local -a args=("${common_args[@]}")

  [[ "$SERVER_URL" =~ ^https:// ]] || fail 'reset requires --server-url HTTPS_URL or KEYCLOAK_SERVER_URL.'
  [[ -n "$CREDENTIALS_OUTPUT" ]] || \
    CREDENTIALS_OUTPUT="$HOME/.local/share/digitafrica/workshop-reset-$(date +%Y%m%dT%H%M%S).tsv"

  args+=(--server-url "$SERVER_URL" --realm "$REALM" --credentials-output "$CREDENTIALS_OUTPUT")
  [[ -n "$ADMIN_REALM" ]] && args+=(--admin-realm "$ADMIN_REALM")

  if [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]]; then
    [[ -n "$ADMIN_CLIENT_ID" && -n "$ADMIN_CLIENT_SECRET_FILE" ]] || \
      fail 'Both --admin-client-id and --admin-client-secret-file are required.'
    args+=(--admin-client-id "$ADMIN_CLIENT_ID" --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE")
  else
    [[ -n "$ADMIN_USER" ]] || fail 'reset requires --admin-user or service-account authentication.'
    args+=(--admin-user "$ADMIN_USER")
  fi

  exec "$RESET_HELPER" "${args[@]}" "$MODE"
}

if [[ "$ACTION" == prepare ]]; then
  run_prepare
elif [[ "$ACTION" == reset ]]; then
  run_reset
fi

[[ -t 0 ]] || fail 'Use an explicit action in a non-interactive shell: prepare or reset beginner|advanced.'
printf '\nDIGITAfrica workshop organiser\n\n'
printf '  1) Prepare new workshop\n'
printf '  2) Reset for new workshop\n'
printf '  0) Exit\n\n'
printf 'Selection: '
read -r choice

case "$choice" in
  1) run_prepare ;;
  2)
    printf 'New workshop type (beginner/advanced): '
    read -r MODE
    [[ "$MODE" == beginner || "$MODE" == advanced ]] || fail 'Choose beginner or advanced.'
    if [[ -z "$SERVER_URL" ]]; then
      printf 'Public Keycloak URL (for example https://host/keycloak): '
      read -r SERVER_URL
    fi
    run_reset
    ;;
  0) exit 0 ;;
  *) fail 'Choose 0, 1, or 2.' ;;
esac

