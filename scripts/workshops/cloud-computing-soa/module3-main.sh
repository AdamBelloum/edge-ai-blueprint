#!/usr/bin/env bash
# Sourced Module 3 controller: local checks and guarded teaching-file delivery.

CLOUD_MODULE3_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_MODULE3_LOCAL_HELPER="$CLOUD_MODULE3_DIR/module3-local.sh"

cloud_module3_status() {
  printf '%s\n' \
    'Cloud Computing SOA — Module 3: Containerization and Orchestration' \
    'Available actions: local checks, deployed readiness/status, publication and solution release.' \
    'Teaching-file delivery is integrated; deployed readiness must pass before publication.' \
    'Docker/Compose and Kubernetes exercise-runtime readiness is NOT VALIDATED.' \
    'This status does not inspect deployed assets or verify runtime readiness.' \
    'No infrastructure, participant accounts or active workshop state was modified.'
}

cloud_module3_check() {
  local track

  [[ -r "$CLOUD_MODULE3_LOCAL_HELPER" ]] || {
    printf 'ERROR: Missing Module 3 local helper: %s\n' \
      "$CLOUD_MODULE3_LOCAL_HELPER" >&2
    return 1
  }

  for track in beginner intermediate advanced solutions; do
    printf '\n=== Module 3 local check: %s ===\n' "$track"
    bash "$CLOUD_MODULE3_LOCAL_HELPER" check "$track" || return $?
  done

  printf '\n%s\n' \
    'Local checks passed for all tracks; service and deployment readiness remain unverified.'
}

run_cloud_module3_menu() {
  local choice mode
  while true; do
    workshop_ui_heading "Cloud SOA / Module 3 - Containerization and Orchestration"
    workshop_ui_warning "Docker/Compose and Kubernetes runtime NOT VALIDATED."
    workshop_ui_section "CHECKS"
    workshop_ui_option 1 "Check local assets - all levels"
    workshop_ui_option 2 "Show integration status - offline"
    workshop_ui_option 3 "Check publication readiness"
    workshop_ui_option 4 "Show deployed delivery status"
    workshop_ui_section "PUBLICATION"
    workshop_ui_option 5 "Publish Beginner workshop: teaching files only; runtime NOT VALIDATED"
    workshop_ui_option 6 "Publish Intermediate workshop: learner TODO teaching files; runtime NOT VALIDATED"
    workshop_ui_option 7 "Publish Advanced workshop: specification and Module 2 services; runtime NOT VALIDATED"
    workshop_ui_section "AFTER THE WORKSHOP"
    workshop_ui_option 8 "Release reference solutions: intermediate or advanced track"
    printf '\n'
    workshop_ui_option 0 "Back to Cloud Computing SOA"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) cloud_module3_check || printf 'Local checks failed.\n' >&2 ;;
      2) cloud_module3_status ;;
      3)
        if mode="$(cloud_module3_select_mode)"; then
          cloud_module3_check_activation_readiness "$mode" ||
            printf 'Delivery readiness check failed.\n' >&2
        fi
        ;;
      5) cloud_module3_activate_selected_mode beginner ||
           printf 'Beginner publication did not complete.\n' >&2 ;;
      6) cloud_module3_activate_selected_mode intermediate ||
           printf 'Intermediate publication did not complete.\n' >&2 ;;
      7) cloud_module3_activate_selected_mode advanced ||
           printf 'Advanced publication did not complete.\n' >&2 ;;
      8) cloud_module3_release_solutions ||
           printf 'Solution release did not complete.\n' >&2 ;;
      4) cloud_module3_show_deployment_status ||
           printf 'Deployed status check failed.\n' >&2 ;;
      0) return 0 ;;
      *) printf 'Choose 0 through 8.\n' >&2 ;;
    esac
  done
}

# BEGIN MODULE 3 DELIVERY-ONLY PUBLICATION
cloud_module3_validate_mode() {
  case "${1:-}" in
    beginner|intermediate|advanced) return 0 ;;
    *)
      printf 'Invalid Module 3 mode; expected beginner, intermediate or advanced.\n' >&2
      return 2
      ;;
  esac
}

cloud_module3_select_mode() {
  local choice
  if [[ -n "${CLOUD_COMPUTING_SOA_MODE:-}" ]]; then
    cloud_module3_validate_mode "$CLOUD_COMPUTING_SOA_MODE" || return $?
    printf '%s\n' "$CLOUD_COMPUTING_SOA_MODE"
    return 0
  fi
  [[ -t 0 ]] || {
    printf 'Set CLOUD_COMPUTING_SOA_MODE=beginner|intermediate|advanced or use the interactive menu.\n' >&2
    return 2
  }
  printf 'Module 3 teaching track: 1) Beginner  2) Intermediate TODO  3) Advanced\nSelection: ' >&2
  read -r choice || return 2
  case "$choice" in
    1) printf 'beginner\n' ;;
    2) printf 'intermediate\n' ;;
    3) printf 'advanced\n' ;;
    *) printf 'Invalid Module 3 track selection.\n' >&2; return 2 ;;
  esac
}

# Solutions are released for the active intermediate or advanced track; the
# remote check refuses if that track is not the active one.
cloud_module3_select_release_mode() {
  local choice
  if [[ -n "${CLOUD_COMPUTING_SOA_MODE:-}" ]]; then
    case "$CLOUD_COMPUTING_SOA_MODE" in
      intermediate|advanced) printf '%s\n' "$CLOUD_COMPUTING_SOA_MODE"; return 0 ;;
      *)
        printf 'Module 3 solutions are released only for the intermediate or advanced track.\n' >&2
        return 2
        ;;
    esac
  fi
  [[ -t 0 ]] || {
    printf 'Set CLOUD_COMPUTING_SOA_MODE=intermediate|advanced or use the interactive menu.\n' >&2
    return 2
  }
  printf 'Active Module 3 track: 1) Intermediate TODO  2) Advanced\nSelection: ' >&2
  read -r choice || return 2
  case "$choice" in
    1) printf 'intermediate\n' ;;
    2) printf 'advanced\n' ;;
    *) printf 'Invalid Module 3 track selection.\n' >&2; return 2 ;;
  esac
}

