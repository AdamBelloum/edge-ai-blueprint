#!/usr/bin/env bash
# Explicit fixed-size educational pilot startup, separate from preparation/build.
set -Eeuo pipefail

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  printf '%s\n' \
    'Usage: start-livy-runtime.sh [--syntax-check]' \
    'Starts the staged one-worker Spark/Livy pilot on the selected group VMs.' \
    'Requires verified existing images, no project orphans and no active project containers.' \
    'Does not prepare assets, pull/build images, remove containers or publish participant access.' \
    'Readiness checks do not establish computation readiness or safe participant concurrency.' \
    'Failed validation after startup may leave containers running; inspect before retrying.'
  exit 0
fi
options=()
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --syntax-check ) ]]; then
  printf 'ERROR: use start-livy-runtime.sh [--syntax-check].\n' >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  options+=(--syntax-check)
fi
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
playbook="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/start-big-data-spark-livy.yml"
[[ -r "$playbook" ]] || {
  printf 'ERROR: startup playbook is missing: %s\n' "$playbook" >&2
  exit 2
}
printf 'Spark/Livy educational pilot target group: %s\n' "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"
exec ansible-playbook \
  -i "$DIGITAFRICA_INVENTORY" \
  "$playbook" \
  --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  "${options[@]}"
