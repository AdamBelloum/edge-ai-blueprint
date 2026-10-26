#!/usr/bin/env bash
# Sourced Cloud Computing SOA grading: run the grading script or the TA audit
# against every group's Module 1 or 2 work, in grading pods on the cluster.
#
# grading-local.py builds each remote step and reads its answer,
# grading-remote.py runs on the control plane and grading-pod.py in the pods.
# Each pod copies one group's workspace from its volume, which it mounts
# read-only; participant servers and files are not changed. Results are written
# under secrets/workshops/grading/, which Git ignores, or CLOUD_SOA_GRADING_RESULTS.

CLOUD_SOA_GRADING_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_SOA_GRADING_LOCAL="$CLOUD_SOA_GRADING_DIR/grading-local.py"
CLOUD_SOA_GRADING_RESULTS="${CLOUD_SOA_GRADING_RESULTS:-$(
  cd -- "$CLOUD_SOA_GRADING_DIR/../../.." && pwd
)/secrets/workshops/grading}"

# Run one step on the control plane; print the answer's key=value lines.
cloud_soa_grading_remote() {
  local operation="$1" run_dir="$2" script output
  shift 2

  script="$(python3 "$CLOUD_SOA_GRADING_LOCAL" script "$operation" \
    --namespace "$DIGITAFRICA_NAMESPACE" --run-dir "$run_dir" "$@")" || return $?
  # A failed step prints its error; receive shows it.
  output="$(run_deployment_remote "$script" 2>&1)" || true
  python3 "$CLOUD_SOA_GRADING_LOCAL" receive "$operation" --run-dir "$run_dir" <<<"$output"
}

cloud_soa_grading_cleanup() {
  local run="$1"

  printf 'Removing grading run %s from the cluster.\n' "$run" >&2
  if ! cloud_soa_grading_remote cleanup "" --run "$run" >/dev/null; then
    printf '%s\n' \
      "Grading run $run could not be removed. Choose a grading entry again: it offers to remove a leftover run." >&2
    return 1
  fi
}

cloud_soa_grading_value() {
  sed -n "s/^$1=//p" <<<"$2" | head -n 1
}

# The end of a run, as its EXIT trap, so also after an error or Ctrl-C: write
# the summary of the groups graded so far, remove the run from the cluster, and
# show the summary or say where the results are.
cloud_soa_grading_finish() {
  local status=$? run="$1" run_dir="$2" removed=true table=""

  # Every step runs, also when nothing can be printed any more, as after the
  # organiser's connection dropped (SIGHUP).
  set +e
  # Before the removal, which can take minutes: a second Ctrl-C ends this trap.
  if [[ -f "$run_dir/run.json" ]] &&
    ! table="$(python3 "$CLOUD_SOA_GRADING_LOCAL" summary --run-dir "$run_dir" 2>&1)"; then
    printf '%s\n' "$table" >&2
    table=""
    ((status != 0)) || status=1
  fi
  if [[ -f "$run_dir/run.json" ]] && ((status == 130)); then
    printf 'The grading run was stopped. Results so far: %s\n' "$run_dir" >&2
  elif [[ -f "$run_dir/run.json" ]] && ((status != 0)); then
    printf 'The grading run did not complete. Results so far: %s\n' "$run_dir" >&2
  fi
  cloud_soa_grading_cleanup "$run" || removed=false
  if ((status == 0)); then
    printf '\n%s\n' "$table"
    [[ "$removed" == true ]] || printf '%s\n' \
      "Every group was graded, but run $run is still in the cluster: choose a grading entry again to remove it." >&2
  fi
  exit "$status"
}

# Start one pod per group, save each group's results as its pod finishes,
# and remove the run from the cluster, also after an error or interruption.
cloud_soa_grading_run() {
  local run="$1" run_dir="$2" module="$3" track="$4" kind="$5"
  local answer remaining deadline attempt pause

  (
    trap 'exit 130' INT HUP TERM
    # Expanded now: the trap runs after this function's variables are gone.
    # shellcheck disable=SC2064
    trap "cloud_soa_grading_finish $(printf '%q' "$run") $(printf '%q' "$run_dir")" EXIT

    answer="$(cloud_soa_grading_remote start "$run_dir" --run "$run" \
      --module "$module" --track "$track" --kind "$kind" \
      --groups "${CLOUD_SOA_GRADING_GROUPS:-}" \
      --parallel "${CLOUD_SOA_GRADING_PARALLEL:-4}" \
      --egress "${CLOUD_SOA_GRADING_EGRESS:-none}" \
      --image "${CLOUD_SOA_GRADING_IMAGE:-}" \
      --audit-dir "${CLOUD_SOA_TA_AUDIT_DIR:-}")" || exit $?
    # Each pod has a deadline; this limits the whole run, should a pod never be collected.
    deadline=$((SECONDS + ${CLOUD_SOA_GRADING_MAX_SECONDS:-21600}))
    while true; do
      remaining="$(cloud_soa_grading_value remaining "$answer")"
      [[ "$remaining" =~ ^[0-9]+$ ]] || exit 1
      ((remaining == 0)) && exit 0
      if ((SECONDS > deadline)); then
        printf 'The grading run is taking too long; stopping it.\n' >&2
        exit 1
      fi
      sleep "${CLOUD_SOA_GRADING_POLL_SECONDS:-15}"
      # A step can be repeated: results are sent again until they are saved.
      attempt=0
      until answer="$(cloud_soa_grading_remote step "$run_dir")"; do
        attempt=$((attempt + 1))
        ((attempt <= 4)) || exit 1
        pause=$((${CLOUD_SOA_GRADING_POLL_SECONDS:-15} * 2 * attempt))
        printf 'No answer from the control plane; trying again in %s s.\n' "$pause" >&2
        sleep "$pause"
      done
    done
  )
}

