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
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
IDENTITY_RESET_HELPER="$SCRIPT_DIR/identity/reset-participant-environment.sh"
ACCOUNT_HELPER="$SCRIPT_DIR/identity/create-participant-accounts.sh"
RESET_AUTH_SESSION="$SCRIPT_DIR/lib/reset-auth-session.sh"
COHORT_HELPER="$SCRIPT_DIR/federated-learning/fl-workshop.sh"
FL_RESET_HELPER="$SCRIPT_DIR/federated-learning/reset-federated-learning-workshop.sh"
RECONCILIATION_HELPER="$SCRIPT_DIR/reconcile-workshop-applications.sh"
COMMON="$REPOSITORY_ROOT/scripts/lib/common.sh"
WORKSHOP_CONTEXT="$SCRIPT_DIR/lib/workshop-context.sh"

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
  reset-workshops.sh [--accounts keep|delete] [identity options]

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

fail() { printf '\n------ ERROR: %s ------\n\n' "$*" >&2; exit 1; }

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
[[ -x "$FL_RESET_HELPER" ]] || fail "Missing executable FL reset helper: $FL_RESET_HELPER"
[[ -x "$RECONCILIATION_HELPER" ]] || fail "Missing executable reconciliation helper: $RECONCILIATION_HELPER"
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
  '============================================================' \
  'WARNING — DESTRUCTIVE WORKSHOP RESET' \
  '============================================================' \
  'This reset is intended to permanently destroy ALL workshop-specific' \
  'deployments, runtimes, participant workspaces, files, datasets and results.' \
  'Participants must copy any needed data BEFORE you continue.' \
  'Keeping accounts preserves login access ONLY, not workspace contents.' \
  'Shared Kubernetes, JupyterHub, Keycloak, networking and TLS remain.' \
  'Administrators, service accounts and unrelated realm records are preserved.' \
  'A failed or unverified cleanup blocks preparation of another workshop.'
if [[ "$ACCOUNT_ACTION" == delete ]]; then
  printf '%s\n' 'Also DELETE participant Keycloak users/groups and matching credential exports.'
  printf 'Confirm DESTRUCTIVE workshop reset AND account deletion? [y/N]: '
else
  printf '%s\n' 'KEEP participant accounts, groups, passwords and credential exports.'
  printf 'Confirm DESTRUCTIVE workshop reset, keeping accounts only? [y/N]: '
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

  # shellcheck source=lib/reset-auth-session.sh
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
"$FL_RESET_HELPER" --runtime-only


stop_selected_participant_servers

# BEGIN SAVED-CONTEXT RUNTIME DISPATCH

# Read persisted cleanup context, never the possibly neutral selection.
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
supported = {
    "none": {"none"},
    "federated-learning": {"none"},
    "big-data": {"spark"},
    "hpc": {"openmp-01-basics"},
    "introduction-to-ai": {"module1", "module2", "module3"},
    "cloud-computing-soa": {
        "module1", "module2", "module3", "module4", "module5"
    },
}
if not isinstance(workshop, str) or workshop not in supported:
    raise SystemExit("Invalid saved cleanup workshop; reset refused.")
if not isinstance(module, str) or module not in supported[workshop]:
    raise SystemExit("Unsupported saved cleanup module; reset refused.")

print("RESET_RUNTIME_ROUTE=" + workshop + ":" + module)
'
REMOTE
)")"

