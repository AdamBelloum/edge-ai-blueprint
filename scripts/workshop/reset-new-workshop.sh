#!/usr/bin/env bash
# Reset stable DIGITAfrica participant identities for a new workshop cohort.
#
# Order:
#   1. After organiser confirmation, stop only selected participant Jupyter servers.
#   2. Delete only their persistent JupyterHub workspaces.
#   3. Delete only their inventory-derived Keycloak users and matching groups.
#
# Tutorial state, administrators, service accounts, and unrelated realm records are preserved.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ACCOUNT_HELPER="$SCRIPT_DIR/create-participant-accounts.sh"
COHORT_HELPER="$SCRIPT_DIR/fl-workshop.sh"
COMMON="$REPOSITORY_ROOT/scripts/lib/common.sh"
WORKSHOP_CONTEXT="$SCRIPT_DIR/workshop-context.sh"

SERVER_URL=""
REALM="digitafrica"
ADMIN_REALM=""
ADMIN_USER=""
ADMIN_CLIENT_ID=""
ADMIN_CLIENT_SECRET_FILE=""

usage() {
  cat <<'EOF'
Usage:
  reset-new-workshop.sh --server-url URL \
    (--admin-user USER | --admin-client-id ID --admin-client-secret-file FILE) \
    [--realm NAME] [--admin-realm NAME]

Deletes the active workshop inventory's participant workspaces, Keycloak users,
and same-named Keycloak groups. It does not change tutorial mode, release
reference solutions, or recreate participant accounts.

The Keycloak administrator password is read privately by
create-participant-accounts.sh, or from KEYCLOAK_ADMIN_PASSWORD_FILE when set.
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --server-url) SERVER_URL="${2:-}"; shift 2 ;;
    --realm) REALM="${2:-}"; shift 2 ;;
    --admin-realm) ADMIN_REALM="${2:-}"; shift 2 ;;
    --admin-user) ADMIN_USER="${2:-}"; shift 2 ;;
    --admin-client-id) ADMIN_CLIENT_ID="${2:-}"; shift 2 ;;
    --admin-client-secret-file) ADMIN_CLIENT_SECRET_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

[[ "$SERVER_URL" =~ ^https:// ]] || fail '--server-url must be an HTTPS URL.'
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

stop_selected_participant_servers() {
  printf '%s\n' 'Stopping selected participant Jupyter servers and waiting for termination...'

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
namespace="${DIGITAFRICA_NAMESPACE}"
IFS=, read -r -a groups <<< "${GROUP_IDS_CSV}"

for group_id in "\${groups[@]}"; do
  if ! pods="\$(k3s kubectl -n "\$namespace" get pods \
    -l "hub.jupyter.org/username=\$group_id" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\\n"}{end}')"; then
    printf 'Could not list participant server pods for %s.\\n' "\$group_id" >&2
    exit 1
  fi

  if [[ -n "\$pods" ]]; then
    mapfile -t pod_names < <(printf '%s\\n' "\$pods")
    printf 'Stopping participant server pod(s) for %s: %s\\n' \
      "\$group_id" "\${pod_names[*]}"
    k3s kubectl -n "\$namespace" delete pod "\${pod_names[@]}" \
      --wait=true --timeout=180s
    printf 'Participant server pod(s) terminated for %s.\\n' "\$group_id"
  else
    printf 'No running participant server pod exists for %s.\\n' "\$group_id"
  fi
done
REMOTE
)"
}

printf '%s\n' \
  "Participant identities: ${GROUP_IDS[*]}" \
  '' \
  'This permanently deletes only the selected participant JupyterHub workspaces,
   inventory-derived Keycloak users, and matching Keycloak groups.' \
  'Ensure participants have first had time to copy any needed data from their running servers.' \
  'Tutorial state, administrators, service accounts, and unrelated records are not changed.'
printf 'Delete these participant workspaces and Keycloak identities? [y/N]: '
read -r answer
case "$answer" in y|Y|yes|YES) ;; *) printf 'No change made.\n'; exit 0 ;; esac

stop_selected_participant_servers

workspace_args=(delete-workspaces --yes)
"$COHORT_HELPER" "${workspace_args[@]}"

account_args=(
  --server-url "$SERVER_URL"
  --realm "$REALM"
  --delete-all-participants
)
[[ -n "$ADMIN_REALM" ]] && account_args+=(--admin-realm "$ADMIN_REALM")
if [[ -n "$ADMIN_USER" ]]; then
  account_args+=(--admin-user "$ADMIN_USER")
else
  account_args+=(--admin-client-id "$ADMIN_CLIENT_ID" --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE")
fi

"$ACCOUNT_HELPER" "${account_args[@]}"

printf 'New workshop cleanup completed: selected participant workspaces and Keycloak identities were deleted.\n'
