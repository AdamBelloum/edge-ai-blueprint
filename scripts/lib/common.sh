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
# Defaults to the established Tier-1 target for backward compatibility.
readonly DIGITAFRICA_DEPLOYMENT_GROUP="${DIGITAFRICA_DEPLOYMENT_GROUP:-${DIGITAFRICA_TIER1_GROUP}}"

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
  printf 'Deployment group: %s\n' "${DIGITAFRICA_DEPLOYMENT_GROUP}"
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


run_deployment_remote() {
  local remote_command="$1"
  local encoded_command

  require_ansible_environment
  require_command base64

  encoded_command="$(printf '%s' "${remote_command}" | base64 | tr -d '\n')"

  ANSIBLE_STDOUT_CALLBACK=default ansible \
    -i "${DIGITAFRICA_INVENTORY}" \
    "${DIGITAFRICA_DEPLOYMENT_GROUP}" \
    -b \
    -m ansible.builtin.shell \
    -a "printf '%s' '${encoded_command}' | base64 -d | /bin/bash"
}

deployment_tier_name() {
  local tier="${DIGITAFRICA_DEPLOYMENT_TIER:-}"

  if [[ -z "${tier}" && "${DIGITAFRICA_DEPLOYMENT_GROUP}" =~ ^(tier1|tier2)_server$ ]]; then
    tier="${BASH_REMATCH[1]}"
  fi

  case "${tier}" in
    tier1|tier2)
      printf '%s\n' "${tier}"
      ;;
    *)
      die "Cannot determine deployment tier. Set DIGITAFRICA_DEPLOYMENT_TIER to tier1 or tier2."
      ;;
  esac
}

deployment_group_vars_file() {
  local vars_file

  vars_file="$(dirname "${DIGITAFRICA_INVENTORY}")/group_vars/all.yml"
  if [[ ! -f "${vars_file}" ]]; then
    printf '[ERROR] Required deployment configuration file not found: %s\n' "${vars_file}" >&2
    return 1
  fi

  printf '%s\n' "${vars_file}"
}

# Reads only explicitly whitelisted, non-secret settings from the selected
# inventory's group_vars/all.yml. Never add credentials or client secrets here.
deployment_public_setting() {
  local setting="$1"
  local vars_file tier value

  case "${setting}" in
    jupyterhub_public_url|oidc_enabled|oidc_issuer_url|tls_mode)
      ;;
    *)
      die "Unsupported public deployment setting requested: ${setting}"
      ;;
  esac

  require_command python3
  if ! vars_file="$(deployment_group_vars_file)"; then
    die "Cannot locate deployment configuration for the selected inventory."
  fi
  tier="$(deployment_tier_name)"

  if ! value="$(python3 - "${vars_file}" "${tier}" "${setting}" <<'PY'
import sys
from pathlib import Path

import yaml

vars_file = Path(sys.argv[1])
tier = sys.argv[2]
setting = sys.argv[3]

with vars_file.open(encoding="utf-8") as handle:
    data = yaml.safe_load(handle) or {}

if setting == "jupyterhub_public_url":
    value = data.get(tier, {}).get("jupyterhub", {}).get("jupyterhub_public_url")
elif setting == "tls_mode":
    value = data.get(tier, {}).get("tls_mode")
else:
    value = data.get("oidc", {}).get(setting)

if value is None or value == "":
    raise SystemExit(2)
if isinstance(value, bool):
    print(str(value).lower())
elif isinstance(value, str):
    print(value)
else:
    raise SystemExit(2)
PY
  )"; then
    die "Could not read public deployment setting '${setting}' from ${vars_file}."
  fi

  printf '%s\n' "${value}"
}

# Backward-compatible Tier-1 name for existing workshop scripts.
run_tier1_remote() {
  run_deployment_remote "$@"
}
