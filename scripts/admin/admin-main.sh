#!/usr/bin/env bash
# DIGITAfrica administrator entry point.
#
# This script is intentionally thin:
# - setup-wizard.sh owns configuration and deployment orchestration;
# - deploy-infrastructure.sh owns Ansible execution;
# - keycloak-bootstrap.sh owns standalone Keycloak REST reconciliation;
# - health-check.sh is read-only;
# - clean-vms.sh removes disposable deployment state while preserving SSH access.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
SETUP_WIZARD="${SCRIPT_DIR}/setup-wizard.sh"
HEALTH_CHECK="${SCRIPT_DIR}/health-check.sh"
CLEAN_VMS="${SCRIPT_DIR}/clean-vms.sh"

info() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARNING] %s\n' "$*" >&2; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

require_executable() {
  [[ -x "$1" ]] || die "Required executable is missing: $1"
}

choose_tier() {
  local choice

  while true; do
    cat >&2 <<'MENU'

Select deployment tier:
  1) Tier-1
  2) Tier-2
  0) Cancel
MENU

    read -r -p 'Selection: ' choice
    case "$choice" in
      1) printf 'tier1\n'; return 0 ;;
      2) printf 'tier2\n'; return 0 ;;
      0) return 1 ;;
      *) warn 'Choose 0, 1, or 2.' ;;
    esac
  done
}

run_health_check() {
  local tier inventory deployment_group

  require_executable "${HEALTH_CHECK}"

  if ! tier="$(choose_tier)"; then
    info 'Health check cancelled.'
    return 0
  fi

  inventory="${REPO_ROOT}/inventories/workshop/${tier}/hosts.ini"
  deployment_group="${tier}_server"

  [[ -f "${inventory}" ]] || die \
    "No local ${tier} inventory exists: ${inventory}. Configure the tier first."

  DIGITAFRICA_INVENTORY="${inventory}" \
  DIGITAFRICA_DEPLOYMENT_GROUP="${deployment_group}" \
    "${HEALTH_CHECK}" all
}

deploy_infrastructure() {
  require_executable "${SETUP_WIZARD}"
  "${SETUP_WIZARD}" --deploy
}

clean_vms_for_fresh_deployment() {
  local tier inventory confirmation

  require_executable "${CLEAN_VMS}"

  if ! tier="$(choose_tier)"; then
    info 'VM cleanup cancelled.'
    return 0
  fi

  inventory="${REPO_ROOT}/inventories/workshop/${tier}/hosts.ini"
  [[ -f "${inventory}" ]] || die \
    "No local ${tier} inventory exists: ${inventory}. Configure the tier first."

  cat <<EOF

WARNING: this removes DIGITAfrica deployment files, Docker state, and k3s
server or agent runtime state from every VM in the selected ${tier} inventory.

Use this only for dedicated disposable VMs. SSH authorised_keys are checked
and preserved by the cleanup helper.

A mandatory dry run will be performed before destructive cleanup.
EOF

  info "Running cleanup dry run for ${tier}: ${inventory}"
  "${CLEAN_VMS}" --inventory "${inventory}" --purge-runtime --dry-run

  printf '\nType PURGE-VM-RUNTIME to remove the selected VM runtime state: '
  read -r confirmation
  if [[ "${confirmation}" != 'PURGE-VM-RUNTIME' ]]; then
    info 'VM cleanup was not confirmed; no destructive action was performed.'
    return 0
  fi

  "${CLEAN_VMS}" --inventory "${inventory}" --purge-runtime --yes
  info "VM cleanup completed for ${tier}. Run deployment configuration before redeploying."
}

main() {
  local choice

  while true; do
    cat <<'MENU'

DIGITAfrica administrator

  1) Run infrastructure health check
  2) Configure and deploy infrastructure
  3) Clean VMs for a fresh deployment (destructive)
  0) Exit
MENU

    read -r -p 'Selection: ' choice
    case "$choice" in
      1) run_health_check ;;
      2) deploy_infrastructure ;;
      3) clean_vms_for_fresh_deployment ;;
      0) info 'Exiting.'; exit 0 ;;
      *) warn 'Choose 0, 1, 2, or 3.' ;;
    esac
  done
}

main "$@"
