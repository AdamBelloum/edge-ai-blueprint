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

# Organiser-only runtime lifecycle: never a participant submission interface.
# Startup supports exactly one Spark worker container per selected group VM.
big_data_spark_runtime_action() {
  local action="${1:-}" helper prompt rc
  local -a args=()
  case "$action" in
    prepare)
      helper="$BIG_DATA_SPARK_MODULE_DIR/prepare-runtime.sh"
      args=(livy 1)
      prompt="Prepare Spark/Livy assets on selected worker VMs (downloads/pulls; no build or startup)"
      ;;
    build)
      helper="$BIG_DATA_SPARK_MODULE_DIR/build-livy-image.sh"
      prompt="Build the staged locked Livy image on selected worker VMs (consumes VM resources; no startup)"
      ;;
    start)
      helper="$BIG_DATA_SPARK_MODULE_DIR/start-livy-runtime.sh"
      prompt="Start the staged one-worker Spark/Livy pilot on selected worker VMs (consumes VM resources)"
      ;;
    *) printf 'Unsupported Spark runtime action: %s\n' "$action" >&2; return 2 ;;
  esac
  [[ -x "$helper" ]] || {
    printf 'Missing executable Spark runtime helper: %s\n' "$helper" >&2
    return 1
  }
  # Reuse the existing cleanup/selection safeguard; do not bypass reset markers.
  ensure_workshop_activation_allowed big-data || return $?
  printf '%s\n' \
    'Organiser runtime operation only: participant accounts and publication are unchanged.' \
    'This operation does not approve participant submission or concurrency.'
  # Runtime resource operations always require their own confirmation.
  if ! DIGITAFRICA_ASSUME_YES=false confirm "$prompt"; then
    printf 'Spark runtime %s was not performed.\n' "$action"
    return 0
  fi
  if "$helper" "${args[@]}"; then
    printf 'Spark runtime %s helper completed successfully.\n' "$action"
    printf '%s\n' 'Participant launch commands and execution readiness remain unverified.'
  else
    rc=$?
    printf 'Spark runtime %s failed (status %s). Inspect before retrying; runtime artifacts or containers may remain.\n' \
      "$action" "$rc" >&2
    return "$rc"
  fi
}

# Organiser-only computation checks. No participant submission interface.
# Subshell isolates test execution; reuse the loaded organiser context.
big_data_spark_computation_test() (
  local step="${1:-}" helper host rc
  case "$step" in
    direct) helper="$BIG_DATA_SPARK_MODULE_DIR/step1-direct/test-runtime.sh" ;;
    livy) helper="$BIG_DATA_SPARK_MODULE_DIR/step2-livy/test-runtime.sh" ;;
    *) printf 'Unsupported computation test.\n' >&2; return 2 ;;
  esac
  [[ -x "$helper" ]] || { printf 'Missing executable test helper: %s\n' "$helper" >&2; return 2; }
  ensure_workshop_activation_allowed big-data || return $?
  # The organiser has already loaded context and may have readonly variables.
  # Do not source or initialise it again in this inherited subshell.
  # The standalone helper loads its own context in a fresh Bash process.
  [[ -n "${DIGITAFRICA_INVENTORY:-}" && -n "${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:-}" ]] || {
    printf 'Missing inventory context; no computation started.\n' >&2; return 2
  }
  command -v ansible-inventory >/dev/null && command -v python3 >/dev/null || {
    printf 'ansible-inventory and python3 are required; no computation started.\n' >&2; return 2
  }
  printf '%s\n' 'Organiser-only test, one VM at a time. This does not establish participant access.'
  read -r -p 'Worker inventory hostname for this test [tier2-worker-1]: ' host || return 2
  host="${host:-tier2-worker-1}"
  [[ "$host" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || {
    printf 'Invalid hostname; no computation started.\n' >&2; return 2
  }
  # --limit accepts groups too. Verify exact host membership before confirmation.
  # Inventory variables/secrets stay in the pipe; never display or save the JSON.
  if ! (
    set -o pipefail
    ansible-inventory -i "$DIGITAFRICA_INVENTORY" --list | python3 -c '
import json, sys
try:
    inventory = json.load(sys.stdin)
    host, group = sys.argv[1:]
    seen = set()
    def members(name):
        if name in seen:
            return set()
        seen.add(name)
        node = inventory.get(name, {})
        result = set(node.get("hosts", []))
        for child in node.get("children", []):
            result.update(members(child))
        return result
    valid = host not in inventory and host in members(group)
except Exception:
    valid = False
sys.exit(0 if valid else 2)
' "$host" "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"
  ); then
    printf 'Expected an exact host in the selected worker group, not a group or unknown host. No computation started.\n' >&2
    return 2
  fi
  # Always confirm; temporarily disable DIGITAFRICA_ASSUME_YES for this prompt.
  if ! DIGITAFRICA_ASSUME_YES=false confirm "Run organiser-only $step computation test on $host; inspect results and cleanup before continuing"; then
    printf 'No computation test was performed.\n'; return 0
  fi
  if "$helper" --limit "$host"; then
    printf '%s\n' \
      'Organiser computation helper completed successfully; inspect its result and cleanup evidence above.' \
      'Participant launch commands and access remain unverified.'
  else
    rc=$?
    printf 'Computation test failed (status %s). Inspect owned application/session and client cleanup before retrying.\n' "$rc" >&2
    return "$rc"
  fi
)

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
    workshop_ui_section "ORGANISER RUNTIME — NOT PARTICIPANT SUBMISSION"
    workshop_ui_option 6 "Prepare Spark/Livy pilot assets: one worker per VM; no startup"
    workshop_ui_option 7 "Build staged locked Livy image: no startup"
    workshop_ui_option 8 "Start staged Spark/Livy pilot: participant execution not validated"
    workshop_ui_section "ORGANISER COMPUTATION TESTS — ONE VM AT A TIME"
    workshop_ui_option 9 "Test Step 1 direct Spark: organiser-only; verify results and cleanup"
    workshop_ui_option 10 "Test Step 2 Livy: organiser-only; verify results and owned-session cleanup"
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
      6) big_data_spark_runtime_action prepare ||
           printf 'Spark/Livy runtime preparation did not complete.\n' >&2 ;;
      7) big_data_spark_runtime_action build ||
           printf 'Livy image build did not complete.\n' >&2 ;;
      8) big_data_spark_runtime_action start ||
           printf 'Spark/Livy startup did not complete; inspect before retrying.\n' >&2 ;;
      9) big_data_spark_computation_test direct ||
           printf 'Direct Spark test did not complete; inspect before retrying.\n' >&2 ;;
      10) big_data_spark_computation_test livy ||
           printf 'Livy test did not complete; inspect before retrying.\n' >&2 ;;
      0) return 0 ;;
      *) printf 'Choose a value from 0 through 10.\n' >&2 ;;
    esac
  done
}
