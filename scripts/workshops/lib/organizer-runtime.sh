#!/usr/bin/env bash
# Shared organiser runtime safeguards.
#
# Source this only after workshop-context.sh and scripts/lib/common.sh have been
# loaded. The caller must therefore provide DIGITAFRICA_NAMESPACE and
# run_deployment_remote.

workshop_runtime_fail() {
  printf 'ERROR: %s\n' "$*" >&2
  return 2
}

check_workshop_runtime_state() {
  local remote_script
  local state_output

  printf -v remote_script 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  remote_script+="$(cat <<'REMOTE'
set -euo pipefail

workshop_type="$(k3s kubectl -n "$namespace" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}')"

case "$workshop_type" in
  none|introduction-to-ai|federated-learning|cloud-computing-soa) ;;
  *)
    printf 'workshop_type=invalid\n'
    printf 'participant_workspace_status=unknown\n'
    exit 0
    ;;
esac

pvc_names="$(k3s kubectl -n "$namespace" get pvc \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"

if grep -Eq '^claim-group-[0-9]+---' <<<"$pvc_names"; then
  workspace_status=present
else
  workspace_status=clean
fi

printf 'workshop_type=%s\n' "$workshop_type"
printf 'participant_workspace_status=%s\n' "$workspace_status"
REMOTE
)"

  state_output="$(run_deployment_remote "$remote_script")" || return $?
  printf '%s\n' "$state_output"

  WORKSHOP_TYPE="$(sed -n 's/.*workshop_type=\([^[:space:]]*\).*/\1/p' <<<"$state_output")"
  PARTICIPANT_WORKSPACE_STATUS="$(
    sed -n 's/.*participant_workspace_status=\([^[:space:]]*\).*/\1/p' <<<"$state_output"
  )"

  case "$WORKSHOP_TYPE" in
    none|introduction-to-ai|federated-learning|cloud-computing-soa) ;;
    *)
      workshop_runtime_fail \
        'Could not determine the active workshop type. Deploy the current workshop state migration first.'
      return $?
      ;;
  esac

  case "$PARTICIPANT_WORKSPACE_STATUS" in
    clean|present) ;;
    *)
      workshop_runtime_fail \
        'Could not determine whether participant workspaces exist.'
      return $?
      ;;
  esac
}

ensure_workshop_activation_allowed() {
  local requested_type="$1"

  case "$requested_type" in
    introduction-to-ai|federated-learning|cloud-computing-soa) ;;
    *)
      workshop_runtime_fail "Unsupported workshop type: $requested_type"
      return $?
      ;;
  esac

  check_workshop_runtime_state || return $?

  if [[ "$WORKSHOP_TYPE" == "$requested_type" || "$WORKSHOP_TYPE" == none ]]; then
    return 0
  fi

  if [[ "$PARTICIPANT_WORKSPACE_STATUS" == clean ]]; then
    printf '%s\n' \
      "Changing workshop selection from $WORKSHOP_TYPE to $requested_type." \
      'No participant workspace exists; participant identities and credentials are preserved.'
    return 0
  fi

  workshop_runtime_fail \
    "Cannot change the active workshop from $WORKSHOP_TYPE to $requested_type while participant workspaces exist. Use Reset active workshop cycle → Reset active workshop and participant cohort first."
}
