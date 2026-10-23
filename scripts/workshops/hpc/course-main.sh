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
    workshop_ui_heading "HPC / OpenMP Beginner"
    workshop_ui_section "PREPARATION"
    workshop_ui_option 1 "Prepare teaching assets: no activation or runtime installation"
    workshop_ui_section "CHECKS"
    workshop_ui_option 2 "Show workshop selection status: not OpenMP execution readiness"
    workshop_ui_section "PUBLICATION"
    workshop_ui_option 3 "Publish Beginner workshop: reconciles JupyterHub; runtime setup at pod startup"
    workshop_ui_option 4 "Publish Advanced workshop: TODO - not implemented"
    workshop_ui_section "AFTER THE WORKSHOP"
    workshop_ui_option 5 "Release advanced reference solutions - TODO: not implemented"
    printf '\n'
    workshop_ui_option 0 "Back to HPC"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) hpc_openmp_prepare_workspace ||
           printf 'HPC asset staging did not complete.\n' >&2 ;;
      3) hpc_openmp_publish ||
           printf 'HPC publication did not complete.\n' >&2 ;;
      2) hpc_openmp_show_status ||
           printf 'Workshop selection status could not be retrieved.\n' >&2 ;;
      4)
        printf '%s\n' 'TODO: OpenMP advanced publication is not implemented. No changes made.'
        ;;
      5)
        printf '%s\n' 'TODO: OpenMP advanced solution release is not implemented. No changes made.'
        ;;
      0) return 0 ;;
      *) printf 'Choose a value from 0 through 5.\n' >&2 ;;
    esac
  done
}

run_hpc_menu() {
  local choice
  while true; do
    workshop_ui_heading "Workshops / HPC"
    workshop_ui_section "SELECT A WORKSHOP LEVEL"
    workshop_ui_option 1 "OpenMP Beginner: runtime setup at participant pod startup"
    workshop_ui_option 2 "OpenMP Advanced: TODO - not implemented"
    workshop_ui_option 3 "MPI Beginner: TODO - not implemented"
    workshop_ui_option 4 "MPI Advanced: TODO - not implemented"
    printf '\n'
    workshop_ui_option 0 "Back to workshops"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) run_hpc_openmp_menu ;;
      2)
        printf '%s\n' 'TODO: OpenMP advanced workshop is not implemented. No changes made.'
        ;;
      3)
        printf '%s\n' 'TODO: MPI beginner workshop is not implemented. No changes made.'
        ;;
      4)
        printf '%s\n' 'TODO: MPI advanced workshop is not implemented. No changes made.'
        ;;
      0) return 0 ;;
      *) printf 'Choose a value from 0 through 4.\n' >&2 ;;
    esac
  done
}
