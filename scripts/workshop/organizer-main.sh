#!/usr/bin/env bash
# Hierarchical organiser-facing entry point for DIGITAfrica workshops.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

PREPARE_HELPER="$SCRIPT_DIR/federated-learning/organizer_wizard.sh"
COHORT_HELPER="$SCRIPT_DIR/federated-learning/fl-workshop.sh"
ACCOUNT_HELPER="$SCRIPT_DIR/identity/create-participant-accounts.sh"
RESET_HELPER="$SCRIPT_DIR/federated-learning/reset-federated-learning-workshop.sh"
PARTICIPANT_RESET_HELPER="$SCRIPT_DIR/identity/reset-participant-environment.sh"
FLOWER_MANAGER="$SCRIPT_DIR/federated-learning/manage-flower-server.sh"
MODULE1_HELPER="$SCRIPT_DIR/introduction-to-ai/module1.sh"
MODULE2_HELPER="$SCRIPT_DIR/introduction-to-ai/module2.sh"
APPLICATION_RECONCILIATION_HELPER="$SCRIPT_DIR/reconcile-workshop-applications.sh"
WORKSHOP_CONTEXT="$SCRIPT_DIR/lib/workshop-context.sh"
COMMON_HELPER="$REPOSITORY_ROOT/scripts/lib/common.sh"

ACTION="menu"
MODE=""
NON_INTERACTIVE=false
CONFIRM_COHORT_RESET=false

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
  organizer-main.sh [OPTIONS] [ACTION]

Actions:
  menu                    Show the hierarchical organiser menu. Default.
  initialise-identities   Provision participant identities and groups only.
  issue-credentials       Issue temporary passwords and write a protected TSV export.
  status                  Show expected participant-account status.
  module1-publish         Publish Module 1 and activate Introduction to AI Module 1 for new spawns.
  module1-check           Check Introduction to AI Module 1 publication readiness.
  module2-publish         Activate Introduction to AI Module 2 beginner and advanced tracks.
  module2-check           Check Introduction to AI Module 2 activation readiness.
  module2-release-solutions
                          Release Introduction to AI Module 2 solutions after the workshop.
  reconcile-applications  Reconcile added or updated workshop applications and JupyterHub.
  fl-prepare              Initialise the selected Federated Learning workshop mode.
  reset                   Reset the active workshop cycle and participant cohort.
  reset-participants      Remove participant identities and credential exports only.
  release-solutions       Release advanced Federated Learning reference solutions.
  flower                  Open the Flower lifecycle manager.

Options:
  --mode beginner|advanced
                           Required for non-interactive fl-prepare.
  --non-interactive       Valid only with fl-prepare.
  --confirm-cohort-reset  Required with non-interactive fl-prepare.
  --server-url URL        Public Keycloak base URL, or KEYCLOAK_SERVER_URL.
  --realm NAME            Participant Keycloak realm. Default: digitafrica.
  --admin-user USER       Keycloak administrator. Default: admin.
  --admin-realm NAME      Keycloak administrator realm, if non-default.
  --admin-client-id ID --admin-client-secret-file FILE
                           Service-account authentication instead of admin user.

Workflow:
  1. Provision participant identities and groups.
  2. Prepare the selected workshop after the participant cohort exists.
  3. Issue/export shared participant credentials when they are ready to distribute.
  4. Distribute credentials to participants.

Federated Learning preparation is independent from Introduction to AI.
After pulling or adding a workshop or module, run reconcile-applications before publishing it.
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
    --non-interactive)
      NON_INTERACTIVE=true
      shift
      ;;
    --confirm-cohort-reset)
      CONFIRM_COHORT_RESET=true
      shift
      ;;
    --mode)
      MODE="${2:-}"
      [[ "$MODE" == beginner || "$MODE" == advanced ]] ||
        fail '--mode must be beginner or advanced.'
      shift 2
      ;;
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
    menu|initialise-identities|issue-credentials|status|module1-publish|module1-check|module2-publish|module2-check|module2-release-solutions|reconcile-applications|fl-prepare|reset|reset-participants|release-solutions|flower)
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

