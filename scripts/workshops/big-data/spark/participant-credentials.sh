#!/usr/bin/env bash
# Spark Stage 1 only: reuse validated credential staging with released context.
# No runtime startup, publication, account changes or credential replacement.
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    'Usage: participant-credentials.sh plan|apply|verify' \
    'plan: validate exports and report staging changes without applying them.' \
    'apply: repeat validation and stage credentials after explicit confirmation.' \
    'verify: require all credentials and helper code to be staged and current; no writes.'
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi
if [[ $# -ne 1 || ( "$1" != plan && "$1" != apply && "$1" != verify ) ]]; then
  usage >&2
  exit 2
fi
action="$1"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../lib/workshop-context.sh"
load_workshop_context

: "${DIGITAFRICA_INVENTORY:?Missing inventory}"
: "${DIGITAFRICA_DEPLOYMENT_GROUP:?Missing control-plane group}"
: "${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:?Missing worker group}"
: "${DIGITAFRICA_NAMESPACE:?Missing namespace}"
: "${WORKSHOP_CONTEXT_REPOSITORY_ROOT:?Missing repository root}"

for group in "$DIGITAFRICA_DEPLOYMENT_GROUP" "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"; do
  if [[ ! "$group" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]]; then
    printf 'ERROR: expected a single inventory group name.\n' >&2
    exit 2
  fi
done
if [[ ${#DIGITAFRICA_NAMESPACE} -gt 63 ||
      ! "$DIGITAFRICA_NAMESPACE" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
  printf 'ERROR: invalid Kubernetes namespace.\n' >&2
  exit 2
fi

command -v ansible-playbook >/dev/null 2>&1 || {
  printf 'ERROR: ansible-playbook is required.\n' >&2
  exit 2
}
playbook="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/reconcile-big-data-spark-credentials.yml"
[[ -r "$playbook" ]] || {
  printf 'ERROR: Spark credential reconciliation playbook is missing.\n' >&2
  exit 2
}

printf 'Spark credentials %s: namespace=%s, control-group=%s, worker-group=%s\n' \
  "$action" "$DIGITAFRICA_NAMESPACE" "$DIGITAFRICA_DEPLOYMENT_GROUP" \
  "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"

if [[ "$action" == apply ]]; then
  printf '%s\n' \
    'Review a successful plan before applying.' \
    'Apply repeats validation and refuses conflicting existing credentials.'
  answer=''
  if ! read -r -p 'Type apply to confirm Spark credential staging: ' answer ||
      [[ "$answer" != apply ]]; then
    printf 'No credential staging was performed.\n' >&2
    exit 1
  fi
fi

exec ansible-playbook -i "$DIGITAFRICA_INVENTORY" "$playbook" \
  --extra-vars "big_data_control_group=${DIGITAFRICA_DEPLOYMENT_GROUP}" \
  --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  --extra-vars "big_data_credentials_namespace=${DIGITAFRICA_NAMESPACE}" \
  --extra-vars "big_data_credentials_action=${action}"
