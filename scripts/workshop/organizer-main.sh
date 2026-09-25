#!/usr/bin/env bash
# Single organiser-facing entry point for DIGITAfrica FL workshops.
# Internal helpers remain separate and are called only from this menu.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREPARE_HELPER="$SCRIPT_DIR/organizer_wizard.sh"
COHORT_HELPER="$SCRIPT_DIR/fl-workshop.sh"
RESET_HELPER="$SCRIPT_DIR/reset-new-workshop.sh"
WORKSHOP_CONTEXT="$SCRIPT_DIR/workshop-context.sh"

NON_INTERACTIVE=false
CONFIRM_COHORT_RESET=false
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

The single organiser entry point for workshop preparation and fresh-cohort reset.

Preparation options:
  --mode beginner|advanced  Workshop level. Prompted for interactive preparation;
                            required with --non-interactive prepare.
  --non-interactive         Run preparation without prompts. Requires --mode and
                            --confirm-cohort-reset.
  --confirm-cohort-reset    Explicitly authorise deletion of participant JupyterHub
                            workspaces during non-interactive preparation.

Prepare validates readiness first, then initialises the selected tutorial mode and
fresh participant workspaces. It never starts Flower before cohort initialisation.

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
  prepare                  Validate readiness and initialise a beginner or advanced cohort.
  reset beginner|advanced  Reset participant credentials and initialise a fresh cohort.

For administrator-password authentication, the reset helper prompts privately,
or reads KEYCLOAK_ADMIN_PASSWORD_FILE when that protected file is configured.
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 2; }

while (($#)); do
  case "$1" in
    --non-interactive) NON_INTERACTIVE=true; shift ;;
    --confirm-cohort-reset) CONFIRM_COHORT_RESET=true; shift ;;
    --mode)
      MODE="${2:-}"
      [[ "$MODE" == beginner || "$MODE" == advanced ]] ||
        fail '--mode must be beginner or advanced.'
      shift 2
      ;;
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

case "$ACTION" in
  prepare)
    if "$NON_INTERACTIVE"; then
      [[ -n "$MODE" ]] || fail '--non-interactive prepare requires --mode beginner|advanced.'
      "$CONFIRM_COHORT_RESET" || \
        fail '--non-interactive prepare requires --confirm-cohort-reset before participant workspaces may be deleted.'
    elif "$CONFIRM_COHORT_RESET"; then
      fail '--confirm-cohort-reset is valid only with --non-interactive prepare.'
    fi
    ;;
  reset)
    "$CONFIRM_COHORT_RESET" && fail '--confirm-cohort-reset is valid only with --non-interactive prepare.'
    ;;
  menu)
    [[ -z "$MODE" ]] || fail '--mode requires the prepare action.'
    "$CONFIRM_COHORT_RESET" && fail '--confirm-cohort-reset requires --non-interactive prepare.'
    ;;
esac

[[ -r "$WORKSHOP_CONTEXT" ]] || fail "Missing workshop context helper: $WORKSHOP_CONTEXT"
# shellcheck source=workshop-context.sh
source "$WORKSHOP_CONTEXT"
load_workshop_context

[[ -x "$PREPARE_HELPER" ]] || fail "Missing prepare helper: $PREPARE_HELPER"
[[ -x "$COHORT_HELPER" ]] || fail "Missing cohort helper: $COHORT_HELPER"
[[ -x "$RESET_HELPER" ]] || fail "Missing reset helper: $RESET_HELPER"

common_args=()

select_prepare_mode() {
  if [[ -z "$MODE" ]]; then
    [[ -t 0 ]] || fail 'Non-interactive prepare requires --mode beginner|advanced.'
    printf 'Workshop type (beginner/advanced): '
    read -r MODE
  fi
  [[ "$MODE" == beginner || "$MODE" == advanced ]] ||
    fail 'Choose beginner or advanced.'
}

run_prepare() {
  local -a readiness_args=("${common_args[@]}" --non-interactive)
  local -a cohort_args=(new-cohort)

  select_prepare_mode

  # A participant server started before cohort initialisation would make the
  # workspace-reset safety check refuse preparation. Flower is started later.
  "$PREPARE_HELPER" "${readiness_args[@]}"

  cohort_args+=("$MODE")
  "$NON_INTERACTIVE" && cohort_args+=(--yes)
  "$COHORT_HELPER" "${cohort_args[@]}"
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
  exit 0
elif [[ "$ACTION" == reset ]]; then
  run_reset
  exit 0
fi

[[ -t 0 ]] || fail 'Use an explicit action in a non-interactive shell: prepare or reset beginner|advanced.'
printf '\nDIGITAfrica workshop organiser\n\n'
printf '  1) Prepare and initialise a beginner or advanced workshop\n'
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

