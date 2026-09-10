#!/usr/bin/env bash
# Guided helper for a DIGITAfrica federated-learning workshop organiser.
#
# This script deliberately does not start a Flower server or clients because
# the correct invocation, data approval, and experiment configuration are
# application-specific. It prepares the organiser with verified platform and
# workspace evidence before the documented experiment procedure is followed.


# Main role-based entry point for DIGITAfrica helper scripts.

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

readonly DEPLOY_SCRIPT="${SCRIPT_DIR}/admin/deploy-infrastructure.sh"
readonly HEALTH_SCRIPT="${SCRIPT_DIR}/admin/health-check.sh"
readonly WORKSHOP_SCRIPT="${SCRIPT_DIR}/workshop/fl-workshop.sh"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/digitafrica.sh
  ./scripts/digitafrica.sh admin deploy [full|tier0|tier1|tier1-server|preflight]
  ./scripts/digitafrica.sh admin health [all|infrastructure|jupyterhub|silos]
  ./scripts/digitafrica.sh workshop [preflight|revisions|inspect-silo-a|inspect-silo-b|checklist|record-template]
EOF
}

require_helpers() {
  require_file "${DEPLOY_SCRIPT}"
  require_file "${HEALTH_SCRIPT}"
  require_file "${WORKSHOP_SCRIPT}"
}

admin_menu() {
  local choice

  while true; do
    print_heading "DIGITAfrica administrator"
    cat <<'EOF'
  1) Deploy or reconcile infrastructure
  2) Run health checks
  0) Return
EOF
    read -r -p "Selection: " choice
    case "${choice}" in
      1) bash "${DEPLOY_SCRIPT}" menu ;;
      2) bash "${HEALTH_SCRIPT}" all ;;
      0) return 0 ;;
      *) warn "Choose 0, 1, or 2." ;;
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
      2) bash "${WORKSHOP_SCRIPT}" menu ;;
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
        deploy) bash "${DEPLOY_SCRIPT}" "${argument:-menu}" ;;
        health) bash "${HEALTH_SCRIPT}" "${argument:-all}" ;;
        menu) admin_menu ;;
        *) usage >&2; die "Unknown administrator action: ${action}" ;;
      esac
      ;;
    workshop)
      require_helpers
      bash "${WORKSHOP_SCRIPT}" "${action:-menu}"
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
