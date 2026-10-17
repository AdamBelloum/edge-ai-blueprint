#!/usr/bin/env bash
# OpenMP basics workflow, sourced by the HPC course dispatcher.
# Publication does not prove runtime installation or participant execution.

HPC_OPENMP_MODULE_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
HPC_WORKSPACE_HELPER="$HPC_OPENMP_MODULE_DIR/../prepare-hpc-workspace.sh"
HPC_COHORT_WORKFLOW="$HPC_OPENMP_MODULE_DIR/../../identity/cohort-workshop.sh"

hpc_openmp_prepare_workspace() {
  [[ -x "$HPC_WORKSPACE_HELPER" ]] || {
    printf 'ERROR: Missing executable HPC workspace helper: %s\n' \
      "$HPC_WORKSPACE_HELPER" >&2
    return 2
  }
  "$HPC_WORKSPACE_HELPER"
}

hpc_openmp_publish() {
  [[ -x "$HPC_COHORT_WORKFLOW" ]] || {
    printf 'ERROR: Missing executable participant cohort workflow: %s\n' \
      "$HPC_COHORT_WORKFLOW" >&2
    return 2
  }
  [[ -x "$HPC_WORKSPACE_HELPER" ]] || {
    printf 'ERROR: Missing executable HPC workspace helper: %s\n' \
      "$HPC_WORKSPACE_HELPER" >&2
    return 2
  }

  # Forward organiser CLI settings through the shared argument builder.
  # Only the secret-file path is passed; secret contents are never displayed.
  build_account_args || return $?
  "$HPC_COHORT_WORKFLOW" "${ACCOUNT_ARGS[@]}" require-complete || return $?
  ensure_workshop_activation_allowed hpc || return $?

  printf '%s\n' \
    'Publish HPC OpenMP basics in beginner mode for subsequent participant spawns.' \
    'Runtime environment preparation occurs during participant pod startup.' \
    'Existing participant servers are not automatically updated.' \
    'Publication does not prove compiler availability or OpenMP execution readiness.'

  if ! "${ASSUME_YES:-false}"; then
    if ! confirm "Publish HPC OpenMP basics and reconcile JupyterHub"; then
      log 'No HPC publication was performed.'
      return 0
    fi
  fi

  # Stage teaching files before changing the active selection.
  hpc_openmp_prepare_workspace || return $?

  local remote_script
  printf -v remote_script 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  remote_script+="$(cat <<'REMOTE'
set -euo pipefail
k3s kubectl -n "$namespace" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"hpc","workshop_module":"openmp-01-basics","mode":"beginner","solutions_released":"false"}}'
REMOTE
)"
  run_deployment_remote "$remote_script" || return $?

  if run_application_reconciliation --enable-hpc-runtime; then
    printf '%s\n' \
      'HPC OpenMP basics publication completed for subsequent participant spawns.' \
      'Participant asset delivery, runtime installation and OpenMP execution remain unverified.'
  else
    printf '%s\n' \
      'HPC selection was written, but application reconciliation failed.' \
      'Do not direct participants to spawn yet.' \
      'Correct the failure and rerun reconcile-applications; active HPC retains runtime integration.' >&2
    return 1
  fi
}

hpc_openmp_show_status() {
  print_heading "HPC — OpenMP basics workshop selection"
  check_workshop_runtime_state || return $?
  printf '%s\n' \
    'This reports workshop type and participant workspace presence only.' \
    'It does not validate the selected module, teaching files, compiler or OpenMP execution.'
}