# Grade every group's work for Cloud Module 1 or 2: "tests" runs the
# assignment's grading script, "audit" the TA audit.
cloud_soa_grade_groups() {
  local module="$1" kind="$2"
  local state lock_run idle track active_module mode host run run_dir what groups network

  case "$module:$kind" in
    1:tests|2:tests) what="the Assignment $module grading script" ;;
    1:audit|2:audit) what="the Assignment $module TA audit" ;;
    *) printf 'Unknown grading request: Module %s, %s.\n' "$module" "$kind" >&2; return 2 ;;
  esac
  case "${CLOUD_SOA_GRADING_EGRESS:-none}" in
    none) network="none: the groups' code cannot reach the internet or the cluster" ;;
    participant) network="the internet, as from participant servers, but not the nodes or the Kubernetes API" ;;
    *)
      printf 'CLOUD_SOA_GRADING_EGRESS must be none or participant, not %s.\n' "$CLOUD_SOA_GRADING_EGRESS" >&2
      return 2
      ;;
  esac
  command -v python3 >/dev/null 2>&1 || {
    printf 'Grading needs python3 on this machine.\n' >&2
    return 2
  }

  print_heading "Cloud Computing SOA Module $module: $what for every group"
  state="$(cloud_soa_grading_remote status "")" || return $?

  # A leftover run is removed first, also during a reset: its pods use the
  # workspaces, so that the reset could not delete them.
  lock_run="$(cloud_soa_grading_value lock_run "$state")"
  if [[ -n "$lock_run" ]]; then
    idle="$(cloud_soa_grading_value lock_idle "$state")"
    printf '%s\n' \
      "Grading run $lock_run ($(cloud_soa_grading_value lock_kind "$state") of Module $(
        cloud_soa_grading_value lock_module "$state"), started $(
        cloud_soa_grading_value lock_started "$state")) is still in the cluster." >&2
    if [[ "$idle" =~ ^[0-9]+$ ]] && ((idle >= 600)); then
      printf 'Nobody has followed it for %s minutes: it was interrupted.\n' "$((idle / 60))" >&2
      confirm "Remove grading run $lock_run" || return 1
    else
      printf '%s\n' \
        'An organiser followed it in the last 10 minutes, so it may still be running.' \
        'Remove it only if nobody runs it: that stops it.' >&2
      # Never answered automatically, as it can stop another organiser's run.
      DIGITAFRICA_ASSUME_YES=false confirm "Remove grading run $lock_run" || return 1
    fi
    cloud_soa_grading_cleanup "$lock_run" || return 1
  fi

  case "$(cloud_soa_grading_value cleanup_status "$state")" in
    in_progress|failed)
      printf '%s\n' \
        'Workshop cleanup is incomplete; the workspaces may be partly deleted.' \
        'Resume the reset before grading.' >&2
      return 1
      ;;
  esac

  groups="$(cloud_soa_grading_value groups "$state")"
  if [[ "$groups" == 0 ]]; then
    printf 'There are no participant workspaces to grade.\n' >&2
    return 1
  fi

  # The active track of this module, unless CLOUD_COMPUTING_SOA_MODE names another.
  active_module="$(cloud_soa_grading_value workshop_module "$state")"
  mode="$(cloud_soa_grading_value mode "$state")"
  if [[ -z "${CLOUD_COMPUTING_SOA_MODE:-}" &&
    "$(cloud_soa_grading_value workshop_type "$state")" == cloud-computing-soa &&
    "$active_module" == "module$module" ]]; then
    track="$mode"
  elif [[ -z "${CLOUD_COMPUTING_SOA_MODE:-}" && ! -t 0 ]]; then
    printf 'Module %s is not the active module: set CLOUD_COMPUTING_SOA_MODE=%s to choose the track.\n' \
      "$module" 'beginner|intermediate|advanced' >&2
    return 2
  else
    track="$("cloud_module${module}_select_mode")" || return $?
  fi
  case "$track" in
    beginner|intermediate|advanced) ;;
    *) printf 'Cannot tell which track to grade (mode: %s).\n' "${track:-unset}" >&2; return 1 ;;
  esac

  if [[ "$active_module" == "module$module" &&
    "$(cloud_soa_grading_value solutions_released "$state")" == true ]]; then
    printf '%s\n' \
      'The reference solutions have been released: groups may have copied them.' \
      'Work that equals the reference solution is marked "solution".' >&2
  fi

  host="$(cloud_soa_grading_value host "$state")"
  run="$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
  run_dir="$CLOUD_SOA_GRADING_RESULTS/${host:-cluster}/$(date -u +%Y%m%d-%H%M%S)-module$module-$kind-$run"
  printf '%s\n' \
    "Track: $track. Groups: ${CLOUD_SOA_GRADING_GROUPS:-all $groups}." \
    "One pod per group, ${CLOUD_SOA_GRADING_PARALLEL:-4} at a time, each with a copy of the group's workspace." \
    "Network: $network." \
    "Participant servers and files are not changed. Results: $run_dir"
  confirm "Start grading" || {
    printf 'No grading run was started.\n'
    return 0
  }

  # The run shows its summary itself, as it also must after Ctrl-C: the
  # organiser menu's own trap ends the menu as soon as the run returns.
  cloud_soa_grading_run "$run" "$run_dir" "$module" "$track" "$kind"
}
