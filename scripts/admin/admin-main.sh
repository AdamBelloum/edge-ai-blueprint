#!/usr/bin/env bash
# DIGITAfrica administrator entry point.
#
# This script is intentionally thin:
# - setup-wizard.sh owns configuration and deployment orchestration;
# - deploy-infrastructure.sh owns Ansible execution;
# - keycloak-bootstrap.sh owns standalone Keycloak REST reconciliation;
# - health-check.sh is read-only.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
SETUP_WIZARD="${SCRIPT_DIR}/setup-wizard.sh"
HEALTH_CHECK="${SCRIPT_DIR}/health-check.sh"

info() { printf '[INFO] %s\n' "$*"; }
warn() { printf '[WARNING] %s\n' "$*" >&2; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

require_executable() {
  [[ -x "$1" ]] || die "Required executable is missing: $1"
}

choose_tier() {
  local choice

  while true; do
    cat <<'MENU'

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

main() {
  local choice

  while true; do
    cat <<'MENU'

DIGITAfrica administrator

  1) Run infrastructure health check
  2) Configure and deploy infrastructure
  0) Exit
MENU

    read -r -p 'Selection: ' choice
    case "$choice" in
      1) run_health_check ;;
      2) deploy_infrastructure ;;
      0) info 'Exiting.'; exit 0 ;;
      *) warn 'Choose 0, 1, or 2.' ;;
    esac
  done
}

main "$@"
