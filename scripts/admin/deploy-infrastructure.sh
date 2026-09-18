#!/usr/bin/env bash
# Deploy or reconcile DIGITAfrica infrastructure through a guided admin workflow.
#
# Usage:
#   ./scripts/admin/deploy-infrastructure.sh
#   ./scripts/admin/deploy-infrastructure.sh full
#   ./scripts/admin/deploy-infrastructure.sh tier0
#   ./scripts/admin/deploy-infrastructure.sh tier1
#   ./scripts/admin/deploy-infrastructure.sh tier1-server
#   ./scripts/admin/deploy-infrastructure.sh preflight
#
# Optional environment overrides:
#   DIGITAFRICA_INVENTORY=/path/to/hosts.ini
#   DIGITAFRICA_ASSUME_YES=true

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/admin/deploy-infrastructure.sh [ACTION]

Actions:
  full           Deploy the Tier-0 plus Tier-1 site profile using playbooks/site.yml.
  tier0          Deploy Tier-0 using playbooks/tier0.yml.
  tier1          Deploy the complete Tier-1 topology, including agents.
  tier2          Deploy a complete independent Tier-2 topology.
  tier1-server   Reconcile only the Tier-1 control-plane application resources.
  preflight      Run connectivity, syntax, and whitespace checks only.
  menu           Show the interactive action menu. This is the default.
  help           Show this help text.

The script asks for confirmation before a state-changing deployment.
Set DIGITAFRICA_ASSUME_YES=true only for deliberate non-interactive automation.
EOF
}

run_preflight() {
  print_heading "Infrastructure deployment preflight"
  require_ansible_environment
  require_command git

  log "Checking Ansible connectivity to inventory hosts."
  check_ansible_connectivity

  log "Checking Tier-1 and Tier-2 playbook syntax."
  ansible-playbook -i "${DIGITAFRICA_INVENTORY}" \
    "${DIGITAFRICA_TIER1_PLAYBOOK}" \
    --syntax-check
  ansible-playbook -i "${DIGITAFRICA_INVENTORY}" \
    "${DIGITAFRICA_REPO_ROOT}/playbooks/tier2.yml" \
    --syntax-check

  if git -C "${DIGITAFRICA_REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "Checking working-tree whitespace errors."
    git -C "${DIGITAFRICA_REPO_ROOT}" diff --check
  else
    warn "Repository root is not a Git working tree; skipped git diff --check."
  fi

  log "Preflight completed successfully."
}

run_deployment() {
  local action="$1"
  local playbook
  local description
  local target_group
  local -a command

  # Select the dedicated workshop Tier-2 inventory by default.  Preserve an
  # explicitly supplied inventory for deliberate custom deployments.
  if [[ "${action}" == "tier2" &&
        "${DIGITAFRICA_INVENTORY_WAS_EXPLICITLY_SET}" != "true" ]]; then
    DIGITAFRICA_INVENTORY="${DIGITAFRICA_REPO_ROOT}/inventories/workshop/tier2/hosts.ini"
  fi

  case "${action}" in
    full)
      playbook="${DIGITAFRICA_REPO_ROOT}/playbooks/site.yml"
      description="Deploy the Tier-0 plus Tier-1 site profile"
      target_group="all"
      command=(ansible-playbook -i "${DIGITAFRICA_INVENTORY}" "${playbook}")
      ;;
    tier0)
      playbook="${DIGITAFRICA_REPO_ROOT}/playbooks/tier0.yml"
      description="Deploy Tier-0"
      target_group="tier0"
      command=(ansible-playbook -i "${DIGITAFRICA_INVENTORY}" "${playbook}")
      ;;
    tier1)
      playbook="${DIGITAFRICA_TIER1_PLAYBOOK}"
      description="Deploy the complete Tier-1 cluster and application layer"
      target_group="tier1_server"
      command=(ansible-playbook -i "${DIGITAFRICA_INVENTORY}" "${playbook}")
      ;;
    tier2)
      playbook="${DIGITAFRICA_REPO_ROOT}/playbooks/tier2.yml"
      description="Deploy the complete independent Tier-2 cluster and application layer"
      target_group="tier2_server"
      command=(ansible-playbook -i "${DIGITAFRICA_INVENTORY}" "${playbook}")
      ;;
    tier1-server)
      playbook="${DIGITAFRICA_TIER1_PLAYBOOK}"
      description="Reconcile Tier-1 control-plane application resources only"
      target_group="tier1_server"
      command=(
        ansible-playbook
        -i "${DIGITAFRICA_INVENTORY}"
        "${playbook}"
        --limit "${DIGITAFRICA_TIER1_GROUP}"
        -e digitafrica_uninstall=false
      )
      ;;
    *)
      die "Unsupported deployment action: ${action}"
      ;;
  esac

  require_file "${playbook}"
  run_preflight

  print_heading "Deployment confirmation"
  printf 'Action    : %s\n' "${description}"
  printf 'Inventory : %s\n' "${DIGITAFRICA_INVENTORY}"
  printf 'Playbook  : %s\n' "${playbook}"
  printf 'Target    : %s\n' "${target_group}"

  if ! confirm "Continue with this infrastructure change?"; then
    log "Deployment cancelled; no playbook was run."
    return 0
  fi

  print_heading "Running deployment"
  "${command[@]}"

  print_heading "Deployment completed"
  log "Run scripts/admin/health-check.sh next to collect health evidence."
}

interactive_menu() {
  local choice

  while true; do
    print_heading "DIGITAfrica infrastructure deployment"
    show_context
    cat <<'EOF'

Choose an action:
  1) Preflight only: connectivity, syntax, and whitespace checks
  2) Deploy Tier-0 plus Tier-1 site profile
  3) Deploy Tier-0 only
  4) Deploy complete Tier-1 topology
  5) Deploy complete independent Tier-2 topology
  6) Reconcile Tier-1 control-plane application resources only
  0) Exit
EOF
    read -r -p "Selection: " choice

    case "${choice}" in
      1) run_preflight ;;
      2) run_deployment full ;;
      3) run_deployment tier0 ;;
      4) run_deployment tier1 ;;
      5) run_deployment tier2 ;;
      6) run_deployment tier1-server ;;
      0) log "Exiting."; return 0 ;;
      *) warn "Choose a number from 0 to 6." ;;
    esac
  done
}

main() {
  local action="${1:-menu}"

  case "${action}" in
    menu)
      interactive_menu
      ;;
    preflight)
      run_preflight
      ;;
    full|tier0|tier1|tier2|tier1-server)
      run_deployment "${action}"
      ;;
    help|--help|-h)
      usage
      ;;
    *)
      usage >&2
      die "Unknown action: ${action}"
      ;;
  esac
}

main "$@"
