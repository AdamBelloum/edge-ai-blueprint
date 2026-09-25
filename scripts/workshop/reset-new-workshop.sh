#!/usr/bin/env bash
# Reset stable DIGITAfrica participant identities for a new workshop cohort.
#
# Order:
#   1. Verify that no participant Jupyter servers are running.
#   2. Reset passwords and revoke participant Keycloak sessions.
#   3. Initialise the selected beginner or advanced cohort baseline.
#
# The account identities and inventory-derived group mapping are preserved.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ACCOUNT_HELPER="$SCRIPT_DIR/create-participant-accounts.sh"
COHORT_HELPER="$SCRIPT_DIR/fl-workshop.sh"
COMMON="$REPOSITORY_ROOT/scripts/lib/common.sh"
WORKSHOP_CONTEXT="$SCRIPT_DIR/workshop-context.sh"

MODE=""
SERVER_URL=""
REALM="digitafrica"
CREDENTIALS_OUTPUT=""
ADMIN_REALM=""
ADMIN_USER=""
ADMIN_CLIENT_ID=""
ADMIN_CLIENT_SECRET_FILE=""

usage() {
  cat <<'EOF'
Usage:
  reset-new-workshop.sh --server-url URL --credentials-output FILE \
    (--admin-user USER | --admin-client-id ID --admin-client-secret-file FILE) \
    [--realm NAME] [--admin-realm NAME] beginner|advanced

Resets stable participant identities for a fresh workshop cohort. It derives
participant accounts from the active workshop release record's worker inventory,
revokes active Keycloak sessions while resetting temporary passwords, then
delegates safe participant-PVC cleanup and tutorial initialisation to fl-workshop.sh.

The Keycloak administrator password is read privately by
create-participant-accounts.sh, or from KEYCLOAK_ADMIN_PASSWORD_FILE when set.
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --server-url) SERVER_URL="${2:-}"; shift 2 ;;
    --realm) REALM="${2:-}"; shift 2 ;;
    --credentials-output) CREDENTIALS_OUTPUT="${2:-}"; shift 2 ;;
    --admin-realm) ADMIN_REALM="${2:-}"; shift 2 ;;
    --admin-user) ADMIN_USER="${2:-}"; shift 2 ;;
    --admin-client-id) ADMIN_CLIENT_ID="${2:-}"; shift 2 ;;
    --admin-client-secret-file) ADMIN_CLIENT_SECRET_FILE="${2:-}"; shift 2 ;;
    beginner|advanced)
      [[ -z "$MODE" ]] || fail 'Specify exactly one workshop mode.'
      MODE="$1"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

[[ -n "$MODE" ]] || fail 'Specify the new workshop mode: beginner or advanced.'
[[ "$SERVER_URL" =~ ^https:// ]] || fail '--server-url must be an HTTPS URL.'
[[ -n "$CREDENTIALS_OUTPUT" ]] || fail '--credentials-output is required.'
[[ -x "$ACCOUNT_HELPER" ]] || fail "Missing executable account helper: $ACCOUNT_HELPER"
[[ -x "$COHORT_HELPER" ]] || fail "Missing executable cohort helper: $COHORT_HELPER"
[[ -r "$COMMON" ]] || fail "Missing common helper: $COMMON"
[[ -z "$ADMIN_USER" || -z "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]] || \
  fail 'Choose either --admin-user or service-account authentication, not both.'
if [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]]; then
  [[ -n "$ADMIN_CLIENT_ID" && -n "$ADMIN_CLIENT_SECRET_FILE" ]] || \
    fail 'Service-account authentication requires both client ID and secret-file options.'
else
  [[ -n "$ADMIN_USER" ]] || fail 'Supply --admin-user or service-account authentication.'
fi

[[ -r "$WORKSHOP_CONTEXT" ]] ||
  fail "Missing workshop context helper: $WORKSHOP_CONTEXT"
# shellcheck source=workshop-context.sh
source "$WORKSHOP_CONTEXT"
load_workshop_context || exit 1

# shellcheck source=/dev/null
source "$COMMON"
command -v ansible-inventory >/dev/null 2>&1 || fail 'Required command not found: ansible-inventory'

deployment_worker_group >/dev/null || fail 'Could not determine the active workshop worker group.'
WORKER_GROUP="$(deployment_worker_group)"
INVENTORY_PATH="${DIGITAFRICA_INVENTORY}"

mapfile -t GROUP_IDS < <(
  ansible-inventory -i "$INVENTORY_PATH" --list | python3 -c '
import json, sys
inventory = json.load(sys.stdin)
group = inventory.get(sys.argv[1], {})
hosts = group.get("hosts", [])
if not isinstance(hosts, list) or not hosts:
    raise SystemExit("selected worker group has no ordered hosts")
for index, host in enumerate(hosts, 1):
    if not isinstance(host, str) or not host:
        raise SystemExit("invalid worker name")
    print(f"group_{index:02d}")
' "$WORKER_GROUP"
)
((${#GROUP_IDS[@]} > 0)) || fail 'No participant identities were derived from the active workshop inventory.'
GROUP_IDS_CSV="$(IFS=,; printf '%s' "${GROUP_IDS[*]}")"

# Do this before credentials are changed. A running participant server means the
# reset is refused without modifying Keycloak or persistent workspaces.
run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
namespace="${DIGITAFRICA_NAMESPACE}"
IFS=, read -r -a groups <<< "${GROUP_IDS_CSV}"
for group_id in "\${groups[@]}"; do
  pods="\$(k3s kubectl -n "\$namespace" get pods -l "hub.jupyter.org/username=\$group_id" -o jsonpath='{range .items[*]}{.metadata.name}{"\\n"}{end}')"
  if [[ -n "\$pods" ]]; then
    printf 'Participant server is still running for %s: %s\\n' "\$group_id" "\$pods" >&2
    exit 1
  fi
done
REMOTE
)" >/dev/null

printf '%s\n' \
  "New workshop mode     : $MODE" \
  "Participant identities: ${GROUP_IDS[*]}" \
  "Credential record     : $CREDENTIALS_OUTPUT" \
  '' \
  'This will reset participant passwords, revoke their Keycloak sessions, and then request confirmation before deleting only their JupyterHub PVCs.'
printf 'Continue with the new-workshop reset? [y/N]: '
read -r answer
case "$answer" in y|Y|yes|YES) ;; *) printf 'No change made.\n'; exit 0 ;; esac

account_args=(
  --server-url "$SERVER_URL"
  --realm "$REALM"
  --credentials-output "$CREDENTIALS_OUTPUT"
  --reset-all-passwords
)
[[ -n "$ADMIN_REALM" ]] && account_args+=(--admin-realm "$ADMIN_REALM")
if [[ -n "$ADMIN_USER" ]]; then
  account_args+=(--admin-user "$ADMIN_USER")
else
  account_args+=(--admin-client-id "$ADMIN_CLIENT_ID" --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE")
fi

"$ACCOUNT_HELPER" "${account_args[@]}"

printf '%s\n' 'Passwords and sessions have been reset. The next confirmation is for participant workspace deletion only.'
"$COHORT_HELPER" new-cohort "$MODE"

printf 'New workshop reset completed. Deliver the mode-0600 credential file securely: %s\n' "$CREDENTIALS_OUTPUT"
