#!/usr/bin/env bash
# Explicit organiser image build, separate from preparation and startup.
set -Eeuo pipefail

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  printf '%s\n' \
    'Usage: build-livy-image.sh [--transition-candidate] [--syntax-check]' \
    'Requires explicitly staged Livy assets and the local pinned Spark base.' \
    'Builds sequentially on the selected inventory worker group.' \
    '--transition-candidate reads compose.livy-transition.yaml for image building only.' \
    'Does not prepare assets, start services, publish workspaces, or change accounts.' \
    'A real build consumes VM resources; plan an appropriate maintenance window.'
  exit 0
fi
options=()
candidate_options=()
syntax_seen=false
candidate_seen=false
for option in "$@"; do
  case "$option" in
    --syntax-check)
      [[ "$syntax_seen" == false ]] || {
        printf 'ERROR: duplicate --syntax-check.\n' >&2; exit 2
      }
      syntax_seen=true
      options+=(--syntax-check)
      ;;
    --transition-candidate)
      [[ "$candidate_seen" == false ]] || {
        printf 'ERROR: duplicate --transition-candidate.\n' >&2; exit 2
      }
      candidate_seen=true
      candidate_options+=(--extra-vars 'big_data_livy_build_candidate=true')
      ;;
    *)
      printf 'ERROR: use build-livy-image.sh [--transition-candidate] [--syntax-check].\n' >&2
      exit 2
      ;;
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
playbook="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/build-big-data-livy-image.yml"
[[ -r "$playbook" ]] || {
  printf 'ERROR: build playbook is missing: %s\n' "$playbook" >&2
  exit 2
}
printf 'Livy image build target group: %s\n' "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"
if [[ ${#options[@]} -eq 0 ]]; then
  printf '%s\n' 'Explicit image build only; no preparation or service startup.'
fi
exec ansible-playbook \
  -i "$DIGITAFRICA_INVENTORY" \
  "$playbook" \
  --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  "${candidate_options[@]}" \
  "${options[@]}"
