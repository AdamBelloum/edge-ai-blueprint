#!/usr/bin/env bash
# Standalone organiser helper; no shared deployment or reset changes.
set -Eeuo pipefail
if [[ $# -lt 1 || ( "$1" != prepare && "$1" != start ) ]]; then
  printf '%s\n' 'Usage: participant-direct-runtime.sh prepare|start [Ansible options]' >&2
  printf '%s\n' 'Provide VM-specific big_data_spark_client_bind_ip through inventory or a protected extra-vars file.' >&2
  exit 2
fi
action="$1"; shift
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../lib/workshop-context.sh"
load_workshop_context
: "${DIGITAFRICA_INVENTORY:?Missing inventory}"
: "${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:?Missing worker group}"
: "${WORKSHOP_CONTEXT_REPOSITORY_ROOT:?Missing repository root}"
[[ "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || exit 2
# Reject user overrides of the action or target group: use the released context.
printf 'Big Data direct %s: worker group %s. No VM provisioning or reset.\n' "$action" "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"
if [[ " $* " != *' --syntax-check '* ]]; then
  read -r -p "Type ${action} to confirm this Big Data runtime operation: " answer
  [[ "$answer" == "$action" ]] || exit 1
fi
ansible-playbook -i "$DIGITAFRICA_INVENTORY" \
  "${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/participant-big-data-spark-direct.yml" \
  "$@" \
  --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  --extra-vars "big_data_direct_action=${action}"

# A started runtime gets fresh container addresses: derive the matching narrow
# NetworkPolicies from the live NAT rules. Dry-run options skip this step.
if [[ "$action" == start ]]; then
  skip_policy=0
  for arg in "$@"; do
    case "$arg" in
      --syntax-check|--check|-C|--list-tasks|--list-hosts) skip_policy=1 ;;
    esac
  done
  if [[ "$skip_policy" -eq 0 ]]; then
    printf '%s\n' 'Runtime started: reconciling Spark network policies from live container addresses.'
    bash "${SCRIPT_DIR}/reconcile-network-policy.sh" apply
  fi
fi
