#!/usr/bin/env bash
# HPC organiser course workflow, sourced through controllers/hpc.sh.

HPC_COURSE_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
HPC_OPENMP_MODULE_MAIN="$HPC_COURSE_DIR/openmp-01-basics/module-main.sh"

[[ -r "$HPC_OPENMP_MODULE_MAIN" ]] || {
  printf 'ERROR: Missing OpenMP module workflow: %s\n' \
    "$HPC_OPENMP_MODULE_MAIN" >&2
  return 1
}
# shellcheck source=openmp-01-basics/module-main.sh
source "$HPC_OPENMP_MODULE_MAIN"

run_hpc_openmp_menu() {
  local choice
  while true; do
    workshop_ui_heading "HPC / OpenMP basics"
    workshop_ui_section "PREPARE"
    workshop_ui_option 1 "Stage teaching assets"
    workshop_ui_note "Assets only; no activation or runtime installation."
    workshop_ui_option 2 "Publish beginner workspace"
    workshop_ui_note "Reconciles JupyterHub; runtime setup occurs at pod startup."
    workshop_ui_section "INSPECT"
    workshop_ui_option 3 "Show workshop selection"
    workshop_ui_note "Selection status is not OpenMP execution readiness."
    printf '\n'
    workshop_ui_option 0 "Back to HPC"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) hpc_openmp_prepare_workspace ||
           printf 'HPC asset staging did not complete.\n' >&2 ;;
      2) hpc_openmp_publish ||
           printf 'HPC publication did not complete.\n' >&2 ;;
      3) hpc_openmp_show_status ||
           printf 'Workshop selection status could not be retrieved.\n' >&2 ;;
      0) return 0 ;;
      *) printf 'Choose a value from 0 through 3.\n' >&2 ;;
    esac
  done
}

run_hpc_menu() {
  local choice
  while true; do
    workshop_ui_heading "Workshops / HPC"
    workshop_ui_section "SELECT A MODULE"
    workshop_ui_option 1 "OpenMP basics"
    workshop_ui_note "Beginner mode."
    printf '\n'
    workshop_ui_option 0 "Back to workshops"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) run_hpc_openmp_menu ;;
      0) return 0 ;;
      *) printf 'Choose 0 or 1.\n' >&2 ;;
    esac
  done
}
