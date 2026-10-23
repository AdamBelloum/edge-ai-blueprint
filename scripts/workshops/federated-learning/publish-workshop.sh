#!/usr/bin/env bash
# Publication-state implementation; sourced by fl-workshop.sh.
# Uses the caller's shared context, helpers, and configuration.

show_tutorial_state() {
  print_heading "Workshop tutorial state"

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
echo "Namespace: ${DIGITAFRICA_NAMESPACE}"
echo "ConfigMap: digitafrica-workshop-state"
echo
echo "workshop_type:"
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}{"\n"}'
echo "mode:"
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}{"\n"}'
echo "solutions_released:"
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.solutions_released}{"\n"}'
REMOTE
)" || return $?

  cat <<'EOF'

The state applies when a participant server is next spawned. Existing running
servers are unchanged because their init containers have already completed.
EOF
}

set_tutorial_mode() {
  local mode="$1"

  case "$mode" in
    beginner|advanced) ;;
    *) die "Invalid tutorial mode: ${mode}" ;;
  esac

  print_heading "Set workshop tutorial mode"
  printf 'Requested mode: %s\n' "$mode"
  printf '%s\n' \
    "This affects subsequently spawned participant servers only." \
    "Existing user servers and files are not modified."

  if ! confirm "Update the workshop tutorial mode"; then
    log "No change made."
    return 0
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"mode":"${mode}"}}'
REMOTE
)"

  show_tutorial_state
}

release_reference_solutions() {
  print_heading "Release reference solutions for advanced workshop"
  printf '%s\n' \
    "This is a one-way organiser action for subsequently spawned participant servers." \
    "Existing user servers and files are not modified." \
    "The release is performed only when the current tutorial mode is advanced."

  if ! confirm "Release reference solutions for the advanced workshop"; then
    log "No change made."
    return 0
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
mode="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

if [ "\$mode" != "advanced" ]; then
  printf '%s\n' \
    "Reference solutions can only be released for an advanced workshop." \
    "Current tutorial mode: \${mode:-unset}" \
    "No change was made."
  exit 0
fi

k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"solutions_released":"true"}}'

printf '%s\n' "Reference solutions released for subsequently spawned advanced-workshop servers."
REMOTE
)"

  show_tutorial_state
}


# Internal step after successful cohort workspace cleanup.
# Reconciliation remains automatic; this is not an organiser menu action.
publish_prepared_fl_cohort() {
  local mode="$1"

  case "$mode" in
    beginner|advanced) ;;
    *) die "Invalid publication mode: $mode" ;;
  esac

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
namespace="${DIGITAFRICA_NAMESPACE}"
mode="${mode}"

if [[ -n "\$mode" ]]; then
  k3s kubectl -n "\$namespace" patch configmap digitafrica-workshop-state \
    --type merge \
    -p "{\"data\":{\"workshop_type\":\"federated-learning\",\"workshop_module\":\"none\",\"mode\":\"\$mode\",\"solutions_released\":\"false\"}}"

  printf 'Fresh cohort state applied: workshop_type=federated-learning, workshop_module=none, mode=%s, solutions_released=false\n' "\$mode"
fi
REMOTE
)" || return $?

  reconcile_current_cohort_mapping || return $?
  show_tutorial_state || return $?
}

reconcile_current_cohort_mapping() {
  [[ -x "$COHORT_MAPPING_HELPER" ]] ||
    die "Workshop cohort-mapping helper is missing or not executable: $COHORT_MAPPING_HELPER"

  print_heading "Preparing participant workshop access"
  "$COHORT_MAPPING_HELPER" || return $?
}
