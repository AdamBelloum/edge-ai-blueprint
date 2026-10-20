#!/usr/bin/env bash
# Stage allowlisted HPC teaching assets using the released workshop context.
# Does not activate HPC, install its runtime, or modify participant workspaces.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSHOP_CONTEXT="${SCRIPT_DIR}/../lib/workshop-context.sh"

[[ -r "${WORKSHOP_CONTEXT}" ]] || {
  printf 'ERROR: Missing workshop context helper: %s\n' "${WORKSHOP_CONTEXT}" >&2
  exit 2
}
# shellcheck source=../lib/workshop-context.sh
source "${WORKSHOP_CONTEXT}"
load_workshop_context

command -v ansible-playbook >/dev/null 2>&1 || {
  printf 'ERROR: ansible-playbook is required.\n' >&2
  exit 2
}

exec ansible-playbook \
  -i "${DIGITAFRICA_INVENTORY}" \
  "${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/prepare-hpc-workspace.yml" \
  -e "hpc_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  "$@"
