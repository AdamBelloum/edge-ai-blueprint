#!/usr/bin/env bash
# Stage Spark participant assets using the released workshop context.
# Does not activate Spark, change authentication, or provision its runtime.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/workshop-context.sh"
load_workshop_context

command -v ansible-playbook >/dev/null 2>&1 || {
  printf 'ERROR: ansible-playbook is required.\n' >&2
  exit 2
}

exec ansible-playbook \
  -i "${DIGITAFRICA_INVENTORY}" \
  "${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/prepare-big-data-workspace.yml" \
  -e "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  "$@"
