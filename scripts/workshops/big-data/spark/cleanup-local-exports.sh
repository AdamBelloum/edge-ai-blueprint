#!/usr/bin/env bash
# Local generated SSH exports only; no remote execution or participant changes.
set +x
set -Eeuo pipefail
usage() {
  printf '%s\n' \
    'Usage: cleanup-local-exports.sh --check|--execute' \
    '' \
    'Scope: secrets/big-data-spark-direct/<selected inventory worker>/.' \
    'Only login_key, host_key.pub and known_hosts are eligible for deletion.' \
    '--check: validate metadata and report candidates without deleting.' \
    '--execute: delete validated exports and empty selected worker directories.' \
    'Other workers, bind configuration and unrelated secrets remain untouched.' \
    'Run as the export owner, with participant servers stopped and no concurrent' \
    'credential generation, staging or workshop preparation.' \
    'This does not verify complete workshop reset.'
}
if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi
if [[ $# -ne 1 || ( "$1" != --check && "$1" != --execute ) ]]; then
  usage >&2
  exit 2
fi
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../lib/workshop-context.sh"
load_workshop_context
: "${DIGITAFRICA_INVENTORY:?Inventory missing from context}"
: "${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:?Worker group missing from context}"
[[ "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || {
  printf '%s\n' 'ERROR: expected a single inventory worker-group name.' >&2
  exit 2
}
module="${SCRIPT_DIR}/cleanup_local_exports.py"
[[ -f "$module" && ! -L "$module" && -r "$module" ]] || {
  printf '%s\n' 'ERROR: missing regular local-export cleanup module.' >&2
  exit 2
}
for command in ansible-inventory python3; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'ERROR: %s is required.\n' "$command" >&2
    exit 2
  }
done
# Capture successfully before invoking Python. A failed inventory command
# must never supply a partial or otherwise usable selection to cleanup.
if inventory_json="$(ansible-inventory -i "$DIGITAFRICA_INVENTORY" --list)"; then
  :
else
  status=$?
  printf '%s\n' 'ERROR: inventory discovery failed; local exports were not touched.' >&2
  exit "$status"
fi
printf '%s\n' "$inventory_json" | python3 -E -s -B "$module" \
  --worker-group "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" "$1"
