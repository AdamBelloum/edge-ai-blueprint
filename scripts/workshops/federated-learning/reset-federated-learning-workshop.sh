#!/usr/bin/env bash
# Reset the workshop cycle; preserve identities unless deletion is selected.
#
# Order:
#   1. After organiser confirmation, stop only selected participant Jupyter servers.
#   2. Delete only their persistent JupyterHub workspaces.
#   3. Optionally delete inventory-derived Keycloak users and matching groups.
#
# The active workshop state is restored to neutral. Administrators, service accounts,
# and unrelated realm records are preserved.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
IDENTITY_RESET_HELPER="$SCRIPT_DIR/../identity/reset-participant-environment.sh"
ACCOUNT_HELPER="$SCRIPT_DIR/../identity/create-participant-accounts.sh"
RESET_AUTH_SESSION="$SCRIPT_DIR/../lib/reset-auth-session.sh"
COHORT_HELPER="$SCRIPT_DIR/fl-workshop.sh"
FLOWER_MANAGER="$SCRIPT_DIR/manage-flower-server.sh"
COMMON="$REPOSITORY_ROOT/scripts/lib/common.sh"
WORKSHOP_CONTEXT="$SCRIPT_DIR/../lib/workshop-context.sh"

ACCOUNT_ACTION="keep"
SERVER_URL=""
REALM="digitafrica"
ADMIN_REALM=""
ADMIN_USER=""
ADMIN_CLIENT_ID=""
ADMIN_CLIENT_SECRET_FILE=""

usage() {
  cat <<'EOF'
Usage:
  reset-federated-learning-workshop.sh [--accounts keep|delete] [identity options]

Deletes selected participant workspaces and restores neutral workshop state.
Accounts, groups, passwords and credential exports are preserved by default.

  --accounts keep                 Preserve participant identities (default)
  --accounts delete               Delete identities and matching exports

Identity options, required only with --accounts delete:
  --server-url URL                HTTPS Keycloak URL
  --realm NAME                    Participant realm (default: digitafrica)
  --admin-realm NAME               Administration realm
  --admin-user USER                Administrator authentication
  --admin-client-id ID --admin-client-secret-file FILE
                                  Service-account authentication

The administrator password is read privately by the account helper, or from
KEYCLOAK_ADMIN_PASSWORD_FILE when set. This helper does not recreate accounts.
EOF
}

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --accounts) ACCOUNT_ACTION="${2:-}"; shift 2 ;;
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

case "$ACCOUNT_ACTION" in
  keep|delete) ;;
  *) fail '--accounts must be keep or delete.' ;;
