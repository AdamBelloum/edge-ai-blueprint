#!/usr/bin/env bash
# Preparation implementation; sourced by fl-workshop.sh.
# Uses the caller's shared context, helpers, and configuration.

prepare_federated_learning_workshop() {
  local mode="$1"

  case "$mode" in
    beginner|advanced) ;;
    *) die "Invalid preparation mode: $mode" ;;
  esac

  [[ -x "$COHORT_WORKFLOW" ]] ||
    die "Cohort workflow helper is missing or not executable: $COHORT_WORKFLOW"
  [[ -x "$FLOWER_MANAGER" ]] ||
    die "Flower server manager is missing or not executable: $FLOWER_MANAGER"
  [[ -x "$WORKSHOP_READINESS_CHECKER" ]] ||
    die "Workshop readiness checker is missing or not executable: $WORKSHOP_READINESS_CHECKER"

  print_heading "Prepare Federated Learning workshop"

  "$COHORT_WORKFLOW" require-complete
  ensure_workshop_activation_allowed federated-learning

  printf '%s\n' "Stopping any existing organiser-controlled Flower server."
  "$FLOWER_MANAGER" stop

  printf '%s\n' "Checking workshop prerequisites."
  bash "$WORKSHOP_READINESS_CHECKER" --non-interactive --skip-participant-mapping

  start_new_cohort "$mode"

  printf '%s\n' "Checking participant workshop readiness."
  bash "$WORKSHOP_READINESS_CHECKER" --non-interactive

  printf '%s\n' "Starting Flower with inventory-derived default parameters."
  "$FLOWER_MANAGER" restart --defaults

  printf '%s\n' "Federated Learning workshop preparation completed."
}

start_new_cohort() {
  local mode="$1"
  local group_ids_csv
  local confirmation

  case "$mode" in
    ""|beginner|advanced) ;;
    *) die "Invalid cohort mode: ${mode}" ;;
  esac

  resolve_participant_workers
  group_ids_csv="$(IFS=,; printf '%s' "${WORKSHOP_GROUP_IDS[*]}")"

  if [[ -n "$mode" ]]; then
    print_heading "Start a fresh workshop cohort"
    printf 'Selected mode: %s\n' "$mode"
  else
    print_heading "Delete participant workspaces"
  fi
  printf 'Participant identities: %s\n' "${WORKSHOP_GROUP_IDS[*]}"
  cat <<'EOF'

This action deletes only the persistent JupyterHub home workspaces of the
inventory-derived participant identities. Active participant servers must not
be running. When invoked through reset-federated-learning-workshop.sh, selected participant
servers are stopped automatically after its first reset confirmation; when
using this helper directly, stop them through JupyterHub first.

Administrator, hub, PostgreSQL, Redis, and non-participant storage are excluded.
EOF

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail

namespace="${DIGITAFRICA_NAMESPACE}"
groups_csv="${group_ids_csv}"
IFS=, read -r -a groups <<< "\$groups_csv"

k3s kubectl -n "\$namespace" get configmap digitafrica-workshop-state >/dev/null

