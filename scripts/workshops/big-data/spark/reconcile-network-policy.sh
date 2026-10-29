#!/usr/bin/env bash
# Organiser helper: derive, apply or remove the Spark direct-access NetworkPolicies.
# Destinations are discovered from the running Docker NAT rules; none are hard-coded.
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    'Usage: reconcile-network-policy.sh plan|apply|remove' \
    '' \
    '  plan    discover and report what apply would create and delete (read-only)' \
    '  apply   create or update one narrow policy per group, then delete stale ones' \
    '  remove  delete owned Spark policies; preserve unverified legacy objects' \
    '' \
    'Only objects carrying all three organiser/Spark/workshop ownership labels are changed.' \
    'Unlabelled or foreign legacy pilot objects are reported and preserved.'
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi
if [[ $# -ne 1 || ( "$1" != plan && "$1" != apply && "$1" != remove ) ]]; then
  usage >&2
  exit 2
fi
action="$1"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../lib/workshop-context.sh
source "${SCRIPT_DIR}/../../lib/workshop-context.sh"
load_workshop_context
: "${DIGITAFRICA_INVENTORY:?Missing inventory}"
: "${DIGITAFRICA_DEPLOYMENT_GROUP:?Missing control-plane group}"
: "${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:?Missing worker group}"
: "${WORKSHOP_CONTEXT_REPOSITORY_ROOT:?Missing repository root}"
namespace="${DIGITAFRICA_NAMESPACE:-digitafrica}"
[[ "$namespace" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || {
  printf 'ERROR: invalid Kubernetes namespace: %s\n' "$namespace" >&2
  exit 2
}
[[ "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || {
  printf 'ERROR: invalid worker group.\n' >&2
  exit 2
}

printf 'Spark network policy %s: namespace=%s, control group=%s, worker group=%s\n' \
  "$action" "$namespace" "$DIGITAFRICA_DEPLOYMENT_GROUP" "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"

exec ansible-playbook -i "$DIGITAFRICA_INVENTORY" \
  "${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/reconcile-big-data-spark-network-policy.yml" \
  --extra-vars "big_data_control_group=${DIGITAFRICA_DEPLOYMENT_GROUP}" \
  --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  --extra-vars "big_data_network_policy_namespace=${namespace}" \
  --extra-vars "big_data_network_policy_action=${action}"
