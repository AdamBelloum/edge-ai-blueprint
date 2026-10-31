#!/usr/bin/env bash
# Released-inventory HPC staging cleanup only.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: cleanup-staging.sh --check|--execute [--source-revision FULL_COMMIT_SHA]

--check: preflight all released target hosts without staging-file deletion.
--execute: repeat fleet preflight, delete matching installed files, verify absence.

Uses administrator SSH/become access. Standard staging paths only:
  workers:       /opt/digitafrica/hpc
  control-plane: /opt/digitafrica/hpc-runtime

Default checksums use the current working tree. An explicit full commit SHA
uses Git source blobs only; it must be an ancestor with identical installation roles.
No automatic historical lookup, checkout, restaging or observed-hash acceptance.

Overrides, content changes, symlinks, hard links and ownership/mode conflicts
block cleanup. Directories and unrelated content remain.

Requires stopped participant servers and exclusive administrator maintenance:
no concurrent staging, publication, reconciliation or participant spawning.
These operational prerequisites are NOT automatically verified.

No participant-home, identity, credential, ConfigMap or shared-service cleanup.
Full workshop reset is NOT verified; neutral reconciliation remains global.
USAGE
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi
if [[ $# -ne 1 && $# -ne 3 ]]; then usage >&2; exit 2; fi
case "$1" in
  --check) execute=false ;;
  --execute) execute=true ;;
  *) usage >&2; exit 2 ;;
esac
revision_args=()
if [[ $# -eq 3 ]]; then
  [[ "$2" == --source-revision && "$3" =~ ^[0-9a-f]{40}$ ]] || {
    usage >&2; exit 2;
  }
  revision_args=(--source-revision "$3")
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
context="$SCRIPT_DIR/../lib/workshop-context.sh"
[[ -r "$context" ]] || {
  printf 'ERROR: Missing workshop context helper.\n' >&2
  exit 2
}
# shellcheck source=../lib/workshop-context.sh
source "$context"
load_workshop_context

for command in python3 ansible-inventory ansible-playbook; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'ERROR: Required command not found: %s\n' "$command" >&2
    exit 2
  }
done

builder="$SCRIPT_DIR/build-cleanup-manifests.py"
playbook="$WORKSHOP_CONTEXT_REPOSITORY_ROOT/playbooks/reset-hpc-staging.yml"
[[ -r "$builder" && -r "$SCRIPT_DIR/cleanup-staged-files.py" && -r "$playbook" ]] || {
  printf 'ERROR: HPC staging cleanup implementation is incomplete.\n' >&2
  exit 2
}

umask 077
temporary="$(mktemp -d "${TMPDIR:-/tmp}/digitafrica-hpc-cleanup.XXXXXXXX")"
inventory_json="$temporary/inventory.json"
manifest_json="$temporary/manifest.json"
cleanup_temporary() {
  rm -f -- "$inventory_json" "$manifest_json"
  rmdir -- "$temporary"
}
trap cleanup_temporary EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

ansible-inventory -i "$DIGITAFRICA_INVENTORY" --list > "$inventory_json"
PYTHONDONTWRITEBYTECODE=1 python3 "$builder" \
  --repository-root "$WORKSHOP_CONTEXT_REPOSITORY_ROOT" \
  --inventory-json "$inventory_json" \
  --worker-group "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" \
  --control-group "$DIGITAFRICA_DEPLOYMENT_GROUP" \
  "${revision_args[@]}" > "$manifest_json"

printf '%s\n' \
  "Inventory: $DIGITAFRICA_INVENTORY" \
  "Worker group: $DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" \
  "Control-plane group: $DIGITAFRICA_DEPLOYMENT_GROUP" \
  "Staging deletion enabled: $execute" \
  "Source revision: ${revision_args[1]:-working-tree}" \
  'Participant homes, identities and Kubernetes resources are not targeted.'

ansible-playbook -i "$DIGITAFRICA_INVENTORY" "$playbook" \
  -e "@$manifest_json" -e "hpc_cleanup_execute=$execute"
