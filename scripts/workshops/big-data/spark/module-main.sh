#!/usr/bin/env bash
# Spark module workflow, sourced by the Big Data course dispatcher.
# Asset publication remains separate from runtime preparation and startup.

BIG_DATA_SPARK_MODULE_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
BIG_DATA_SPARK_WORKSPACE_HELPER="$BIG_DATA_SPARK_MODULE_DIR/../prepare-spark-workspace.sh"
BIG_DATA_COHORT_WORKFLOW="$BIG_DATA_SPARK_MODULE_DIR/../../identity/cohort-workshop.sh"

big_data_spark_future_unavailable() {
  printf 'Spark %s is unavailable: implementation is reserved for a future sprint. No changes performed.\n' \
    "$1" >&2
  return 2
}

# Return the selected mode on stdout; keep prompts on stderr.
big_data_spark_select_mode() {
  local choice

  if [[ -n "${BIG_DATA_SPARK_MODE:-}" ]]; then
    case "$BIG_DATA_SPARK_MODE" in
      beginner|advanced) printf '%s\n' "$BIG_DATA_SPARK_MODE"; return 0 ;;
      *) printf 'BIG_DATA_SPARK_MODE must be beginner or advanced.\n' >&2; return 2 ;;
    esac
  fi

  [[ -t 0 ]] || {
    printf 'Use an interactive terminal or BIG_DATA_SPARK_MODE=beginner.\n' >&2
    return 2
  }

  while true; do
    {
      workshop_ui_heading "Spark / Teaching mode"
      workshop_ui_option 1 "Beginner - guided notebook"
      workshop_ui_option 2 "Advanced: TODO - not implemented; future sprint"
      workshop_ui_prompt
    } >&2
    read -r choice || return 2
    case "$choice" in
      1) printf 'beginner\n'; return 0 ;;
      2) printf 'advanced\n'; return 0 ;;
      *) printf 'Choose 1 or 2.\n' >&2 ;;
    esac
  done
}

# Asset preparation only: no activation, runtime preparation or account changes.
big_data_spark_prepare_workspace() {
  [[ -x "$BIG_DATA_SPARK_WORKSPACE_HELPER" ]] || {
    printf 'Missing executable Spark workspace helper: %s\n' \
      "$BIG_DATA_SPARK_WORKSPACE_HELPER" >&2
    return 1
  }
  "$BIG_DATA_SPARK_WORKSPACE_HELPER"
}

big_data_spark_activate_selected_mode() {
  local mode="$1"

  case "$mode" in
    beginner) ;;
    advanced) big_data_spark_future_unavailable 'advanced activation'; return $? ;;
    *) printf 'Unsupported Spark mode: %s\n' "$mode" >&2; return 2 ;;
  esac

  [[ -x "$BIG_DATA_COHORT_WORKFLOW" ]] || {
    printf 'Missing executable participant cohort workflow: %s\n' \
      "$BIG_DATA_COHORT_WORKFLOW" >&2
    return 1
  }

  "$BIG_DATA_COHORT_WORKFLOW" require-complete || return $?
  ensure_workshop_activation_allowed big-data || return $?

  printf '%s\n' \
    'Publish the beginner Spark workspace and reconcile JupyterHub.' \
    'This does not start Spark or establish notebook/submission readiness.' \
    'Existing participant servers are not automatically updated.'
  if ! "${ASSUME_YES:-false}" &&
    ! confirm "Publish the Spark beginner workspace for subsequent participant spawns"; then
    log 'No Spark workspace publication was performed.'
    return 0
  fi

  big_data_spark_prepare_workspace || return $?

  # Spark source delivery is enabled when reconciliation reads this selection.
  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"big-data","workshop_module":"spark","mode":"beginner","solutions_released":"false"}}'
REMOTE
)" || return $?

  if run_application_reconciliation; then
    printf '%s\n' \
      'Spark beginner workspace publication completed for subsequent participant spawns.' \
      'Spark runtime connectivity, spark-submit and execution readiness remain unverified.'
  else
    printf '%s\n' \
      'Spark selection was written, but application reconciliation failed.' \
      'Do not direct participants to spawn yet. Correct the failure and rerun reconcile-applications.' >&2
    return 1
  fi
}

big_data_spark_activate() {
  local mode
  mode="$(big_data_spark_select_mode)" || return $?
  big_data_spark_activate_selected_mode "$mode"
}

big_data_spark_release_solutions() {
  big_data_spark_future_unavailable 'advanced solution release'
}

big_data_spark_show_status() {
  print_heading "Big Data — Spark workshop selection"
  check_workshop_runtime_state || return $?
  printf '%s\n' \
    'This reports workshop selection and participant workspace presence only.' \
    'It does not validate Spark containers, asset delivery or distributed execution.'
}

run_big_data_spark_menu() {
  local choice
  while true; do
    workshop_ui_heading "Big Data / Spark Beginner"
    workshop_ui_section "PREPARATION"
    workshop_ui_option 1 "Prepare teaching assets: no activation or runtime startup"
    workshop_ui_section "CHECKS"
    workshop_ui_option 2 "Show workshop selection status: not asset-delivery or execution validation"
    workshop_ui_section "PUBLICATION"
    workshop_ui_option 3 "Publish Beginner workshop: reconciles JupyterHub for new spawns; execution not validated"
    workshop_ui_option 4 "Publish Advanced workshop: TODO - not implemented"
    workshop_ui_section "AFTER THE WORKSHOP"
    workshop_ui_option 5 "Release advanced reference solutions - TODO: not implemented"
    printf '\n'
    workshop_ui_option 0 "Back to Big Data"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) big_data_spark_prepare_workspace ||
           printf 'Spark asset preparation did not complete.\n' >&2 ;;
      3) big_data_spark_activate_selected_mode beginner ||
           printf 'Spark beginner publication did not complete.\n' >&2 ;;
      4) big_data_spark_activate_selected_mode advanced ||
           printf 'Spark advanced publication was not performed.\n' >&2 ;;
      5) big_data_spark_release_solutions ||
           printf 'Spark solution release was not performed.\n' >&2 ;;
      2) big_data_spark_show_status ||
           printf 'Workshop selection status could not be retrieved.\n' >&2 ;;
      0) return 0 ;;
      *) printf 'Choose a value from 0 through 5.\n' >&2 ;;
    esac
  done
}