esac
[[ -x "$COHORT_HELPER" ]] || fail "Missing executable cohort helper: $COHORT_HELPER"
[[ -x "$FLOWER_MANAGER" ]] || fail "Missing executable Flower manager: $FLOWER_MANAGER"
[[ -r "$COMMON" ]] || fail "Missing common helper: $COMMON"
if [[ "$ACCOUNT_ACTION" == delete ]]; then
  [[ "$SERVER_URL" =~ ^https:// ]] || fail '--server-url must be an HTTPS URL.'
  [[ -x "$IDENTITY_RESET_HELPER" ]] || fail "Missing executable identity reset helper: $IDENTITY_RESET_HELPER"
  [[ -z "$ADMIN_USER" || -z "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]] || \
    fail 'Choose either --admin-user or service-account authentication, not both.'
  if [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]]; then
    [[ -n "$ADMIN_CLIENT_ID" && -n "$ADMIN_CLIENT_SECRET_FILE" ]] || \
      fail 'Service-account authentication requires both client ID and secret-file options.'
  else
    [[ -n "$ADMIN_USER" ]] || fail 'Supply --admin-user or service-account authentication.'
  fi
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
  'This permanently deletes the selected participant JupyterHub workspaces.' \
  'Ensure participants have first had time to copy any needed data from their running servers.' \
  'Workshop selection and tutorial state will be reset to neutral.' \
  'Administrators, service accounts, and unrelated realm records are preserved.'
if [[ "$ACCOUNT_ACTION" == delete ]]; then
  printf '%s\n' 'Also DELETE participant Keycloak users/groups and matching credential exports.'
  printf 'Delete selected workspaces AND participant identities/exports? [y/N]: '
else
  printf '%s\n' 'KEEP participant accounts, groups, passwords and credential exports.'
  printf 'Delete selected workspaces while keeping participant accounts? [y/N]: '
fi
read -r answer
case "$answer" in y|Y|yes|YES) ;; *) printf 'No change made.\n'; exit 0 ;; esac


# Authenticate before recording cleanup or removing any runtime/workspace.
# Keep-account resets do not load the authentication library or call Keycloak.
if [[ "$ACCOUNT_ACTION" == delete ]]; then
  [[ -x "$ACCOUNT_HELPER" ]] ||
    fail "Missing executable account helper: $ACCOUNT_HELPER"
  [[ -r "$RESET_AUTH_SESSION" ]] ||
    fail "Missing reset authentication library: $RESET_AUTH_SESSION"

  ACCOUNT_ARGS=(--server-url "$SERVER_URL" --realm "$REALM")
  [[ -n "$ADMIN_REALM" ]] && ACCOUNT_ARGS+=(--admin-realm "$ADMIN_REALM")
  if [[ -n "$ADMIN_USER" ]]; then
    ACCOUNT_ARGS+=(--admin-user "$ADMIN_USER")
  else
    ACCOUNT_ARGS+=(
      --admin-client-id "$ADMIN_CLIENT_ID"
      --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE"
    )
  fi

  # shellcheck source=../lib/reset-auth-session.sh
  source "$RESET_AUTH_SESSION"
  trap clear_admin_password_session EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM

  printf '%s\n' 'Checking Keycloak access before destructive cleanup...'
  if run_account_helper --status; then
    :
  else
    auth_status=$?
    printf '%s\n' 'Keycloak preflight failed; no destructive cleanup was started.' >&2
    exit "$auth_status"
  fi
fi

# Persist retry context before the first destructive operation.
# Existing incomplete resets retain their original workshop and module,
# even if a previous attempt already changed the selection to none.
run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
namespace="${DIGITAFRICA_NAMESPACE}"

state="\$(k3s kubectl -n "\$namespace" \
  get configmap digitafrica-workshop-state -o json)"

patch="\$(printf '%s' "\$state" | python3 -c '
import json, sys

state = json.load(sys.stdin)
data = state.get("data", {})
status = data.get("cleanup_status", "legacy")
allowed = {
    "none", "introduction-to-ai", "federated-learning",
    "cloud-computing-soa", "big-data", "hpc",
}

if status in {"in_progress", "failed"}:
    workshop = data.get("cleanup_workshop_type")
    module = data.get("cleanup_workshop_module")
elif status in {"legacy", "complete"}:
    workshop = data.get("workshop_type")
    module = data.get("workshop_module", "none")
else:
    raise SystemExit("Unknown cleanup status; reset refused.")

if workshop not in allowed or not isinstance(module, str) or not module:
    raise SystemExit("Missing or invalid cleanup retry context; reset refused.")

print(json.dumps({
    "metadata": {
        "resourceVersion": state["metadata"]["resourceVersion"],
    },
    "data": {
        "cleanup_status": "in_progress",
        "cleanup_workshop_type": workshop,
        "cleanup_workshop_module": module,
    },
}))
')"

k3s kubectl -n "\$namespace" \
  patch configmap digitafrica-workshop-state \
  --type merge -p "\$patch"
REMOTE
)"

printf '%s\n' 'Stopping the organiser-controlled Flower server before participant reset...'
"$FLOWER_MANAGER" stop


stop_selected_participant_servers

# BEGIN SAVED-CONTEXT RUNTIME DISPATCH
# Read the persisted cleanup context, never the possibly neutral selection.
runtime_context_output="$(run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
state="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state -o json)"

printf '%s' "\$state" | python3 -c '
import json, sys

