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
  local -a pre_reconciliation_readiness_args=(--non-interactive --skip-participant-mapping)
  local -a post_reconciliation_readiness_args=(--non-interactive)
  local -a cohort_args=(new-cohort)

  select_fl_mode
  check_participant_accounts
  [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
    fail 'Provision the participant cohort before initialising a Federated Learning workshop.'

  ensure_workshop_activation_allowed federated-learning

  printf '%s\n' 'Stopping any prior organiser-controlled Flower server...'
  "$FLOWER_MANAGER" stop

  "$PREPARE_HELPER" "${pre_reconciliation_readiness_args[@]}"

  cohort_args+=("$MODE")
  "$NON_INTERACTIVE" && cohort_args+=(--yes)
  "$COHORT_HELPER" "${cohort_args[@]}"

  "$PREPARE_HELPER" "${post_reconciliation_readiness_args[@]}"

  printf '%s\n' 'Starting a fresh Flower server for the initialised cohort...'
  "$FLOWER_MANAGER" restart --defaults
  printf '%s\n' 'Federated Learning preparation completed.'
}

run_flower_manager_menu() {
  local choice rounds min_clients

  while true; do
    printf '\nFlower server lifecycle\n\n'
    printf '  1) Show status and effective parameters\n'
    printf '  2) Start the server\n'
    printf '  3) Stop the server\n'
    printf '  4) Restart the server\n'
    printf '  5) Update rounds and required-client parameters\n'
    printf '  6) Show recent server logs\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) "$FLOWER_MANAGER" status ;;
      2) "$FLOWER_MANAGER" start ;;
      3) "$FLOWER_MANAGER" stop ;;
      4) "$FLOWER_MANAGER" restart ;;
      5)
        printf 'Number of federated-training rounds: '
        read -r rounds
        printf 'Required participating clients in every round: '
        read -r min_clients
        "$FLOWER_MANAGER" configure --rounds "$rounds" --min-clients "$min_clients"
        ;;
      6) "$FLOWER_MANAGER" logs ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, 4, 5, or 6.\n' >&2 ;;
    esac
  done
}

run_federated_learning_menu() {
  local choice

  while true; do
    printf '\nFederated Learning\n\n'
    printf '  1) Initialise beginner workshop\n'
    printf '  2) Initialise advanced workshop\n'
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