for group_id in "\${groups[@]}"; do
  active_pods="\$(k3s kubectl -n "\$namespace" get pods \
    -l "hub.jupyter.org/username=\$group_id" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"

  if [[ -n "\$active_pods" ]]; then
    printf 'Refusing reset: participant server still running for %s: %s\n' \
      "\$group_id" "\$active_pods" >&2
    exit 1
  fi

  # This deployment configures KubeSpawner with pvc_name_template =
  # "claim-{username}". KubeSpawner safely escapes group_01 as group-01---<hash>.
  # Participant labels exist on server pods but not on their PVCs, so use the
  # strict selected-identity claim prefix rather than a PVC label selector.
  escaped_group_id="\${group_id//_/-}"
  pvc_prefix="claim-\${escaped_group_id}---"

  if ! all_pvc_names="\$(k3s kubectl -n "\$namespace" get pvc \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"; then
    printf 'Could not list PVCs while resolving the workspace for %s.\n' \
      "\$group_id" >&2
    exit 1
  fi

  pvc_names=()
  while IFS= read -r pvc_name; do
    [[ -n "\$pvc_name" && "\$pvc_name" == "\$pvc_prefix"* ]] &&
      pvc_names+=("\$pvc_name")
  done <<< "\$all_pvc_names"

  if (( \${#pvc_names[@]} > 1 )); then
    printf 'Refusing reset: expected at most one participant PVC for %s; found: %s\n' \
      "\$group_id" "\${pvc_names[*]}" >&2
    exit 1
  fi

  if (( \${#pvc_names[@]} == 1 )); then
    printf 'Would delete participant PVC: %s (identity: %s)\n' \
      "\${pvc_names[0]}" "\$group_id"
  else
    printf 'No participant PVC exists yet for: %s\n' "\$group_id"
  fi
done
REMOTE
)"

  confirmation="Delete the listed participant workspaces"
  [[ -n "$mode" ]] && confirmation+=" and initialise the new cohort"

  if "$ASSUME_COHORT_RESET"; then
    log "Proceeding with the explicitly confirmed participant-workspace reset."
  elif ! confirm "$confirmation"; then
    log "Cohort initialisation cancelled; no change made."
    return 3
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail

namespace="${DIGITAFRICA_NAMESPACE}"
mode="${mode}"
groups_csv="${group_ids_csv}"
IFS=, read -r -a groups <<< "\$groups_csv"

k3s kubectl -n "\$namespace" get configmap digitafrica-workshop-state >/dev/null

for group_id in "\${groups[@]}"; do
  active_pods="\$(k3s kubectl -n "\$namespace" get pods \
    -l "hub.jupyter.org/username=\$group_id" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"

  if [[ -n "\$active_pods" ]]; then
    printf 'Refusing reset: participant server still running for %s: %s\n' \
      "\$group_id" "\$active_pods" >&2
    exit 1
  fi

  # This deployment configures KubeSpawner with pvc_name_template =
  # "claim-{username}". KubeSpawner safely escapes group_01 as group-01---<hash>.
  # Participant labels exist on server pods but not on their PVCs, so use the
  # strict selected-identity claim prefix rather than a PVC label selector.
  escaped_group_id="\${group_id//_/-}"
  pvc_prefix="claim-\${escaped_group_id}---"

  if ! all_pvc_names="\$(k3s kubectl -n "\$namespace" get pvc \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"; then
    printf 'Could not list PVCs while resolving the workspace for %s.\n' \
      "\$group_id" >&2
    exit 1
  fi

  pvc_names=()
  while IFS= read -r pvc_name; do
    [[ -n "\$pvc_name" && "\$pvc_name" == "\$pvc_prefix"* ]] &&
      pvc_names+=("\$pvc_name")
  done <<< "\$all_pvc_names"

  if (( \${#pvc_names[@]} > 1 )); then
    printf 'Refusing reset: expected at most one participant PVC for %s; found: %s\n' \
      "\$group_id" "\${pvc_names[*]}" >&2
    exit 1
  fi

  if (( \${#pvc_names[@]} == 1 )); then
    k3s kubectl -n "\$namespace" delete pvc "\${pvc_names[0]}" \
      --wait=true --timeout=180s
    printf 'Deleted participant PVC: %s (identity: %s)\n' \
      "\${pvc_names[0]}" "\$group_id"
  fi

  remaining_pods="\$(k3s kubectl -n "\$namespace" get pods \
    -l "hub.jupyter.org/username=\$group_id" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\\n"}{end}')"
  [[ -z "\$remaining_pods" ]] || {
    printf 'Workspace cleanup failed: participant pod remains for %s.\\n' \
      "\$group_id" >&2
    exit 1
  }

  remaining_pvcs="\$(k3s kubectl -n "\$namespace" get pvc \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\\n"}{end}')"
  while IFS= read -r remaining_pvc; do
    if [[ -n "\$remaining_pvc" && "\$remaining_pvc" == "\$pvc_prefix"* ]]; then
      printf 'Workspace cleanup failed: participant PVC remains for %s.\\n' \
        "\$group_id" >&2
      exit 1
    fi
  done <<< "\$remaining_pvcs"

  printf 'Participant pod and PVC absence verified for %s.\\n' "\$group_id"
done


REMOTE
)"

  if [[ -n "$mode" ]]; then
    publish_prepared_fl_cohort "$mode"
  fi
}
