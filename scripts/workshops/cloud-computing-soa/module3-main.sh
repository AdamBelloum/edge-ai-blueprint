#!/usr/bin/env bash
# Sourced Module 3 controller: local validation and informational status only.

CLOUD_MODULE3_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_MODULE3_LOCAL_HELPER="$CLOUD_MODULE3_DIR/module3-local.sh"

cloud_module3_status() {
  printf '%s\n' \
    'Cloud Computing SOA — Module 3: Containerization and Orchestration' \
    'Available organiser actions: local structural/syntax checks and this status.' \
    'Participant delivery and activation are not connected.' \
    'Docker/Compose and Kubernetes functional rehearsal is deferred to the next sprint.' \
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

  for track in beginner advanced solutions; do
    printf '\n=== Module 3 local check: %s ===\n' "$track"
    bash "$CLOUD_MODULE3_LOCAL_HELPER" check "$track" || return $?
  done

  printf '\n%s\n' \
    'Local checks passed for all tracks; service and deployment readiness remain unverified.'
}

run_cloud_module3_menu() {
  local choice

  while true; do
    printf '\nModule 3 — Containerization and Orchestration (local preparation only)\n\n'
    printf '%s\n' \
      '  1) Check local assets — all tracks' \
      '  2) Show integration and validation status' \
      '  0) Back to modules'
    printf '\nSelection: '
    read -r choice || return 0

    case "$choice" in
      1)
        cloud_module3_check ||
          printf 'Module 3 local checks did not pass.\n' >&2
        ;;
      2) cloud_module3_status ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, or 2.\n' >&2 ;;
    esac
  done
}
