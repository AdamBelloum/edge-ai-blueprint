#!/usr/bin/env bash
# Deploy or reconcile DIGITAfrica infrastructure through Ansible.
#
# Tier-specific actions:
#   deploy-infrastructure.sh tier1 identity
#   deploy-infrastructure.sh tier1 applications
#   deploy-infrastructure.sh tier1 full
#   deploy-infrastructure.sh tier2 identity
#   deploy-infrastructure.sh tier2 applications
#   deploy-infrastructure.sh tier2 full

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"

usage() {
  cat <<'USAGE'
Usage:
  scripts/admin/deploy-infrastructure.sh [ACTION] [PHASE]

Tier-specific actions:
  tier1 identity       Deploy Keycloak/PostgreSQL/TLS identity resources.
  tier1 applications   Deploy OIDC secret, JupyterHub, and workshop applications.
  tier1 full           Deploy the complete Tier-1 workshop profile.

  tier2 identity       Deploy Keycloak/PostgreSQL/TLS identity resources.
  tier2 applications   Deploy OIDC secret, JupyterHub, and workshop applications.
  tier2 full           Deploy the complete Tier-2 workshop profile.

Legacy actions:
  full                 Deploy the Tier-0 plus Tier-1 site profile.
  tier0                Deploy Tier-0.
  tier1-server         Reconcile Tier-1 control-plane resources.
  preflight            Run connectivity, syntax, and whitespace checks.
  menu                 Show the interactive menu.
  help                 Show this help.

The identity and applications phases are intended for the Managed-Keycloak OIDC
profile. The Basic profile uses the selected tier's full action.
USAGE
}

run_preflight() {
  local playbook="$1"

  print_heading "Infrastructure deployment preflight"
  require_ansible_environment
  require_command git

  log "Checking Ansible connectivity to inventory hosts."
  check_ansible_connectivity

  log "Checking playbook syntax."
  ansible-playbook -i "${DIGITAFRICA_INVENTORY}" \
    "${playbook}" \
    --syntax-check

  if git -C "${DIGITAFRICA_REPO_ROOT}" \
    rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "Checking working-tree whitespace errors."
    git -C "${DIGITAFRICA_REPO_ROOT}" diff --check
  fi

  log "Preflight completed successfully."
}

set_tier_inventory_if_needed() {
  local tier="$1"

  if [[ "${DIGITAFRICA_INVENTORY_WAS_EXPLICITLY_SET}" != "true" ]]; then
    DIGITAFRICA_INVENTORY=\
"${DIGITAFRICA_REPO_ROOT}/inventories/workshop/${tier}/hosts.ini"
  fi

  [[ -f "${DIGITAFRICA_INVENTORY}" ]] ||
    die "Inventory not found: ${DIGITAFRICA_INVENTORY}"
}

run_tier_deployment() {
  local tier="$1"
  local phase="$2"
  local playbook
  local description
  local target_group
  local -a command

  case "$tier" in
    tier1|tier2) ;;
    *) die "Unsupported deployment tier: ${tier}" ;;
  esac

  case "$phase" in
    identity|applications|full) ;;
    *) die "Unsupported ${tier} phase: ${phase}" ;;
  esac

  set_tier_inventory_if_needed "$tier"

  playbook="${DIGITAFRICA_REPO_ROOT}/playbooks/${tier}.yml"
  target_group="${tier}_server"
  require_file "$playbook"

  case "$phase" in
    identity)
      description="Deploy ${tier^} Keycloak identity infrastructure"
      command=(
        ansible-playbook
        -i "${DIGITAFRICA_INVENTORY}"
        "${playbook}"
        --tags identity
      )
      ;;
    applications)
      description="Deploy ${tier^} OIDC and workshop applications"
      command=(
        ansible-playbook
        -i "${DIGITAFRICA_INVENTORY}"
        "${playbook}"
        --tags applications
      )
      ;;
    full)
      description="Deploy the complete ${tier^} workshop profile"
      command=(
        ansible-playbook
        -i "${DIGITAFRICA_INVENTORY}"
        "${playbook}"
      )
      ;;
  esac

  run_preflight "$playbook"

  print_heading "Deployment confirmation"
  printf 'Tier      : %s\n' "$tier"
  printf 'Phase     : %s\n' "$phase"
  printf 'Action    : %s\n' "$description"
  printf 'Inventory : %s\n' "${DIGITAFRICA_INVENTORY}"
  printf 'Playbook  : %s\n' "$playbook"
  printf 'Target    : %s\n' "$target_group"

  if ! confirm "Continue with this infrastructure change?"; then
    log "Deployment cancelled; no playbook was run."
    return 0
  fi

  print_heading "Running deployment"
  "${command[@]}"

  print_heading "Deployment completed"
  log "Run scripts/admin/health-check.sh for read-only validation."
}