mapfile -t runtime_routes < <(
  printf '%s\n' "$runtime_context_output" |
    sed -n 's/^RESET_RUNTIME_ROUTE=\([a-z0-9-]*:[a-z0-9-]*\)$/\1/p'
)
((${#runtime_routes[@]} == 1)) ||
  fail 'Could not uniquely determine the saved runtime cleanup route.'

IFS=: read -r cleanup_workshop cleanup_module <<< "${runtime_routes[0]}"

case "$cleanup_workshop" in
  none)
    [[ "$cleanup_module" == none ]] ||
      fail 'Invalid neutral cleanup module.'
    printf '%s\n' 'Saved cleanup context is neutral; no selected runtime dispatched.'
    ;;
  federated-learning)
    [[ "$cleanup_module" == none ]] ||
      fail 'Unsupported FL cleanup module.'

    fl_data_reset_playbook="$REPOSITORY_ROOT/playbooks/reset-fl-worker-data.yml"
    [[ -r "$fl_data_reset_playbook" ]] ||
      fail "Missing FL worker-data cleanup playbook: $fl_data_reset_playbook"
    command -v ansible-playbook >/dev/null 2>&1 ||
      fail 'Required command not found: ansible-playbook.'

    printf '%s\n' \
      'FL baseline runtime stop already ran; no duplicate stop dispatched.' \
      'Removing generated FL data from the selected inventory workers...'

    if ansible-playbook \
      -i "$INVENTORY_PATH" \
      "$fl_data_reset_playbook" \
      -e "fl_reset_worker_group=$WORKER_GROUP"; then
      printf '%s\n' \
        'FL worker-data cleanup verified; installed application assets preserved.'
    else
      fl_cleanup_status=$?
      printf '%s\n' \
        'FL worker-data cleanup failed; cleanup remains in_progress.' >&2
      exit "$fl_cleanup_status"
    fi
    ;;
  big-data|hpc|introduction-to-ai|cloud-computing-soa)
    workshop_reset="$SCRIPT_DIR/$cleanup_workshop/reset-workshop.sh"
    [[ -x "$workshop_reset" ]] ||
      fail "Missing executable workshop reset helper: $workshop_reset"

    printf 'Dispatching saved workshop runtime cleanup: %s / %s\n' \
      "$cleanup_workshop" "$cleanup_module"
    if "$workshop_reset" --runtime-only --module "$cleanup_module"; then
      printf '%s\n' \
        'Selected workshop runtime reset stage returned successfully.' \
        'Full workshop cleanup remains unverified.'
    else
      reset_status=$?
      printf '%s\n' \
        'Workshop runtime reset failed; cleanup remains in_progress.' >&2
      exit "$reset_status"
    fi
    ;;
  *)
    fail 'Unsupported saved runtime cleanup route.'
    ;;
esac
# END SAVED-CONTEXT RUNTIME DISPATCH

# Clean local partitions only for the saved FL cleanup context.
# Reset never regenerates data.
if [[ "$cleanup_workshop" == federated-learning ]]; then
  fl_partition_reset_helper="$SCRIPT_DIR/federated-learning/reset_fl_partitions.py"
  [[ -r "$fl_partition_reset_helper" ]] ||
    fail "Missing FL partition cleanup helper: $fl_partition_reset_helper"

  printf '%s\n' 'Removing local generated FL partitions; preserving canonical source...'
  if python3 "$fl_partition_reset_helper" \
    --repository-root "$REPOSITORY_ROOT"; then
    printf '%s\n' 'Local FL partition cleanup verified.'
  else
    partition_cleanup_status=$?
    printf '%s\n' \
      'Local FL partition cleanup failed; cleanup remains in_progress.' >&2
    exit "$partition_cleanup_status"
  fi
fi

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

# BEGIN NEUTRAL RESET RECONCILIATION
run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"none","workshop_module":"none","mode":"beginner","solutions_released":"false"}}'
REMOTE
)"

"$RECONCILIATION_HELPER" --neutral-for-reset || {
  reconciliation_status=$?
  printf '%s\n' \
    'Neutral reconciliation or release verification failed; cleanup remains in_progress.' >&2
  exit "$reconciliation_status"
}

# Complete only if the state still belongs to a neutral reset in progress.
run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type json \
  -p '[
    {"op":"test","path":"/data/cleanup_status","value":"in_progress"},
    {"op":"test","path":"/data/workshop_type","value":"none"},
    {"op":"test","path":"/data/workshop_module","value":"none"},
    {"op":"test","path":"/data/mode","value":"beginner"},
    {"op":"test","path":"/data/solutions_released","value":"false"},
    {"op":"replace","path":"/data/cleanup_status","value":"complete"}
  ]'
REMOTE
)" || fail 'Could not record reset completion; inspect workshop state before activation.'
# END NEUTRAL RESET RECONCILIATION

printf '%s\n' \
  'RESET COMPLETE — supported cleanup stages and neutral release reconciliation succeeded.' \
  'Participant workspaces were removed; identity handling followed the selected account option.'

warn 'Automated verification covers neutral release configuration and rollout, not effective Hub configuration or fresh notebook startup.'
warn 'Cloud module 5 cleanup covers offline rehearsal only; any live external deployment requires separate verified cleanup.'
