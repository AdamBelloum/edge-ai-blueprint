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

# Forward context to the child without assigning/exporting readonly parent variables.
# The child retains its existing release-record validation.
big_data_spark_credentials_with_context() {
  env \
    DIGITAFRICA_INVENTORY="${DIGITAFRICA_INVENTORY:?Missing inventory}" \
    DIGITAFRICA_DEPLOYMENT_GROUP="${DIGITAFRICA_DEPLOYMENT_GROUP:?Missing control-plane group}" \
    DIGITAFRICA_DEPLOYMENT_WORKER_GROUP="${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:?Missing worker group}" \
    DIGITAFRICA_NAMESPACE="${DIGITAFRICA_NAMESPACE:?Missing namespace}" \
    "$BIG_DATA_SPARK_MODULE_DIR/participant-credentials.sh" "$@"
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

  [[ -x "$BIG_DATA_SPARK_MODULE_DIR/participant-credentials.sh" ]] || {
    printf 'Spark publication blocked: credential verification helper is missing.\n' >&2
    return 2
  }
  # Fresh active-client/export/Secret validation; a successful plan is insufficient.
  big_data_spark_credentials_with_context verify || return $?

  printf '%s\n' \
    'Publish the beginner Spark workspace and reconcile JupyterHub.' \
    'This does not start Spark or establish notebook/submission readiness.' \
    'Existing participant servers are not automatically updated.'
  if ! DIGITAFRICA_ASSUME_YES=false confirm "Publish the Spark beginner workspace for subsequent participant spawns"; then
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


# Secondary tools retain their existing confirmations and runtime safeguards.
big_data_spark_maintenance_menu() {
  local choice
  while true; do
    workshop_ui_heading "Spark / Maintenance and organiser tests"
    printf '%s\n' 'Organiser tools only; these do not establish participant readiness.'
    workshop_ui_section "RUNTIME TOOLS"
    workshop_ui_option 1 "Prepare Spark/Livy pilot assets"
    workshop_ui_option 2 "Build staged Livy image"
    workshop_ui_option 3 "Start staged Spark/Livy pilot"
    workshop_ui_section "COMPUTATION TESTS"
    workshop_ui_option 4 "Test Step 1 - direct Spark"
    workshop_ui_option 5 "Test Step 2 - Livy"
    workshop_ui_section "WORKSPACE RECOVERY"
    workshop_ui_option 6 "Republish Beginner workspace"
    printf '\n'
    workshop_ui_option 0 "Back to Spark"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) big_data_spark_runtime_action prepare ||
           printf 'Spark/Livy runtime preparation did not complete.\n' >&2 ;;
      2) big_data_spark_runtime_action build ||
           printf 'Livy image build did not complete.\n' >&2 ;;
      3) big_data_spark_runtime_action start ||
           printf 'Spark/Livy startup did not complete; inspect before retrying.\n' >&2 ;;
      4) big_data_spark_computation_test direct ||
           printf 'Direct Spark test did not complete; inspect before retrying.\n' >&2 ;;
      5) big_data_spark_computation_test livy ||
           printf 'Livy test did not complete; inspect before retrying.\n' >&2 ;;
      6) big_data_spark_activate_selected_mode beginner ||
           printf 'Spark beginner publication did not complete.\n' >&2 ;;
      0) return 0 ;;
      *) printf 'Choose a value from 0 through 6.\n' >&2 ;;
    esac
  done
}

run_big_data_spark_menu() {
  local choice
  while true; do
    workshop_ui_heading "Big Data / Spark Beginner - work-in-progress"
    workshop_ui_section "PREPARE WORKSHOP"
    workshop_ui_option 1 "Stage 1 - direct submission workflow"
    workshop_ui_option 2 "Prepare Step 2 - work-in-progress"
    printf '\n%s\n' \
      'Step 1 opens the ordered workflow and requires staged-credential verification; publication alone is not workshop readiness.' \
      'Step 2 integrated preparation is not implemented; selecting it performs no changes.'
    workshop_ui_section "STATUS AND TOOLS"
    workshop_ui_option 3 "Show workshop status"
    workshop_ui_option 4 "Maintenance and organiser tests"
    printf '\n'
    workshop_ui_option 0 "Back to Big Data"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) big_data_spark_stage1_menu ||
           printf 'Spark Stage 1 workflow did not complete.\n' >&2 ;;
      2) big_data_spark_future_unavailable 'Step 2 integrated preparation' ||
           printf 'Spark Step 2 preparation is work-in-progress; no changes performed.\n' >&2 ;;
      3) big_data_spark_show_status ||
           printf 'Workshop selection status could not be retrieved.\n' >&2 ;;
      4) big_data_spark_maintenance_menu ;;
      0) return 0 ;;
      *) printf 'Choose a value from 0 through 4.\n' >&2 ;;
    esac
  done
}


