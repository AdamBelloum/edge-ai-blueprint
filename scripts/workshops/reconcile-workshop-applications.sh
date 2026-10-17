#!/usr/bin/env bash
# Reconcile repository-owned workshop applications on the active deployment.
#
# Run after pulling or adding a workshop, module, notebook track, or related
# JupyterHub application configuration. This stages content, reconciles the
# corresponding Kubernetes resources, upgrades JupyterHub using the pinned
# chart version, and waits for its rollout. It does not deploy infrastructure,
# TLS, Keycloak identity services, participant accounts, or cohort mappings.

set -Eeuo pipefail

# Accept only the scoped HPC runtime opt-in; reject unknown arguments
# before loading deployment context or contacting the deployment.
HPC_RUNTIME_ARGS=()
while (($#)); do
  case "$1" in
    --enable-hpc-runtime)
      HPC_RUNTIME_ARGS=(-e '{"hpc_runtime_enabled":true}')
      shift
      ;;
    -h|--help)
      printf 'Usage: %s [--enable-hpc-runtime]\n' "${0##*/}"
      printf 'The HPC option stages runtime definitions and enables pod integration.\n'
      printf 'It does not activate HPC or install packages on worker hosts.\n'
      exit 0
      ;;
    *)
      printf 'ERROR: Unknown reconciliation option: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSHOP_CONTEXT="${SCRIPT_DIR}/lib/workshop-context.sh"

[[ -r "${WORKSHOP_CONTEXT}" ]] || {
  printf 'ERROR: Missing workshop context helper: %s\n' "${WORKSHOP_CONTEXT}" >&2
  exit 2
}
# shellcheck source=lib/workshop-context.sh
source "${WORKSHOP_CONTEXT}"
load_workshop_context

command -v ansible-playbook >/dev/null 2>&1 || {
  printf 'ERROR: Required command not found: ansible-playbook\n' >&2
  exit 2
}

printf '%s\n' \
  'Reconciling repository-owned workshop applications...' \
  "Inventory: ${DIGITAFRICA_INVENTORY}" \
  "Playbook: ${WORKSHOP_DEPLOYMENT_PLAYBOOK}" \
  "Control-plane group: ${DIGITAFRICA_DEPLOYMENT_GROUP}" \
  "Worker group: ${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  'Scope: workshop assets, application ConfigMaps and state, JupyterHub values, pinned Helm upgrade, and rollout.'

exec ansible-playbook \
  -i "${DIGITAFRICA_INVENTORY}" \
  "${WORKSHOP_DEPLOYMENT_PLAYBOOK}" \
  --tags workshop_application_reconciliation \
  "${HPC_RUNTIME_ARGS[@]}"