run_legacy_deployment() {
  local action="$1"
  local playbook
  local description
  local target_group
  local -a command

  case "$action" in
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
    tier1-server)
      playbook="${DIGITAFRICA_TIER1_PLAYBOOK}"
      description="Reconcile Tier-1 control-plane application resources"
      target_group="${DIGITAFRICA_TIER1_GROUP}"
      command=(
        ansible-playbook
        -i "${DIGITAFRICA_INVENTORY}"
        "${playbook}"
        --limit "${DIGITAFRICA_TIER1_GROUP}"
        -e digitafrica_uninstall=false
      )
      ;;
    *)
      die "Unsupported legacy deployment action: ${action}"
      ;;
  esac

  require_file "$playbook"
  run_preflight "$playbook"

  print_heading "Deployment confirmation"
  printf 'Action    : %s\n' "$description"
  printf 'Inventory : %s\n' "${DIGITAFRICA_INVENTORY}"
  printf 'Playbook  : %s\n' "$playbook"
  printf 'Target    : %s\n' "$target_group"

  if ! confirm "Continue with this infrastructure change?"; then
    log "Deployment cancelled; no playbook was run."
    return 0
  fi

  print_heading "Running deployment"
  "${command[@]}"

  print_heading "Deployment completed"
  log "Run scripts/admin/health-check.sh for read-only validation."
}

interactive_menu() {
  local choice

  while true; do
    print_heading "DIGITAfrica infrastructure deployment"
    show_context

    cat <<'MENU'

Choose an action:
  1) Preflight only
  2) Deploy complete Tier-1 workshop profile
  3) Deploy complete Tier-2 workshop profile
  4) Deploy legacy Tier-0 plus Tier-1 site profile
  5) Deploy legacy Tier-0 only
  6) Reconcile legacy Tier-1 control-plane resources
  0) Exit
MENU

    read -r -p "Selection: " choice
    case "$choice" in
      1)
        run_preflight "${DIGITAFRICA_TIER1_PLAYBOOK}"
        ;;
      2)
        run_tier_deployment tier1 full
        ;;
      3)
        run_tier_deployment tier2 full
        ;;
      4)
        run_legacy_deployment full
        ;;
      5)
        run_legacy_deployment tier0
        ;;
      6)
        run_legacy_deployment tier1-server
        ;;
      0)
        log "Exiting."
        return 0
        ;;
      *)
        warn "Choose a number from 0 to 6."
        ;;
    esac
  done
}

main() {
  local action="${1:-menu}"
  local phase="${2:-full}"

  case "$action" in
    tier1|tier2)
      run_tier_deployment "$action" "$phase"
      ;;
    full|tier0|tier1-server)
      [[ "$#" -eq 1 ]] ||
        die "Legacy action ${action} does not accept a phase."
      run_legacy_deployment "$action"
      ;;
    preflight)
      [[ "$#" -eq 1 ]] ||
        die "preflight does not accept a phase."
      run_preflight "${DIGITAFRICA_TIER1_PLAYBOOK}"
      ;;
    menu)
      [[ "$#" -eq 1 ]] ||
        die "menu does not accept a phase."
      interactive_menu
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
