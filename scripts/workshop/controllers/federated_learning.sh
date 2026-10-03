#!/usr/bin/env bash
#
# federated_learning.sh
# Sourced by scripts/workshop/organizer-main.sh.
# It expects the organiser's shared configuration and helper functions.

select_fl_mode() {
  local choice

  if [[ -n "$MODE" ]]; then
    [[ "$MODE" == beginner || "$MODE" == advanced ]] ||
      fail 'Choose beginner or advanced.'
    return 0
  fi

  while true; do
    printf '%s\n' \
      'Federated Learning mode:' \
      '  1) Beginner' \
      '  2) Advanced'
    printf 'Selection: '
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
    printf '\nFederated Learning\n\n'
    printf '  1) Prepare beginner workshop and start Flower\n'
    printf '  2) Prepare advanced workshop and start Flower\n'
    printf '  3) Release advanced reference solutions\n'
    printf '  4) Manage Flower server\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
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
