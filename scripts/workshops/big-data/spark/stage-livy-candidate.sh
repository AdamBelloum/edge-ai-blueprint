#!/usr/bin/env bash
# Explicit warm candidate asset staging; no preparation, build or startup.
set -Eeuo pipefail

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  printf '%s\n'     'Usage: stage-livy-candidate.sh [--syntax-check]'     'Uses the selected workshop inventory and worker group.'     'Requires an existing prepared one-worker Step 1 configuration.'     'Provide VM-specific SSH bind addresses through inventory.'     'Real staging downloads the locked archive into private temporary storage.'     'Exclude other Docker/filesystem writers during the maintenance window.'     'No image build, service changes, credentials, preparation or reset.'     'Private delivery bundles are retained; runtime readiness is not validated.'
  exit 0
fi

options=()
syntax_seen=false
for option in "$@"; do
  case "$option" in
    --syntax-check)
      [[ "$syntax_seen" == false ]] || {
        printf 'ERROR: duplicate --syntax-check.\n' >&2
        exit 2
      }
      syntax_seen=true
      options+=(--syntax-check)
      ;;
    *)
      printf 'ERROR: use stage-livy-candidate.sh [--syntax-check].\n' >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
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
playbook="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/stage-big-data-spark-livy-candidate.yml"
[[ -r "$playbook" ]] || {
  printf 'ERROR: candidate staging playbook is missing.\n' >&2
  exit 2
}

printf 'Livy candidate staging target group: %s\n' "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"
maintenance=false
if [[ "$syntax_seen" == false ]]; then
  printf '%s\n'     'Candidate assets only; existing compose.yaml and credentials remain unchanged.'     'Confirm a maintenance window excluding other Docker/filesystem writers.'     'The locked archive will be downloaded; private delivery storage is retained.'     'No image build or service startup; runtime readiness remains unvalidated.'
  answer=''
  IFS= read -r -p 'Confirm maintenance and stage Livy runtime files? [y/N]: ' answer || exit 1
  [[ "$answer" =~ ^[yY]$ ]] || exit 1
  maintenance=true
else
  printf '%s\n' 'Syntax check only; no tasks, downloads or staging.'
fi

exec ansible-playbook   -i "$DIGITAFRICA_INVENTORY"   "$playbook"   --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}"   --extra-vars "big_data_livy_stage_maintenance_confirmed=${maintenance}"   "${options[@]}"
