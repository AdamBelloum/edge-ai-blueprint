#!/usr/bin/env bash
#
# federated_learning.sh
# Sourced by scripts/workshops/organizer-main.sh.
# It expects the organiser's shared configuration and helper functions.

select_fl_mode() {
  local choice

  if [[ -n "$MODE" ]]; then
    [[ "$MODE" == beginner || "$MODE" == advanced ]] ||
      fail 'Choose beginner or advanced.'
    return 0
  fi

  while true; do
    workshop_ui_heading "Federated Learning / Teaching mode"
    workshop_ui_option 1 "Beginner"
    workshop_ui_option 2 "Advanced"
    workshop_ui_prompt
    read -r choice

    case "$choice" in
      1) MODE=beginner; return 0 ;;
      2) MODE=advanced; return 0 ;;
      *) printf 'Choose 1 for Beginner or 2 for Advanced.\n' >&2 ;;
    esac
  done
}

run_fl_prepare() {
  local -a preparation_args=(prepare)

  select_fl_mode
  check_participant_accounts
  [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
    fail 'Provision the participant cohort before preparing a Federated Learning workshop.'

  preparation_args+=("$MODE")
  "$NON_INTERACTIVE" && preparation_args+=(--yes)

  "$COHORT_HELPER" "${preparation_args[@]}"
}

run_flower_manager_menu() {
  "$COHORT_HELPER" flower
}

run_federated_learning_menu() {
  local choice

  while true; do
    workshop_ui_heading "Workshops / Federated Learning"
    workshop_ui_section "PREPARE AND START"
    workshop_ui_option 1 "Beginner workshop"
    workshop_ui_option 2 "Advanced workshop"
    workshop_ui_note "Both preparation actions start Flower."
    workshop_ui_section "AFTER THE WORKSHOP"
    workshop_ui_option 3 "Release advanced reference solutions"
    workshop_ui_section "RUNTIME"
    workshop_ui_option 4 "Manage Flower server"
    printf '\n'
    workshop_ui_option 0 "Back to workshops"
    workshop_ui_prompt
    read -r choice

    case "$choice" in
      1) MODE=beginner; run_fl_prepare ;;
      2) MODE=advanced; run_fl_prepare ;;
      3) "$COHORT_HELPER" release-solutions ;;
      4) run_flower_manager_menu ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, or 4.\n' >&2 ;;
    esac
  done
}
