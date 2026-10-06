#!/usr/bin/env bash
#
# Cloud Computing SOA organiser workflow.
#
# Sourced by the Cloud Computing SOA controller after organizer-main.sh has
# loaded shared context, common helpers, and organizer-runtime.sh.

CLOUD_COMPUTING_SOA_MODULE1_NAME="Cloud Computing SOA — Module 1: REST API"
CLOUD_COMPUTING_SOA_COHORT_WORKFLOW="${CLOUD_COMPUTING_SOA_COHORT_WORKFLOW:-$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd
)/identity/cohort-workshop.sh}"

cloud_module1_require_complete_participant_cohort() {
  if [[ ! -x "$CLOUD_COMPUTING_SOA_COHORT_WORKFLOW" ]]; then
    printf 'Missing executable participant cohort workflow: %s\n' \
      "$CLOUD_COMPUTING_SOA_COHORT_WORKFLOW" >&2
    return 1
  fi

  "$CLOUD_COMPUTING_SOA_COHORT_WORKFLOW" require-complete
}

cloud_module1_select_mode() {
  local choice

  if [[ -n "${CLOUD_COMPUTING_SOA_MODE:-}" ]]; then
    case "$CLOUD_COMPUTING_SOA_MODE" in
      beginner|advanced)
        printf '%s\n' "$CLOUD_COMPUTING_SOA_MODE"
        return 0
        ;;
      *)
        printf '%s\n' \
          'CLOUD_COMPUTING_SOA_MODE must be either beginner or advanced.' >&2
        return 2
        ;;
    esac
  fi

  [[ -t 0 ]] || {
    printf '%s\n' \
      'Cloud Module 1 activation requires an interactive terminal or CLOUD_COMPUTING_SOA_MODE=beginner|advanced.' >&2
    return 2
  }

  while true; do
    printf '\n%s\n\n' "$CLOUD_COMPUTING_SOA_MODULE1_NAME" >&2
    printf '%s\n' \
      '  1) Beginner — guided Flask REST API implementation' \
      '  2) Advanced — TODO-based Flask REST API implementation' >&2
    printf 'Selection: ' >&2
    read -r choice

    case "$choice" in
      1) printf '%s\n' beginner; return 0 ;;
      2) printf '%s\n' advanced; return 0 ;;
      *) printf 'Choose 1 or 2.\n' >&2 ;;
    esac
  done
}

cloud_module1_remote_status_script() {
  printf 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  cat <<'REMOTE_STATUS'
set -euo pipefail

check_track() {
  local track="$1" configmap="$2"
  local asset_key asset checksum manifest_input=""

  shift 2

  if ! k3s kubectl -n "$namespace" get configmap "$configmap" >/dev/null 2>&1; then
    printf 'cloud_module1_%s_configmap_status=absent\n' "$track"
    return
  fi

  for asset_key in "$@"; do
    asset="$(
      k3s kubectl -n "$namespace" get configmap "$configmap" \
        -o jsonpath="{.data.${asset_key//./\\.}}"
    )"

    if [[ -z "$asset" ]]; then
      printf 'cloud_module1_%s_configmap_status=placeholder\n' "$track"
      printf 'cloud_module1_%s_missing_asset=%s\n' "$track" "$asset_key"
      return
    fi

    checksum="$(printf '%s' "$asset" | sha256sum | awk '{print $1}')"
    manifest_input+="${asset_key}:${checksum}"$'\n'
  done

  printf 'cloud_module1_%s_configmap_status=deployed\n' "$track"
  printf '%s' "$manifest_input" | sha256sum | \
    awk "{print \"cloud_module1_${track}_configmap_sha256=\" \$1}"
}

state_value() {
  local key="$1"

  k3s kubectl -n "$namespace" get configmap digitafrica-workshop-state \
    -o jsonpath="{.data.${key}}" 2>/dev/null || true
}

check_track beginner \
  digitafrica-notebooks-cloud-computing-soa-module1-beginner \
  app.py \
  upstream-participants-guide.md

check_track advanced \
  digitafrica-notebooks-cloud-computing-soa-module1-advanced \
  app.py \
  upstream-participants-guide.md

check_track solutions \
  digitafrica-notebooks-cloud-computing-soa-module1-solutions \
  app.py

check_track tests \
  digitafrica-notebooks-cloud-computing-soa-module1-tests \
  read_from.csv \
  test_api.py

printf 'workshop_type=%s\n' "$(state_value workshop_type)"
printf 'workshop_mode=%s\n' "$(state_value mode)"
printf 'solutions_released=%s\n' "$(state_value solutions_released)"
REMOTE_STATUS
}

cloud_module1_show_status() {
  print_heading "$CLOUD_COMPUTING_SOA_MODULE1_NAME deployment status"
  run_deployment_remote "$(cloud_module1_remote_status_script)"
  cat <<'STATUS_MESSAGE'

Application reconciliation deploys beginner, advanced, protected-solution, and
shared-test ConfigMaps. Activation copies only the selected teaching track and
shared tests when a participant next spawns a JupyterHub server.

Reference solution app.py is copied only after an explicit organiser release,
and only for the active advanced track.
STATUS_MESSAGE
}