case "$ACTION" in
  fl-prepare)
    if "$NON_INTERACTIVE"; then
      [[ -n "$MODE" ]] ||
        fail '--non-interactive fl-prepare requires --mode beginner|advanced.'
      "$CONFIRM_COHORT_RESET" ||
        fail '--non-interactive fl-prepare requires --confirm-cohort-reset.'
    elif "$CONFIRM_COHORT_RESET"; then
      fail '--confirm-cohort-reset is valid only with --non-interactive fl-prepare.'
    fi
    ;;
  *)
    [[ -z "$MODE" ]] || fail '--mode is valid only with fl-prepare.'
    "$NON_INTERACTIVE" && fail '--non-interactive is valid only with fl-prepare.'
    "$CONFIRM_COHORT_RESET" &&
      fail '--confirm-cohort-reset is valid only with --non-interactive fl-prepare.'
    ;;
esac

[[ -r "$WORKSHOP_CONTEXT" ]] ||
  fail "Missing workshop context helper: $WORKSHOP_CONTEXT"
# shellcheck source=lib/workshop-context.sh
source "$WORKSHOP_CONTEXT"
load_workshop_context

[[ -r "$COMMON_HELPER" ]] ||
  fail "Missing shared helper: $COMMON_HELPER"
# shellcheck source=../lib/common.sh
source "$COMMON_HELPER"

for helper in \
  "$PREPARE_HELPER" \
  "$COHORT_HELPER" \
  "$ACCOUNT_HELPER" \
  "$RESET_HELPER" \
  "$PARTICIPANT_RESET_HELPER" \
  "$FLOWER_MANAGER" \
  "$MODULE1_HELPER" \
  "$MODULE2_HELPER" \
  "$APPLICATION_RECONCILIATION_HELPER"; do
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

run_status() {
  check_participant_accounts
  check_workshop_runtime_state
}

run_application_reconciliation() {
  "$APPLICATION_RECONCILIATION_HELPER"
}

check_workshop_runtime_state() {
  local remote_script
  local state_output

  printf -v remote_script 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  remote_script+="$(cat <<'REMOTE'
set -euo pipefail

workshop_type="$(k3s kubectl -n "$namespace" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}')"

case "$workshop_type" in
  none|introduction-to-ai|federated-learning) ;;
  *)
    printf 'workshop_type=invalid\n'
    printf 'participant_workspace_status=unknown\n'
    exit 0
    ;;
esac

pvc_names="$(k3s kubectl -n "$namespace" get pvc \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"

if grep -Eq '^claim-group-[0-9]+---' <<<"$pvc_names"; then
  workspace_status=present
else
  workspace_status=clean
fi

printf 'workshop_type=%s\n' "$workshop_type"
printf 'participant_workspace_status=%s\n' "$workspace_status"
REMOTE
)"

  state_output="$(run_deployment_remote "$remote_script")"
  printf '%s\n' "$state_output"

  WORKSHOP_TYPE="$(sed -n 's/.*workshop_type=\([^[:space:]]*\).*/\1/p' <<<"$state_output")"
  PARTICIPANT_WORKSPACE_STATUS="$(
    sed -n 's/.*participant_workspace_status=\([^[:space:]]*\).*/\1/p' <<<"$state_output"
  )"

  case "$WORKSHOP_TYPE" in
    none|introduction-to-ai|federated-learning) ;;
    *) fail 'Could not determine the active workshop type. Deploy the current workshop state migration first.' ;;
  esac
  case "$PARTICIPANT_WORKSPACE_STATUS" in
    clean|present) ;;
    *) fail 'Could not determine whether participant workspaces exist.' ;;
  esac
}
ensure_workshop_activation_allowed() {
  local requested_type="$1"

  case "$requested_type" in
    introduction-to-ai|federated-learning) ;;
    *) fail "Unsupported workshop type: $requested_type" ;;
  esac

  check_workshop_runtime_state

  if [[ "$WORKSHOP_TYPE" == "$requested_type" || "$WORKSHOP_TYPE" == none ]]; then
    return 0
  fi

  if [[ "$PARTICIPANT_WORKSPACE_STATUS" == clean ]]; then
    printf '%s\n' \
      "Changing workshop selection from $WORKSHOP_TYPE to $requested_type." \
      'No participant workspace exists; participant identities and credentials are preserved.'
    return 0
  fi

  fail \
    "Cannot change the active workshop from $WORKSHOP_TYPE to $requested_type while participant workspaces exist. Use Reset active workshop cycle → Reset active workshop and participant cohort first."
}