data = json.load(sys.stdin).get("data", {})
if data.get("cleanup_status") != "in_progress":
    raise SystemExit("Cleanup is not in progress; runtime dispatch refused.")

workshop = data.get("cleanup_workshop_type")
module = data.get("cleanup_workshop_module")
allowed = {
    "none", "introduction-to-ai", "federated-learning",
    "cloud-computing-soa", "big-data", "hpc",
}
if workshop not in allowed or not isinstance(module, str) or not module:
    raise SystemExit("Invalid saved cleanup context; runtime dispatch refused.")

if workshop == "big-data":
    if module != "spark":
        raise SystemExit("Unsupported big-data cleanup module; reset refused.")
    route = "spark"
else:
    route = "not-spark"

print("RESET_RUNTIME_ROUTE=" + route)
'
REMOTE
)")"

mapfile -t runtime_routes < <(
  printf '%s\n' "$runtime_context_output" |
    sed -n 's/^RESET_RUNTIME_ROUTE=\(spark\|not-spark\)$/\1/p'
)
((${#runtime_routes[@]} == 1)) ||
  fail 'Could not uniquely determine the saved runtime cleanup route.'

case "${runtime_routes[0]}" in
  spark)
    spark_teardown="$SCRIPT_DIR/../big-data/spark/teardown-runtime.sh"
    [[ -x "$spark_teardown" ]] ||
      fail "Missing executable Spark teardown wrapper: $spark_teardown"
    printf '%s\n' 'Tearing down Spark runtime using the saved cleanup context...'
    if "$spark_teardown" --execute; then
      printf '%s\n' 'Selected worker Spark runtime cleanup verified.'
    else
      teardown_status=$?
      printf '%s\n' \
        'Spark teardown failed; reset stopped and cleanup remains in_progress.' >&2
      exit "$teardown_status"
    fi
    ;;
  not-spark)
    printf '%s\n' \
      'Saved cleanup context does not select Spark; no Spark teardown dispatched.'
    ;;
esac
# END SAVED-CONTEXT RUNTIME DISPATCH

workspace_args=(delete-workspaces --yes)
"$COHORT_HELPER" "${workspace_args[@]}"

if [[ "$ACCOUNT_ACTION" == delete ]]; then
  identity_reset_args=(
    --server-url "$SERVER_URL"
    --realm "$REALM"
    --yes
  )
  [[ -n "$ADMIN_REALM" ]] && identity_reset_args+=(--admin-realm "$ADMIN_REALM")
  if [[ -n "$ADMIN_USER" ]]; then
    identity_reset_args+=(--admin-user "$ADMIN_USER")
  else
    identity_reset_args+=(--admin-client-id "$ADMIN_CLIENT_ID" --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE")
  fi

  "$IDENTITY_RESET_HELPER" "${identity_reset_args[@]}"
else
  printf '%s\n' 'Participant identities and credential exports preserved.'
fi

run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"none","workshop_module":"none","mode":"beginner","solutions_released":"false"}}'
REMOTE
)"

cat <<'GUIDANCE'

RESET INCOMPLETE — do not start a new workshop
  Participant cleanup finished and workshop selection is neutral.
  Full workshop cleanup has NOT been verified. Activation remains blocked
  by cleanup_status=in_progress.

What to do next:
  1. Contact the administrator/maintainer to finish neutral-JupyterHub
     verification and any remaining workshop-specific runtime cleanup.
     Saved-context Spark teardown is integrated, but full reset is not verified.
  2. Do not manually mark cleanup complete or bypass activation safeguards.
  3. Do not publish a new workshop or distribute new credentials until
     full cleanup has been completed and verified.
  4. After verified cleanup, follow the normal organiser workflow:
     provision identities/groups, reconcile updated applications,
     prepare/publish the workshop, check readiness, then issue/export
     and securely distribute participant credentials.

Neutral selection alone does not prove a successful full reset.
GUIDANCE

fail 'Participant reset finished and selection is neutral, but full workshop cleanup is NOT verified. Activation remains blocked by cleanup_status=in_progress. Neutral-Hub verification and complete workshop-runtime coverage remain pending.'
