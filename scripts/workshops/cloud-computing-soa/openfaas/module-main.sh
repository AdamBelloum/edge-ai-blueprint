#!/usr/bin/env bash
# Sourced OpenFaaS controller. Pre-live actions have no deployment side effects.

CLOUD_MODULE5_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_MODULE5_ROOT="$(cd -- "$CLOUD_MODULE5_DIR/../../../.." && pwd)"
CLOUD_MODULE5_ASSETS="$CLOUD_MODULE5_ROOT/workshop_assets/cloud_computing_soa/module5_openfaas"

cloud_module5_status() {
  printf '%s\n' \
    'Cloud Computing SOA — Module 5: OpenFaaS' \
    'State: pre-live authoring; not ready for participant delivery.' \
    'Live build, push, deploy, monitoring and isolation remain unvalidated.' \
    'No infrastructure or active workshop state was inspected or modified.'
}

cloud_module5_check() {
  local checker="$CLOUD_MODULE5_ASSETS/tests/check-prelive.py"
  if [[ ! -r "$checker" ]]; then
    printf 'ERROR: Pre-live checker is not yet staged: %s\n' "$checker" >&2
    return 1
  fi
  command -v python3 >/dev/null 2>&1 || {
    printf 'ERROR: python3 is required for local checks.\n' >&2
    return 2
  }
  python3 "$checker"
}

cloud_module5_publish() {
  printf '%s\n' \
    'BLOCKED: OpenFaaS publication is unavailable before live validation.' \
    'Resolve edition approval, builder/registry access and reference-lab gates first.' \
    'No workshop selection, reconciliation or deployment was performed.' >&2
  return 2
}

run_cloud_module5_menu() {
  local choice
  while true; do
    printf '\nOpenFaaS — pre-live preparation\n\n'
    printf '%s\n' \
      '  1) Check local pre-live assets' \
      '  2) Show authoring status' \
      '  0) Back to modules'
    printf '\nSelection: '
    read -r choice || return 0
    case "$choice" in
      1) cloud_module5_check || printf 'Pre-live checks did not pass.\n' >&2 ;;
      2) cloud_module5_status ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, or 2.\n' >&2 ;;
    esac
  done
}