set_introduction_to_ai_workshop_state() {
  local module="$1"
  local mode solutions_released

  case "$module" in
    module1)
      mode=beginner
      solutions_released=false
      ;;
    module2)
      mode=advanced
      solutions_released=false
      ;;
    *)
      fail "Unsupported Introduction to AI module: $module"
      ;;
  esac

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"introduction-to-ai","introduction_to_ai_module":"${module}","mode":"${mode}","solutions_released":"${solutions_released}"}}'
REMOTE
)"
  printf '%s\n' \
    "Introduction to AI ${module} is now active for subsequently spawned participant servers."
}

run_introduction_to_ai_prepare() {
  check_participant_accounts
  [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
    fail 'Provision complete participant identities and groups before starting Introduction to AI.'

  ensure_workshop_activation_allowed introduction-to-ai
  "$MODULE1_HELPER" publish
  set_introduction_to_ai_workshop_state module1
}

run_introduction_to_ai_module2_publish() {
  check_participant_accounts
  [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
    fail 'Provision complete participant identities and groups before starting Introduction to AI Module 2.'

  ensure_workshop_activation_allowed introduction-to-ai
  "$MODULE2_HELPER" check
  set_introduction_to_ai_workshop_state module2
}

run_introduction_to_ai_module2_release_solutions() {
  print_heading "Release Introduction to AI — Module 2 solutions"
  printf '%s\n' \
    'This is a one-way organiser action for subsequently spawned participant servers.' \
    'Existing participant servers and notebooks are not modified.' \
    'It is available only while Introduction to AI Module 2 is active.'

  if ! confirm "Release Module 2 reference solutions after the workshop"; then
    log 'No Module 2 solution release was performed.'
    return 0
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail

workshop_type="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}')"
module="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.introduction_to_ai_module}')"
mode="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

if [ "\$workshop_type" != "introduction-to-ai" ] || \
   [ "\$module" != "module2" ] || \
   [ "\$mode" != "advanced" ]; then
  printf '%s\n' \
    'Module 2 solutions can be released only while Introduction to AI Module 2 is active.' \
    "Current state: workshop_type=\${workshop_type:-unset}, module=\${module:-unset}, mode=\${mode:-unset}" >&2
  exit 1
fi

solution_notebook="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-notebooks-introduction-to-ai-module2-solutions \
  -o jsonpath='{.data.02_foundations_of_ml_solutions\.ipynb}')"
if [ -z "\$solution_notebook" ]; then
  printf '%s\n' \
    'Module 2 solutions ConfigMap does not contain the expected notebook.' \
    'Run reconcile-applications before releasing solutions.' >&2
  exit 1
fi

k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"solutions_released":"true"}}'

printf '%s\n' 'Module 2 solutions released for subsequently spawned participant servers.'
REMOTE
)"

  "$MODULE2_HELPER" status
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

select_fl_mode() {
  local choice

  if [[ -n "$MODE" ]]; then
    [[ "$MODE" == beginner || "$MODE" == advanced ]] ||
      fail 'Choose beginner or advanced.'
    return 0
  fi

  while true; do
    printf '%s\n' \
      'Federated Learning mode:' \
      '  1) Beginner' \
      '  2) Advanced'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) MODE=beginner; return 0 ;;
      2) MODE=advanced; return 0 ;;
      *) printf 'Choose 1 for Beginner or 2 for Advanced.\n' >&2 ;;
    esac
  done
}

run_fl_prepare() {
  local -a pre_reconciliation_readiness_args=(--non-interactive --skip-participant-mapping)
  local -a post_reconciliation_readiness_args=(--non-interactive)
  local -a cohort_args=(new-cohort)

  select_fl_mode
  check_participant_accounts
  [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
    fail 'Provision the participant cohort before initialising a Federated Learning workshop.'

  ensure_workshop_activation_allowed federated-learning

  printf '%s\n' 'Stopping any prior organiser-controlled Flower server...'
  "$FLOWER_MANAGER" stop

  "$PREPARE_HELPER" "${pre_reconciliation_readiness_args[@]}"

  cohort_args+=("$MODE")
  "$NON_INTERACTIVE" && cohort_args+=(--yes)
  "$COHORT_HELPER" "${cohort_args[@]}"

  "$PREPARE_HELPER" "${post_reconciliation_readiness_args[@]}"

  printf '%s\n' 'Starting a fresh Flower server for the initialised cohort...'
  "$FLOWER_MANAGER" restart --defaults
  printf '%s\n' 'Federated Learning preparation completed.'
}

run_flower_manager_menu() {
  local choice rounds min_clients

  while true; do
    printf '\nFlower server lifecycle\n\n'
    printf '  1) Show status and effective parameters\n'
    printf '  2) Start the server\n'
    printf '  3) Stop the server\n'
    printf '  4) Restart the server\n'
    printf '  5) Update rounds and required-client parameters\n'
    printf '  6) Show recent server logs\n'
    printf '  0) Back\n\n'
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
      *) printf 'Choose 0, 1, 2, 3, 4, 5, or 6.\n' >&2 ;;
    esac
  done
}