cloud_module3_confirm_delivery_only() {
  # Disable automatic approval only within this confirmation call.
  local DIGITAFRICA_ASSUME_YES=false ASSUME_YES=false
  printf '%s\n' \
    'WARNING: Module 3 publication delivers teaching files only.' \
    'Container, Compose and Kubernetes exercises are NOT runtime-validated.' \
    'JupyterHub delivery does not provide Docker access or an exercise runtime.' \
    'Existing participant servers, files and credentials are not modified.' >&2

  # Deliberately do not treat ASSUME_YES as runtime-boundary acknowledgement.
  if ! declare -F confirm >/dev/null; then
    printf 'Explicit organiser confirmation is unavailable; publication blocked.\n' >&2
    return 2
  fi
  confirm 'Publish Module 3 teaching files only, acknowledging runtime validation is pending'
}

cloud_module3_activate_selected_mode() {
  local mode="${1:-}" dependency
  cloud_module3_validate_mode "$mode" || return $?

  # Fail closed while deployment readiness/state helpers are not connected.
  for dependency in \
    cloud_module2_require_complete_participant_cohort \
    ensure_workshop_activation_allowed \
    cloud_module3_check_activation_readiness \
    cloud_module3_set_workshop_state; do
    if ! declare -F "$dependency" >/dev/null; then
      printf 'Module 3 publication blocked: missing helper %s.\n' "$dependency" >&2
      return 2
    fi
  done

  cloud_module2_require_complete_participant_cohort || return $?
  ensure_workshop_activation_allowed cloud-computing-soa || return $?
  cloud_module3_check_activation_readiness "$mode" || return $?
  if ! cloud_module3_confirm_delivery_only; then
    printf 'No Module 3 publication was performed.\n' >&2
    return 1
  fi
  cloud_module3_set_workshop_state "$mode"
}

cloud_module3_activate() {
  local mode
  mode="$(cloud_module3_select_mode)" || return $?
  cloud_module3_activate_selected_mode "$mode"
}
# END MODULE 3 DELIVERY-ONLY PUBLICATION

# Build a remote checker from current repository assets, not stale fixed keys.
cloud_module3_run_deployed() {
  local operation="$1" mode="$2" script
  cloud_module3_validate_mode "$mode" || return $?
  declare -F run_deployment_remote >/dev/null || {
    printf 'Module 3 deployed checks require organiser deployment context.\n' >&2
    return 2
  }
  cloud_module3_check || return $?
  script="$(python3 - "$CLOUD_MODULE3_DIR" "$DIGITAFRICA_NAMESPACE" \
    "$operation" "$mode" <<'BUILD'
import base64
import csv
import hashlib
import json
from pathlib import Path
import shlex
import sys

directory = Path(sys.argv[1])
root = directory.parents[2]
assets = root / "workshop_assets/cloud-computing-soa/module3-containerization-orchestration"
map_text = (assets / "asset-map.tsv").read_bytes().decode("utf-8")
mapped = {track: {} for track in ("beginner", "intermediate", "advanced", "solutions", "tests")}
for track, key, relative in csv.reader(map_text.splitlines(), delimiter="\t"):
    source = assets / ("shared/tests" if track == "tests" else track) / relative
    mapped[track][key] = hashlib.sha256(source.read_bytes()).hexdigest()
payload = {
    "namespace": sys.argv[2], "operation": sys.argv[3], "mode": sys.argv[4],
    "map": map_text, "assets": mapped,
}
encoded = base64.b64encode(json.dumps(payload).encode()).decode()
code = (directory / "module3-deployed.py").read_text()
# helm, unlike k3s kubectl, needs the k3s kubeconfig: the remote shell has none.
print("set -euo pipefail\nexport KUBECONFIG=/etc/rancher/k3s/k3s.yaml")
print("python3 - " + shlex.quote(encoded) + " <<'MODULE3_CHECK'")
print(code)
print("MODULE3_CHECK")
BUILD
)" || return $?
  run_deployment_remote "$script"
}

cloud_module3_check_activation_readiness() {
  cloud_module3_run_deployed check "$1"
}

cloud_module3_set_workshop_state() {
  # Revalidate delivery configuration after organiser confirmation.
  cloud_module3_run_deployed publish "$1"
}

cloud_module3_show_deployment_status() {
  cloud_module3_run_deployed status beginner
}

cloud_module3_release_solutions() {
  local DIGITAFRICA_ASSUME_YES=false ASSUME_YES=false mode
  mode="$(cloud_module3_select_release_mode)" || return $?
  cloud_module2_require_complete_participant_cohort || return $?
  ensure_workshop_activation_allowed cloud-computing-soa || return $?
  cloud_module3_run_deployed check "$mode" || return $?
  printf '%s\n' \
    "Release adds reference solutions only to subsequently spawned $mode servers." \
    'Exercise-runtime readiness remains NOT VALIDATED.' >&2
  declare -F confirm >/dev/null || return 2
  confirm "Explicitly release Cloud SOA Module 3 reference solutions for the $mode track" || {
    printf 'No Module 3 solution release was performed.\n' >&2
    return 1
  }
  # The remote release checks module identity, the active mode and all solutions.
  cloud_module3_run_deployed release "$mode"
}
