#!/usr/bin/env bash
# Organiser-only direct Spark computation test; not a participant launcher.
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    'Usage: test-runtime.sh [--syntax-check] [--limit INVENTORY_HOST]' \
    'Runs a bounded script test in a dedicated driver container on the private Spark network.' \
    'Requires an already prepared and running Spark runtime; Livy is not required.' \
    'Does not pull/build images, start/stop cluster services or enable participant access.' \
    'The optional single-host limit is intersected with the selected worker group.'
}
options=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --syntax-check) options+=(--syntax-check); shift ;;
    --limit)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      [[ "$2" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || {
        printf 'ERROR: expected a single inventory hostname.\n' >&2
        exit 2
      }
      options+=(--limit "$2")
      shift 2
      ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../../lib/workshop-context.sh
source "${SCRIPT_DIR}/../../../lib/workshop-context.sh"
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
playbook="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/test-big-data-spark-direct.yml"
[[ -r "$playbook" ]] || {
  printf 'ERROR: direct Spark test playbook is missing: %s\n' "$playbook" >&2
  exit 2
}
printf 'Organiser-only direct Spark test; selected group: %s\n' "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"
exec ansible-playbook \
  -i "$DIGITAFRICA_INVENTORY" \
  "$playbook" \
  --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  "${options[@]}"
