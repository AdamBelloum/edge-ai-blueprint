#!/usr/bin/env bash
# Shared functions for DIGITAfrica helper scripts.
# Source this file; do not execute it directly.

set -o errexit
set -o nounset
set -o pipefail

readonly DIGITAFRICA_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DIGITAFRICA_REPO_ROOT="$(cd "${DIGITAFRICA_SCRIPTS_DIR}/.." && pwd)"

# Operators may override these values through their environment.
readonly DIGITAFRICA_INVENTORY="${DIGITAFRICA_INVENTORY:-${DIGITAFRICA_REPO_ROOT}/inventories/prod/hosts.ini}"
readonly DIGITAFRICA_TIER1_PLAYBOOK="${DIGITAFRICA_TIER1_PLAYBOOK:-${DIGITAFRICA_REPO_ROOT}/playbooks/tier1.yml}"
readonly DIGITAFRICA_NAMESPACE="${DIGITAFRICA_NAMESPACE:-digitafrica}"
readonly DIGITAFRICA_TIER1_GROUP="${DIGITAFRICA_TIER1_GROUP:-tier1_server}"

log() {
  printf '[INFO] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*" >&2
}

die() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

print_heading() {
  printf '\n%s\n' "============================================================"
  printf '%s\n' "$*"
  printf '%s\n' "============================================================"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_file() {
  [[ -f "$1" ]] || die "Required file not found: $1"
}

require_directory() {
  [[ -d "$1" ]] || die "Required directory not found: $1"
}

require_repository_layout() {
  require_file "${DIGITAFRICA_REPO_ROOT}/README.md"
  require_directory "${DIGITAFRICA_REPO_ROOT}/playbooks"
  require_directory "${DIGITAFRICA_REPO_ROOT}/roles"
  require_file "${DIGITAFRICA_INVENTORY}"
  require_file "${DIGITAFRICA_TIER1_PLAYBOOK}"
}

require_ansible_environment() {
  require_command ansible
  require_command ansible-playbook
  require_repository_layout
}

confirm() {
  local prompt="$1"
  local reply

  if [[ "${DIGITAFRICA_ASSUME_YES:-false}" == "true" ]]; then
    log "Automatically confirmed through DIGITAFRICA_ASSUME_YES=true."
    return 0
  fi

  read -r -p "${prompt} [y/N]: " reply
  [[ "${reply}" =~ ^([yY]|[yY][eE][sS])$ ]]
}

show_context() {
  print_heading "DIGITAfrica helper-script context"
  printf 'Repository root : %s\n' "${DIGITAFRICA_REPO_ROOT}"
  printf 'Inventory       : %s\n' "${DIGITAFRICA_INVENTORY}"
  printf 'Tier-1 playbook : %s\n' "${DIGITAFRICA_TIER1_PLAYBOOK}"
  printf 'Namespace       : %s\n' "${DIGITAFRICA_NAMESPACE}"
  printf 'Tier-1 group    : %s\n' "${DIGITAFRICA_TIER1_GROUP}"
}

run_ansible_playbook() {
  require_ansible_environment
  ansible-playbook -i "${DIGITAFRICA_INVENTORY}" "$@"
}

run_tier1_reconciliation() {
  run_ansible_playbook \
    "${DIGITAFRICA_TIER1_PLAYBOOK}" \
    --limit "${DIGITAFRICA_TIER1_GROUP}" \
    -e digitafrica_uninstall=false
}

run_tier1_remote_shell() {
  local remote_command="$1"

  require_ansible_environment
  ANSIBLE_STDOUT_CALLBACK=default ansible \
    -i "${DIGITAFRICA_INVENTORY}" \
    "${DIGITAFRICA_TIER1_GROUP}" \
    -b \
    -m ansible.builtin.shell \
    -a "${remote_command}"
}

check_ansible_connectivity() {
  require_ansible_environment
  ansible -i "${DIGITAFRICA_INVENTORY}" all -m ping
}


run_tier1_remote() {
  local remote_command="$1"
  local encoded_command

  require_ansible_environment
  require_command base64

  encoded_command="$(printf '%s' "${remote_command}" | base64 | tr -d '\n')"

  ANSIBLE_STDOUT_CALLBACK=default ansible \
    -i "${DIGITAFRICA_INVENTORY}" \
    "${DIGITAFRICA_TIER1_GROUP}" \
    -b \
    -m ansible.builtin.shell \
    -a "printf '%s' '${encoded_command}' | base64 -d | /bin/bash"
}
