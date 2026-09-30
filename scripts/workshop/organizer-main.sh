#!/usr/bin/env bash
# Single organiser-facing entry point for DIGITAfrica FL workshops.
# Internal helpers remain separate and are called only from this menu.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PREPARE_HELPER="$SCRIPT_DIR/organizer_wizard.sh"
COHORT_HELPER="$SCRIPT_DIR/fl-workshop.sh"
ACCOUNT_HELPER="$SCRIPT_DIR/create-participant-accounts.sh"
RESET_HELPER="$SCRIPT_DIR/reset-new-workshop.sh"
FLOWER_MANAGER="$SCRIPT_DIR/manage-flower-server.sh"
WORKSHOP_CONTEXT="$SCRIPT_DIR/workshop-context.sh"

NON_INTERACTIVE=false
CONFIRM_COHORT_RESET=false
ACTION="menu"
MODE=""
SERVER_URL="${KEYCLOAK_SERVER_URL:-}"
REALM="${KEYCLOAK_REALM:-digitafrica}"
ADMIN_REALM="${KEYCLOAK_ADMIN_REALM:-}"
ADMIN_USER="${KEYCLOAK_ADMIN_USER:-}"
ADMIN_CLIENT_ID="${KEYCLOAK_ADMIN_CLIENT_ID:-}"
ADMIN_CLIENT_SECRET_FILE="${KEYCLOAK_ADMIN_CLIENT_SECRET_FILE:-}"

usage() {
  cat <<'EOF'
Usage:
  organizer-main.sh [OPTIONS] [menu|prepare|reset|status|release-solutions|flower]

The single organiser entry point for workshop preparation, solution release, and participant cleanup.

Preparation options:
  --mode beginner|advanced  Workshop level. Prompted for interactive preparation;
                            required with --non-interactive prepare.
  --non-interactive         Run preparation without prompts. Requires --mode and
                            --confirm-cohort-reset.
  --confirm-cohort-reset    Explicitly authorise deletion of participant JupyterHub
                            workspaces during non-interactive preparation.

Prepare checks that no active participant identities exist, validates readiness,
initialises the selected tutorial mode and fresh workspaces, then creates one
Keycloak identity per active worker. It never starts Flower before cohort initialisation.

Keycloak options (required for prepare, reset, and status):
  --server-url URL         Public Keycloak base URL (or KEYCLOAK_SERVER_URL).
  --realm NAME             Participant realm. Default: digitafrica.
  --admin-user USER        Keycloak administrator. Default: admin.
  --admin-realm NAME       Administrator realm, if non-default.
  --admin-client-id ID --admin-client-secret-file FILE
                           Use service-account authentication instead of admin user.

Actions:
  menu                     Show the organiser menu. Default.
  prepare                  Validate readiness and initialise a beginner or advanced cohort.
  reset                    Delete participant workspaces, Keycloak users, and groups.
  status                   Read-only status of expected participant identities.
  release-solutions        Release reference solutions for an advanced workshop.
  flower                    Open the interactive Flower server lifecycle manager.

Interactive menu reset also offers to remove the local participant credential
export after remote participant cleanup. The explicit reset action does not
offer this local-file prompt.

Reset does not change tutorial mode or create participant accounts. For
administrator-password authentication, the reset helper prompts privately,
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
    --admin-user) ADMIN_USER="${2:-}"; shift 2 ;;
    --admin-realm) ADMIN_REALM="${2:-}"; shift 2 ;;
    --admin-client-id) ADMIN_CLIENT_ID="${2:-}"; shift 2 ;;
    --admin-client-secret-file) ADMIN_CLIENT_SECRET_FILE="${2:-}"; shift 2 ;;
    menu|prepare|status|release-solutions|flower)
      [[ "$ACTION" == menu ]] || fail 'Specify one action only.'
      ACTION="$1"; shift
      ;;
    reset)
      [[ "$ACTION" == menu ]] || fail 'Specify one action only.'
      ACTION="reset"; shift
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
  reset|status|release-solutions|flower)
    [[ -z "$MODE" ]] || fail '--mode is valid only with the prepare action.'
    "$NON_INTERACTIVE" && fail '--non-interactive is valid only with the prepare action.'
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
[[ -x "$ACCOUNT_HELPER" ]] || fail "Missing account helper: $ACCOUNT_HELPER"
[[ -x "$RESET_HELPER" ]] || fail "Missing reset helper: $RESET_HELPER"
[[ -x "$FLOWER_MANAGER" ]] || fail "Missing executable Flower manager: $FLOWER_MANAGER"

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

