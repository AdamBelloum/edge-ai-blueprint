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

  "$COHORT_WORKFLOW" require-complete || return $?
  ensure_workshop_activation_allowed federated-learning || return $?

  printf '%s\n' "Stopping any existing organiser-controlled Flower server."
  "$FLOWER_MANAGER" stop || return $?

  printf '%s\n' "Recovering and staging checksum-verified participant partitions."
  recover_and_stage_fl_partitions || return $?

  printf '%s\n' "Checking workshop prerequisites."
  bash "$WORKSHOP_READINESS_CHECKER" --non-interactive --skip-participant-mapping || return $?

  start_new_cohort "$mode" || return $?

  printf '%s\n' "Checking participant workshop readiness."
  bash "$WORKSHOP_READINESS_CHECKER" --non-interactive || return $?

  printf '%s\n' "Starting Flower with inventory-derived default parameters."
  "$FLOWER_MANAGER" restart --defaults || return $?

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

  resolve_participant_workers || return $?
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
)" || return $?

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
)" || return $?

  if [[ -n "$mode" ]]; then
    publish_prepared_fl_cohort "$mode" || return $?
  fi
}

# Subshell confines temporary-export cleanup traps to this operation.
# Canonical source, retained evidence, and release records are never rewritten.
recover_and_stage_fl_partitions() (
  local repository_root evidence expected candidate extra_vars
  local runtime_root worker

  repository_root="$(cd "$SCRIPT_DIR/../../.." && pwd)" || return $?
  expected="${PARTITION_MANIFEST_SHA256:-}"
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || {
    printf 'ERROR: Missing or invalid pinned partition manifest checksum.\n' >&2
    return 2
  }
  [[ -r "${WORKSHOP_INVENTORY:-}" ]] || {
    printf 'ERROR: Selected workshop inventory is not readable.\n' >&2
    return 2
  }
  [[ "${WORKSHOP_WORKER_GROUP:-}" =~ ^[A-Za-z0-9_.-]+$ ]] || {
    printf 'ERROR: Selected worker group is missing or unsafe.\n' >&2
    return 2
  }
  runtime_root="${WORKSHOP_RUNTIME_ROOT:-/opt/digitafrica/fl-workshop}"
  [[ "$runtime_root" == /* && "$runtime_root" != / ]] || {
    printf 'ERROR: Worker runtime root must be an absolute non-root path.\n' >&2
    return 2
  }

  resolve_participant_workers || return $?
  ((${#WORKSHOP_WORKERS[@]} > 0)) || {
    printf 'ERROR: No participant workers resolved.\n' >&2
    return 2
  }
  for worker in "${WORKSHOP_WORKERS[@]}"; do
    [[ "$worker" =~ ^[A-Za-z0-9_.-]+$ ]] || {
      printf 'ERROR: Unsafe inventory worker identifier.\n' >&2
      return 2
    }
  done

  evidence="$repository_root/data/fl-recovery-manifests/$expected.json"
  if [[ ! -f "$evidence" ]]; then
    evidence="$repository_root/data/fl-recovery/$expected/partition-manifest.json"
  fi
  if [[ ! -f "$evidence" ]]; then
    evidence="$repository_root/data/partitions/partition-manifest.json"
  fi
  [[ -r "$evidence" ]] || {
    printf 'ERROR: Pinned manifest evidence is missing; cannot recover partitions.\n' >&2
    return 2
  }

  # Reject changed evidence or topology before generation or any worker writes.
  python3 - "$evidence" "$expected" "${#WORKSHOP_WORKERS[@]}" <<'PY_VALIDATE'
import hashlib
import json
from pathlib import Path
import sys

raw = Path(sys.argv[1]).read_bytes()
if hashlib.sha256(raw).hexdigest() != sys.argv[2]:
    raise SystemExit("ERROR: Retained evidence checksum mismatch.")
evidence = json.loads(raw)
if type(evidence.get("groups")) is not int or evidence["groups"] != int(sys.argv[3]):
    raise SystemExit("ERROR: Selected worker count differs from pinned recovery evidence.")
PY_VALIDATE
  local validation_status=$?
  ((validation_status == 0)) || return "$validation_status"

  [[ -r "$SCRIPT_DIR/verify_fl_partition_recovery.py" &&
     -r "$repository_root/playbooks/fl-workshop-stage-partitions.yml" ]] || {
    printf 'ERROR: Partition recovery helper or staging playbook is missing.\n' >&2
    return 2
  }
  command -v ansible-playbook >/dev/null || {
    printf 'ERROR: ansible-playbook is not available.\n' >&2
    return 2
  }

  candidate="$(mktemp -d "${TMPDIR:-/tmp}/fl-partition-stage.XXXXXXXX")" || return $?
  trap 'status=$?; trap - EXIT; rm -rf -- "$candidate"; exit "$status"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  mkdir -p "$candidate/data" || return $?

  python3 "$SCRIPT_DIR/verify_fl_partition_recovery.py" \
    --recovery-manifest "$evidence" \
    --expected-manifest-sha256 "$expected" \
    --export-root "$candidate/data/partitions" || return $?

  extra_vars="$(python3 - "$candidate/data" "$WORKSHOP_WORKER_GROUP" \
    "$runtime_root" "${WORKSHOP_WORKERS[@]}" <<'PY_VARS'
import json
import sys

print(json.dumps({
    "fl_data_root": sys.argv[1],
    "workshop_worker_group": sys.argv[2],
    "fl_workshop_client_group": sys.argv[2],
    "fl_silo_runtime_root": sys.argv[3],
    "fl_workshop_client_hosts": sys.argv[4:],
}))
PY_VARS
)" || return $?

  ansible-playbook -i "$WORKSHOP_INVENTORY" \
    "$repository_root/playbooks/fl-workshop-stage-partitions.yml" \
    --tags fl_partition_data \
    --extra-vars "$extra_vars" || return $?
)