# Stage 1 integration only. Legacy maintenance actions remain unchanged.
# Primary option 1 delegates here; mutating actions retain helper confirmations.
big_data_spark_stage1_preflight() {
  local name value helper
  for name in DIGITAFRICA_INVENTORY DIGITAFRICA_DEPLOYMENT_GROUP \
              DIGITAFRICA_DEPLOYMENT_WORKER_GROUP DIGITAFRICA_NAMESPACE; do
    value="${!name:-}"
    [[ -n "$value" ]] || {
      printf 'Stage 1 blocked: missing %s in the selected context.\n' "$name" >&2
      return 2
    }
  done
  for name in DIGITAFRICA_DEPLOYMENT_GROUP DIGITAFRICA_DEPLOYMENT_WORKER_GROUP; do
    value="${!name}"
    [[ "$value" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || {
      printf 'Stage 1 blocked: invalid inventory group in %s.\n' "$name" >&2
      return 2
    }
  done
  [[ ${#DIGITAFRICA_NAMESPACE} -le 63 &&
     "$DIGITAFRICA_NAMESPACE" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || {
    printf 'Stage 1 blocked: invalid namespace.\n' >&2
    return 2
  }
  command -v ansible-playbook >/dev/null 2>&1 || {
    printf 'Stage 1 blocked: ansible-playbook is required.\n' >&2
    return 2
  }
  for helper in "$BIG_DATA_COHORT_WORKFLOW" \
                "$BIG_DATA_SPARK_MODULE_DIR/participant-direct-runtime.sh" \
                "$BIG_DATA_SPARK_MODULE_DIR/participant-credentials.sh"; do
    [[ -x "$helper" ]] || {
      printf 'Stage 1 blocked: missing executable helper: %s\n' "$helper" >&2
      return 2
    }
  done
  ensure_workshop_activation_allowed big-data || return $?
  "$BIG_DATA_COHORT_WORKFLOW" require-complete || return $?
  printf 'Stage 1 context/cohort checks passed: namespace=%s, control-group=%s, worker-group=%s\n' \
    "$DIGITAFRICA_NAMESPACE" "$DIGITAFRICA_DEPLOYMENT_GROUP" \
    "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"
  printf '%s\n' 'This does not verify bind addresses, host capacity or participant execution.'
}

big_data_spark_stage1_action() {
  local action="${1:-}" rc
  case "$action" in
    check|prepare|start|credentials) ;;
    publish)
      # Canonical publisher owns cohort checks, verification and confirmation.
      big_data_spark_activate_selected_mode beginner
      return $? ;;
    *) printf 'Unsupported Stage 1 action: %s\n' "$action" >&2; return 2 ;;
  esac

  big_data_spark_stage1_preflight || return $?
  case "$action" in
    check) return 0 ;;
    prepare|start)
      # The standalone helper owns explicit confirmation and startup policy apply.
      if "$BIG_DATA_SPARK_MODULE_DIR/participant-direct-runtime.sh" "$action"; then
        printf 'Stage 1 %s helper completed; participant readiness remains unverified.\n' "$action"
      else
        rc=$?
        printf 'Stage 1 %s failed/cancelled (status %s). Inspect current state before retrying.\n' \
          "$action" "$rc" >&2
        return "$rc"
      fi
      ;;
    credentials)
      # A failed plan prevents apply. Apply repeats validation and owns confirmation.
      big_data_spark_credentials_with_context plan || return $?
      if big_data_spark_credentials_with_context apply; then
        printf '%s\n' 'Credential staging completed; publication and participant validation are still required.'
      else
        rc=$?
        printf 'Credential staging failed/cancelled (status %s); no readiness claim.\n' "$rc" >&2
        return "$rc"
      fi
      ;;
  esac
}

big_data_spark_stage1_menu() {
  local choice
  while true; do
    workshop_ui_heading 'Spark / Stage 1 - Direct submission'
    printf 'Target: control=%s | workers=%s | namespace=%s\n' \
      "${DIGITAFRICA_DEPLOYMENT_GROUP:-unset}" \
      "${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:-unset}" \
      "${DIGITAFRICA_NAMESPACE:-unset}"
    printf '%s\n' \
      'Integration in progress. Participant readiness is NOT validated.' \
      'Follow the numbered order. Reopening this menu does not prove prior completion.'
    workshop_ui_section 'ORDERED STEP 1 WORKFLOW'
    workshop_ui_option 1 'Check selected context and participant cohort'
    workshop_ui_option 2 'Prepare direct runtime and credential exports'
    workshop_ui_option 3 'Start direct runtime and apply network access'
    workshop_ui_option 4 'Plan, confirm and stage participant credentials'
    workshop_ui_option 5 'Publish Step 1 after credential verification'
    workshop_ui_section 'INSPECTION'
    workshop_ui_option 7 'Show existing workshop selection status (not readiness)'
    printf '%s\n' \
      'Safe non-destructive stop is not integrated; teardown is not a normal stop.' \
      'Stage 2 is outside this workflow; no Livy actions are executed here.'
    workshop_ui_option 0 'Back to Spark'
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) big_data_spark_stage1_action check || printf 'Stage 1 preflight did not complete.\n' >&2 ;;
      2) big_data_spark_stage1_action prepare || printf 'Stage 1 preparation did not complete.\n' >&2 ;;
      3) big_data_spark_stage1_action start || printf 'Stage 1 startup did not complete.\n' >&2 ;;
      4) big_data_spark_stage1_action credentials || printf 'Stage 1 credential staging did not complete.\n' >&2 ;;
      5) big_data_spark_stage1_action publish || printf 'Stage 1 publication did not complete; inspect selection and reconciliation state.\n' >&2 ;;
      7) big_data_spark_show_status || printf 'Selection status could not be read.\n' >&2 ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, 4, 5 or 7.\n' >&2 ;;
    esac
  done
}
