#!/usr/bin/env bash
# Explicit scoped Spark teardown, separate from participant and account reset.
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    'Usage: teardown-runtime.sh --syntax-check|--execute' \
    '' \
    '--syntax-check: parse the teardown playbook without executing tasks.' \
    '--execute: remove ownership-verified Spark containers and networks on worker VMs.' \
    '' \
    'Removes verified locked image references, generated runtime assets and staged Spark seed/data.' \
    'Preserves participant accounts, unrelated image references and coordination locks.' \
    'Requires administrative control of Docker during execution.' \
    'After a successful --execute, also removes the managed Spark NetworkPolicies.' \
    'Failures may leave partial cleanup; protected evidence supports retry.' \
    'This does not verify neutral JupyterHub state or complete workshop reset.'
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 2
fi

options=()
case "$1" in
  --syntax-check)
    options+=(--syntax-check)
    ;;
  --execute)
    options+=(--extra-vars '{"big_data_spark_teardown_execute": true}')
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../lib/workshop-context.sh
source "${SCRIPT_DIR}/../../lib/workshop-context.sh"
load_workshop_context

command -v ansible-playbook >/dev/null 2>&1 || {
  printf 'ERROR: ansible-playbook is required.\n' >&2
  exit 2
}

: "${DIGITAFRICA_INVENTORY:?Inventory missing from context}"
: "${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:?Worker group missing from context}"
: "${WORKSHOP_CONTEXT_REPOSITORY_ROOT:?Repository root missing from context}"

[[ "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || {
  printf 'ERROR: expected a single inventory worker-group name.\n' >&2
  exit 2
}

playbook="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/teardown-big-data-spark-runtime.yml"
[[ -r "$playbook" ]] || {
  printf 'ERROR: teardown playbook is missing: %s\n' "$playbook" >&2
  exit 2
}

printf 'Spark teardown: mode=%s, worker-group=%s\n' \
  "$1" "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"

ansible-playbook \
  -i "$DIGITAFRICA_INVENTORY" \
  "$playbook" \
  --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  "${options[@]}"

# The containers are gone, so their network-policy allowances are obsolete.
if [[ "$1" == --execute ]]; then
  printf '%s\n' 'Runtime removed: deleting the managed Spark network policies.'
  bash "${SCRIPT_DIR}/reconcile-network-policy.sh" remove
fi