cloud_module1_check_activation_readiness() {
  local track="$1"
  local status_output

  status_output="$(cloud_module1_show_status)"
  printf '%s\n' "$status_output"

  if ! grep -Fq "cloud_module1_${track}_configmap_status=deployed" <<<"$status_output" ||
    ! grep -Fq "cloud_module1_tests_configmap_status=deployed" <<<"$status_output"; then
    printf '%s\n' \
      "Cloud Module 1 ${track} activation is not ready." \
      'Run reconcile-applications before assigning Cloud Module 1 to participants.' >&2
    return 1
  fi

  printf '%s\n' \
    "Cloud Module 1 ${track} activation readiness passed." \
    'Shared tests are available; solutions remain protected until explicit release.'
}

cloud_module1_set_workshop_state() {
  local mode="$1"

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"cloud-computing-soa","introduction_to_ai_module":"module1","mode":"${mode}","solutions_released":"false"}}'
REMOTE
)"
  printf '%s\n' \
    "Cloud Module 1 (${mode}) is now active for subsequently spawned participant servers."
}

cloud_module1_activate_selected_mode() {
  local mode="$1"

  cloud_module1_require_complete_participant_cohort || return $?
  ensure_workshop_activation_allowed cloud-computing-soa || return $?
  cloud_module1_check_activation_readiness "$mode" || return $?
  cloud_module1_set_workshop_state "$mode"
}

cloud_module1_activate() {
  local mode

  mode="$(cloud_module1_select_mode)" || return $?
  cloud_module1_activate_selected_mode "$mode"
}

cloud_module1_release_solutions() {
  print_heading "Release $CLOUD_COMPUTING_SOA_MODULE1_NAME solutions"
  printf '%s\n' \
    'This is a one-way organiser action for subsequently spawned participant servers.' \
    'Existing participant servers and files are not modified.' \
    'It is available only while Cloud Module 1 advanced mode is active.'

  if ! "${ASSUME_YES:-false}" &&
    ! confirm "Release Cloud Module 1 reference solution after the workshop"; then
    log 'No Cloud Module 1 solution release was performed.'
    return 0
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail

workshop_type="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}')"
mode="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

if [ "\$workshop_type" != "cloud-computing-soa" ] || [ "\$mode" != "advanced" ]; then
  printf '%s\n' \
    'Cloud Module 1 solutions can be released only while advanced mode is active.' \
    "Current state: workshop_type=\${workshop_type:-unset}, mode=\${mode:-unset}" >&2
  exit 1
fi

solution_app="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-notebooks-cloud-computing-soa-module1-solutions \
  -o jsonpath='{.data.app\.py}')"
if [ -z "\$solution_app" ]; then
  printf '%s\n' \
    'Cloud Module 1 solutions ConfigMap does not contain app.py.' \
    'Run reconcile-applications before releasing solutions.' >&2
  exit 1
fi

k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"solutions_released":"true"}}'

printf '%s\n' 'Cloud Module 1 solutions released for subsequently spawned participant servers.'
REMOTE
)"

  cloud_module1_show_status
}

run_cloud_computing_soa_menu() {
  local choice

  while true; do
    printf '\n%s\n\n' "$CLOUD_COMPUTING_SOA_MODULE1_NAME"
    printf '%s\n' \
      '  1) Check activation readiness' \
      '  2) Activate beginner track' \
      '  3) Activate advanced TODO track' \
      '  4) Release advanced reference solution' \
      '  5) Show deployment status' \
      '  0) Back'
    printf '\nSelection: '
    read -r choice

    case "$choice" in
      1)
        if ! cloud_module1_check_activation_readiness \
          "$(cloud_module1_select_mode)"; then
          printf '%s\n' \
            'Readiness check did not pass. No workshop state was changed; returning to the Cloud menu.' >&2
        fi
        ;;
      2)
        if ! cloud_module1_activate_selected_mode beginner; then
          printf '%s\n' \
            'Beginner activation did not complete. No workshop state was changed; returning to the Cloud menu.' >&2
        fi
        ;;
      3)
        if ! cloud_module1_activate_selected_mode advanced; then
          printf '%s\n' \
            'Advanced activation did not complete. No workshop state was changed; returning to the Cloud menu.' >&2
        fi
        ;;
      4)
        if ! cloud_module1_release_solutions; then
          printf '%s\n' 'Solution release did not complete; returning to the Cloud menu.' >&2
        fi
        ;;
      5)
        if ! cloud_module1_show_status; then
          printf '%s\n' 'Status retrieval did not complete; returning to the Cloud menu.' >&2
        fi
        ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, 4, or 5.\n' >&2 ;;
    esac
  done
}
