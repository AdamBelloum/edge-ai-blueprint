#!/usr/bin/env bash
# Explicit single-session computation test with owned-session cleanup.
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    'Usage: test-livy-runtime.sh [--syntax-check] [--limit INVENTORY_HOST]' \
    'Creates one bounded organiser test session, checks its result and deletes only that session.' \
    'Does not prepare assets, pull/build images, start/stop services or enable participant access.' \
    'The optional single-host limit is intersected with the selected worker group.'
}
options=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --syntax-check)
      options+=(--syntax-check)
      shift
      ;;
    --limit)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      [[ "$2" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || {
        printf 'ERROR: expected a single inventory hostname.\n' >&2
        exit 2
      }
      options+=(--limit "$2")
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *) usage >&2; exit 2 ;;
  esac
done
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
playbook="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/test-big-data-spark-livy.yml"
[[ -r "$playbook" ]] || {
  printf 'ERROR: checker playbook is missing: %s\n' "$playbook" >&2
  exit 2
}
printf 'Bounded Spark/Livy computation test; selected group: %s\n' "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"
exec ansible-playbook \
  -i "$DIGITAFRICA_INVENTORY" \
  "$playbook" \
  --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  "${options[@]}"
