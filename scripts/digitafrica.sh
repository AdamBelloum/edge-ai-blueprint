#!/usr/bin/env bash
# Main role-based entry point for DIGITAfrica helper scripts.
#
# The administrator setup wizard creates independent Tier-1 and Tier-2 local
# inventories. This entry point selects a tier before common.sh captures the
# chosen inventory and server group as readonly values.

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSHOP_TIER="${DIGITAFRICA_DEPLOYMENT_TIER:-tier1}"

case "${WORKSHOP_TIER}" in
  tier1|tier2)
    ;;
  *)
    printf '[ERROR] DIGITAFRICA_DEPLOYMENT_TIER must be tier1 or tier2, not: %s\n' \
      "${WORKSHOP_TIER}" >&2
    exit 1
    ;;
esac

WORKSHOP_INVENTORY="${REPO_ROOT}/inventories/workshop/${WORKSHOP_TIER}/hosts.ini"

# This must happen before common.sh is sourced: common.sh records the selected
# inventory and server group as readonly variables.
if [[ -z "${DIGITAFRICA_INVENTORY:-}" && -f "${WORKSHOP_INVENTORY}" ]]; then
  export DIGITAFRICA_INVENTORY="${WORKSHOP_INVENTORY}"
fi
if [[ -z "${DIGITAFRICA_DEPLOYMENT_GROUP:-}" ]]; then
  export DIGITAFRICA_DEPLOYMENT_GROUP="${WORKSHOP_TIER}_server"
fi

# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

readonly SETUP_SCRIPT="${SCRIPT_DIR}/admin/setup-wizard.sh"
readonly DEPLOY_SCRIPT="${SCRIPT_DIR}/admin/deploy-infrastructure.sh"
readonly HEALTH_SCRIPT="${SCRIPT_DIR}/admin/health-check.sh"
readonly WORKSHOP_HELPER="${SCRIPT_DIR}/workshop/fl-workshop.sh"
readonly ORGANIZER_WIZARD="${SCRIPT_DIR}/workshop/organizer_wizard.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/digitafrica.sh
  ./scripts/digitafrica.sh admin setup
  ./scripts/digitafrica.sh admin deploy [full|tier0|tier1|tier2|tier1-server|preflight]
  ./scripts/digitafrica.sh admin health [all|infrastructure|jupyterhub|silos]
  ./scripts/digitafrica.sh workshop [readiness]
  ./scripts/digitafrica.sh workshop helper [preflight|revisions|inspect-silo-a|inspect-silo-b|checklist|record-template]

Inventory selection:
  Tier-1 is selected by default:
    inventories/workshop/tier1/hosts.ini

  Select Tier-2 with:
    DIGITAFRICA_DEPLOYMENT_TIER=tier2 ./scripts/digitafrica.sh ...

  Set DIGITAFRICA_INVENTORY=/path/to/hosts.ini to use another inventory.
  When using a custom Tier-2 inventory directly, also set:
    DIGITAFRICA_DEPLOYMENT_GROUP=tier2_server
EOF
}

require_helpers() {
  require_file "${SETUP_SCRIPT}"
  require_file "${DEPLOY_SCRIPT}"
  require_file "${HEALTH_SCRIPT}"
  require_file "${WORKSHOP_HELPER}"
  require_file "${ORGANIZER_WIZARD}"
}

admin_menu() {
  local choice

  while true; do
    print_heading "DIGITAfrica administrator"
    printf 'Active inventory: %s\n\n' "${DIGITAFRICA_INVENTORY}"
    cat <<'EOF'
  1) Set up or reconfigure a workshop
  2) Deploy or reconcile infrastructure
  3) Run health checks
  0) Return
EOF
    read -r -p "Selection: " choice
    case "${choice}" in
      1) bash "${SETUP_SCRIPT}" ;;
      2) bash "${DEPLOY_SCRIPT}" menu ;;
      3) bash "${HEALTH_SCRIPT}" all ;;
      0) return 0 ;;
      *) warn "Choose a number from 0 to 3." ;;
    esac
  done
}

main_menu() {
  local choice

  require_helpers
  while true; do
    print_heading "DIGITAfrica Edge-AI Blueprint"
    cat <<'EOF'
Choose your role:
  1) Infrastructure administrator
  2) Federated-learning workshop organiser
  3) Show script context
  0) Exit
EOF
    read -r -p "Selection: " choice
    case "${choice}" in
      1) admin_menu ;;
      2) bash "${ORGANIZER_WIZARD}" ;;
      3) show_context ;;
      0) log "Exiting."; return 0 ;;
      *) warn "Choose a number from 0 to 3." ;;
    esac
  done
}

main() {
  local role="${1:-menu}"
  local action="${2:-}"
  local argument="${3:-}"

  case "${role}" in
    menu)
      main_menu
      ;;
    admin)
      require_helpers
      case "${action:-menu}" in
        setup) bash "${SETUP_SCRIPT}" ;;
        deploy) bash "${DEPLOY_SCRIPT}" "${argument:-menu}" ;;
        health) bash "${HEALTH_SCRIPT}" "${argument:-all}" ;;
        menu) admin_menu ;;
        *) usage >&2; die "Unknown administrator action: ${action}" ;;
      esac
      ;;
    workshop)
      require_helpers
      case "${action:-readiness}" in
        readiness|"")
          bash "${ORGANIZER_WIZARD}"
          ;;
        helper)
          bash "${WORKSHOP_HELPER}" "${argument:-menu}"
          ;;
        *)
          usage >&2
          die "Unknown workshop action: ${action}. Use readiness or helper."
          ;;
      esac
      ;;
    context)
      show_context
      ;;
    help|--help|-h)
      usage
      ;;
    *)
      usage >&2
      die "Unknown role or command: ${role}"
      ;;
  esac
}

main "$@"