build_account_args() {
  ACCOUNT_ARGS=(--server-url "$SERVER_URL" --realm "$REALM")

  [[ "$SERVER_URL" =~ ^https:// ]] ||     fail 'prepare requires --server-url HTTPS_URL or KEYCLOAK_SERVER_URL.'

  [[ -z "$ADMIN_USER" || -z "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]] ||     fail 'Choose either --admin-user or service-account authentication, not both.'

  [[ -n "$ADMIN_REALM" ]] && ACCOUNT_ARGS+=(--admin-realm "$ADMIN_REALM")
  if [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]]; then
    [[ -n "$ADMIN_CLIENT_ID" && -n "$ADMIN_CLIENT_SECRET_FILE" ]] ||       fail 'Both --admin-client-id and --admin-client-secret-file are required.'
    ACCOUNT_ARGS+=(--admin-client-id "$ADMIN_CLIENT_ID" --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE")
  else
    ADMIN_USER="${ADMIN_USER:-admin}"
    ACCOUNT_ARGS+=(--admin-user "$ADMIN_USER")
  fi
}

participant_credentials_file() {
  local host
  host="${SERVER_URL#https://}"
  host="${host%%/*}"
  printf '%s/secrets/workshops/%s-%s-credentials.tsv
' "$REPOSITORY_ROOT" "$host" "$MODE"
}

check_participant_accounts() {
  local status_output

  build_account_args
  status_output="$("$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" --status)"
  printf '%s
' "$status_output"
  PARTICIPANT_ACCOUNT_STATUS="$(sed -n 's/^participant_account_status=\([^ ]*\).*/\1/p' <<<"$status_output")"

  case "$PARTICIPANT_ACCOUNT_STATUS" in
    absent|complete|inconsistent) ;;
    *) fail 'Could not determine participant-account status from the Keycloak check.' ;;
  esac
}

run_prepare() {
  local -a pre_reconciliation_readiness_args=(
    "${common_args[@]}" --non-interactive --skip-participant-mapping
  )
  local -a post_reconciliation_readiness_args=(
    "${common_args[@]}" --non-interactive
  )
  local -a cohort_args=(new-cohort)
  local credentials_output

  select_prepare_mode
  check_participant_accounts

  case "$PARTICIPANT_ACCOUNT_STATUS" in
    absent) ;;
    complete)
      fail 'Participant accounts already exist. Run the reset action for a new workshop cycle, or use the dedicated reconfiguration workflow.'
      ;;
    inconsistent)
      fail 'Participant accounts are incomplete or have incorrect group membership. Do not reset workspaces; repair the Keycloak participant state first.'
      ;;
  esac

  # A prior experiment must not survive into a newly initialised cohort.
  # The fresh server is started only after all cohort and identity steps succeed.
  printf '%s\n' 'Stopping any prior organiser-controlled Flower server...'
  "$FLOWER_MANAGER" stop

  "$PREPARE_HELPER" "${pre_reconciliation_readiness_args[@]}"

  cohort_args+=("$MODE")
  "$NON_INTERACTIVE" && cohort_args+=(--yes)
  if ! "$COHORT_HELPER" "${cohort_args[@]}"; then
    fail 'Cohort initialisation did not complete; participant accounts were not created.'
  fi

  # new-cohort has reset selected workspaces, rendered the current inventory
  # mapping, upgraded JupyterHub, and waited for rollout. Validate that final
  # mapping before identity accounts are created or credentials are exported.
  "$PREPARE_HELPER" "${post_reconciliation_readiness_args[@]}"

  credentials_output="$(participant_credentials_file)"
  "$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" --credentials-output "$credentials_output"
  printf 'Participant credentials are available locally (mode 0600): %s
' "$credentials_output"

  printf '%s\n' 'Starting a fresh Flower server for the newly initialised cohort...'
  "$FLOWER_MANAGER" restart --defaults
  printf '%s\n' 'Flower server is ready; participants may now begin the guided client notebook.'
}

