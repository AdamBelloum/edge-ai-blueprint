#!/usr/bin/env bash
# Reconcile the active workshop's inventory-derived JupyterHub group mapping.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSHOP_CONTEXT="${SCRIPT_DIR}/workshop-context.sh"

[[ -r "${WORKSHOP_CONTEXT}" ]] || {
  printf 'ERROR: Missing workshop context helper: %s\n' "${WORKSHOP_CONTEXT}" >&2
  exit 2
}
# shellcheck source=workshop-context.sh
source "${WORKSHOP_CONTEXT}"
load_workshop_context

command -v ansible-playbook >/dev/null 2>&1 || {
  printf 'ERROR: Required command not found: ansible-playbook\n' >&2
  exit 2
}

printf '%s\n' \
  'Reconciling the inventory-derived JupyterHub participant mapping...' \
  "Inventory: ${DIGITAFRICA_INVENTORY}" \
  "Playbook: ${WORKSHOP_DEPLOYMENT_PLAYBOOK}" \
  "Control-plane group: ${DIGITAFRICA_DEPLOYMENT_GROUP}" \
  "Worker group: ${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}"

exec ansible-playbook \
  -i "${DIGITAFRICA_INVENTORY}" \
  "${WORKSHOP_DEPLOYMENT_PLAYBOOK}" \
  --tags workshop_cohort
