#!/usr/bin/env bash
# Shared active-workshop context for organiser-facing helpers.
# This deliberately has no Tier-1/Tier-2 semantics.

WORKSHOP_CONTEXT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSHOP_CONTEXT_REPOSITORY_ROOT="$(cd -- "${WORKSHOP_CONTEXT_DIR}/../.." && pwd)"
WORKSHOP_RELEASE_RECORD="${WORKSHOP_RELEASE_RECORD:-${WORKSHOP_CONTEXT_DIR}/workshop-release.env}"

load_workshop_context() {
  [[ -r "${WORKSHOP_RELEASE_RECORD}" ]] || {
    printf '[ERROR] Workshop release record is not readable: %s\n' "${WORKSHOP_RELEASE_RECORD}" >&2
    return 2
  }
  # shellcheck source=/dev/null
  source "${WORKSHOP_RELEASE_RECORD}"

  : "${WORKSHOP_INVENTORY:?Workshop release record must define WORKSHOP_INVENTORY.}"
  : "${WORKSHOP_CONTROL_PLANE_GROUP:?Workshop release record must define WORKSHOP_CONTROL_PLANE_GROUP.}"
  : "${WORKSHOP_WORKER_GROUP:?Workshop release record must define WORKSHOP_WORKER_GROUP.}"
  : "${WORKSHOP_DEPLOYMENT_PLAYBOOK:?Workshop release record must define WORKSHOP_DEPLOYMENT_PLAYBOOK.}"

  [[ "${WORKSHOP_INVENTORY}" = /* ]] || \
    WORKSHOP_INVENTORY="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/${WORKSHOP_INVENTORY}"
  [[ -r "${WORKSHOP_INVENTORY}" ]] || {
    printf '[ERROR] Workshop inventory is not readable: %s\n' "${WORKSHOP_INVENTORY}" >&2
    return 2
  }

  [[ "${WORKSHOP_DEPLOYMENT_PLAYBOOK}" = /* ]] || \
    WORKSHOP_DEPLOYMENT_PLAYBOOK="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/${WORKSHOP_DEPLOYMENT_PLAYBOOK}"
  case "${WORKSHOP_DEPLOYMENT_PLAYBOOK}" in
    "${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/"*) ;;
    *)
      printf '[ERROR] Workshop deployment playbook must be under %s/playbooks/: %s\n' \
        "${WORKSHOP_CONTEXT_REPOSITORY_ROOT}" "${WORKSHOP_DEPLOYMENT_PLAYBOOK}" >&2
      return 2
      ;;
  esac
  [[ -r "${WORKSHOP_DEPLOYMENT_PLAYBOOK}" ]] || {
    printf '[ERROR] Workshop deployment playbook is not readable: %s\n' \
      "${WORKSHOP_DEPLOYMENT_PLAYBOOK}" >&2
    return 2
  }

  [[ "${WORKSHOP_CONTROL_PLANE_GROUP}" =~ ^[A-Za-z0-9_.-]+$ ]] || {
    printf '[ERROR] Unsafe workshop control-plane group: %q\n' "${WORKSHOP_CONTROL_PLANE_GROUP}" >&2
    return 2
  }
  [[ "${WORKSHOP_WORKER_GROUP}" =~ ^[A-Za-z0-9_.-]+$ ]] || {
    printf '[ERROR] Unsafe workshop worker group: %q\n' "${WORKSHOP_WORKER_GROUP}" >&2
    return 2
  }

  export DIGITAFRICA_INVENTORY="${WORKSHOP_INVENTORY}"
  export DIGITAFRICA_DEPLOYMENT_GROUP="${WORKSHOP_CONTROL_PLANE_GROUP}"
  export DIGITAFRICA_DEPLOYMENT_WORKER_GROUP="${WORKSHOP_WORKER_GROUP}"
}