run_flower_manager_menu() {
  local choice rounds min_clients

  printf '\nFlower server lifecycle\n\n'
  printf '  1) Show status and effective parameters\n'
  printf '  2) Start the server using current parameters\n'
  printf '  3) Stop the server\n'
  printf '  4) Stop and start a fresh server using current parameters\n'
  printf '  5) Update rounds and required-client parameters (server remains stopped)\n'
  printf '  6) Show recent Flower server logs\n'
  printf '  0) Return to organiser menu\n\n'
  printf 'Selection: '
  read -r choice

  case "$choice" in
    1) "$FLOWER_MANAGER" status ;;
    2) "$FLOWER_MANAGER" start ;;
    3) "$FLOWER_MANAGER" stop ;;
    4) "$FLOWER_MANAGER" restart ;;
    5)
      printf 'Number of federated-training rounds: '
      read -r rounds
      printf 'Required participating clients in every round: '
      read -r min_clients
      "$FLOWER_MANAGER" configure --rounds "$rounds" --min-clients "$min_clients"
      ;;
    6) "$FLOWER_MANAGER" logs ;;
    0) return 0 ;;
    *) fail 'Choose 0, 1, 2, 3, 4, 5, or 6.' ;;
  esac
}

run_reset() {
  local -a args=("${common_args[@]}")

  [[ "$SERVER_URL" =~ ^https:// ]] || fail 'reset requires --server-url HTTPS_URL or KEYCLOAK_SERVER_URL.'
  args+=(--server-url "$SERVER_URL" --realm "$REALM")
  [[ -n "$ADMIN_REALM" ]] && args+=(--admin-realm "$ADMIN_REALM")

  if [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]]; then
    [[ -n "$ADMIN_CLIENT_ID" && -n "$ADMIN_CLIENT_SECRET_FILE" ]] || \
      fail 'Both --admin-client-id and --admin-client-secret-file are required.'
    args+=(--admin-client-id "$ADMIN_CLIENT_ID" --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE")
  else
    ADMIN_USER="${ADMIN_USER:-admin}"
    args+=(--admin-user "$ADMIN_USER")
  fi

  "$RESET_HELPER" "${args[@]}"
}

if [[ "$ACTION" == prepare ]]; then
  run_prepare
  exit 0
elif [[ "$ACTION" == reset ]]; then
  run_reset
  exit 0
elif [[ "$ACTION" == status ]]; then
  check_participant_accounts
  exit 0
elif [[ "$ACTION" == release-solutions ]]; then
  "$COHORT_HELPER" release-solutions
  exit 0
elif [[ "$ACTION" == flower ]]; then
  [[ -t 0 ]] || fail 'The flower action requires an interactive terminal.'
  run_flower_manager_menu
  exit 0
fi

[[ -t 0 ]] || fail 'Use an explicit action in a non-interactive shell: prepare, reset, or release-solutions.'
printf '\nDIGITAfrica workshop organiser\n\n'
printf '  1) Prepare and initialise a beginner or advanced workshop\n'
printf '  2) Delete participant workspaces and Keycloak identities\n'
printf '  3) Release reference solutions for advanced workshop\n'
printf '  4) Manage the Flower server (status, start, stop, parameters, logs)\n'
printf '  0) Exit\n\n'
printf 'Selection: '
read -r choice

case "$choice" in
  1)
    if [[ -z "$SERVER_URL" ]]; then
      printf 'Public Keycloak URL (for example https://host/keycloak): '
      read -r SERVER_URL
    fi
    run_prepare
    ;;
  2)
    if [[ -z "$SERVER_URL" ]]; then
      printf 'Public Keycloak URL (for example https://host/keycloak): '
      read -r SERVER_URL
    fi
    run_reset

    credential_host="${SERVER_URL#https://}"
    credential_host="${credential_host%%/*}"
    credential_files=()
    for credential_mode in beginner advanced; do
      credential_file="${REPOSITORY_ROOT}/secrets/workshops/${credential_host}-${credential_mode}-credentials.tsv"
      [[ -f "$credential_file" ]] && credential_files+=("$credential_file")
    done

    if ((${#credential_files[@]})); then
      printf 'Local participant credential exports:\n'
      printf '  %s\n' "${credential_files[@]}"
      read -r -p "Remove these local participant credential exports? [y/N]: " remove_credentials
      if [[ "$remove_credentials" == [Yy] ]]; then
        rm -f -- "${credential_files[@]}"
        printf 'Removed local participant credential export(s).\n'
      else
        printf 'Retained local participant credential export(s).\n'
      fi
    fi

    exec "$0"
    ;;
  3)
    "$COHORT_HELPER" release-solutions
    exec "$0"
    ;;
  4)
    run_flower_manager_menu
    exec "$0"
    ;;
  0) exit 0 ;;
  *) fail 'Choose 0, 1, 2, 3, or 4.' ;;
esac