run_reset() {
  build_account_args
  "$RESET_HELPER" "${ACCOUNT_ARGS[@]}"
}

run_reset_participants() {
  build_account_args
  "$PARTICIPANT_RESET_HELPER" "${ACCOUNT_ARGS[@]}"
}

run_introduction_to_ai_menu() {
  local choice

  while true; do
    printf '\nIntroduction to AI\n\n'
    printf '  1) Module 1 — publish and activate for new participant spawns\n'
    printf '  2) Module 1 — check publication readiness\n'
    printf '  3) Module 2 — activate guided beginner and advanced TODO material\n'
    printf '  4) Module 2 — check activation readiness\n'
    printf '  5) Module 2 — release reference solutions after the workshop\n'
    printf '  6) Module 3 — not configured yet\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) run_introduction_to_ai_prepare ;;
      2) "$MODULE1_HELPER" check ;;
      3) run_introduction_to_ai_module2_publish ;;
      4) "$MODULE2_HELPER" check ;;
      5) run_introduction_to_ai_module2_release_solutions ;;
      6) printf 'This module has not been configured yet.\n' ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, 4, 5, or 6.\n' >&2 ;;
    esac
  done
}

run_federated_learning_menu() {
  local choice

  while true; do
    printf '\nFederated Learning\n\n'
    printf '  1) Initialise beginner workshop\n'
    printf '  2) Initialise advanced workshop\n'
    printf '  3) Release advanced reference solutions\n'
    printf '  4) Manage Flower server\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) MODE=beginner; run_fl_prepare ;;
      2) MODE=advanced; run_fl_prepare ;;
      3) "$COHORT_HELPER" release-solutions ;;
      4) run_flower_manager_menu ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, or 4.\n' >&2 ;;
    esac
  done
}

run_workshops_menu() {
  local choice

  while true; do
    printf '\nWorkshops\n\n'
    printf '  1) Introduction to AI\n'
    printf '  2) Federated Learning\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) run_introduction_to_ai_menu ;;
      2) run_federated_learning_menu ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, or 2.\n' >&2 ;;
    esac
  done
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

run_main_menu() {
  local choice

  while true; do
    printf '\nDIGITAfrica workshop organiser\n\n'
    printf '  1) Manage participant cohort\n'
    printf '  2) Reset active workshop cycle\n'
    printf '  3) Reconcile workshop applications after adding or updating a workshop/module\n'
    printf '  4) Workshops\n'
    printf '  0) Exit\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) run_initialisation_menu ;;
      2) run_reset_menu ;;
      3) run_application_reconciliation ;;
      4) run_workshops_menu ;;
      0) exit 0 ;;
      *) printf 'Choose 0, 1, 2, 3, or 4.\n' >&2 ;;
    esac
  done
}

case "$ACTION" in
  menu)
    [[ -t 0 ]] || fail 'Use an explicit action in a non-interactive shell.'
    run_main_menu
    ;;
  initialise-identities) run_initialise_identities ;;
  issue-credentials) run_issue_credentials ;;
  status) run_status ;;
  module1-publish) run_introduction_to_ai_prepare ;;
  module1-check) "$MODULE1_HELPER" check ;;
  module2-publish) run_introduction_to_ai_module2_publish ;;
  module2-check) "$MODULE2_HELPER" check ;;
  module2-release-solutions) run_introduction_to_ai_module2_release_solutions ;;
  reconcile-applications) run_application_reconciliation ;;
  fl-prepare) run_fl_prepare ;;
  reset) run_reset ;;
  reset-participants) run_reset_participants ;;
  release-solutions) "$COHORT_HELPER" release-solutions ;;
  flower)
    [[ -t 0 ]] || fail 'The flower action requires an interactive terminal.'
    run_flower_manager_menu
    ;;
esac
