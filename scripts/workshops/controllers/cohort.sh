#!/usr/bin/env bash
#
# cohort.sh
# Sourced by scripts/workshops/organizer-main.sh.
# It expects the organiser's shared configuration and helper functions.

run_initialise_identities() {
  check_participant_accounts

  case "$PARTICIPANT_ACCOUNT_STATUS" in
    absent)
      printf '%s\n' \
        'Provisioning participant identities and matching groups without passwords.' \
        'Participants cannot log in until credentials are issued explicitly.'
      run_account_helper --provision-only
      ;;
    complete)
      printf '%s\n' \
        'Participant identities and groups are already complete.' \
        'No change was made.'
      ;;
    inconsistent)
      fail 'Participant accounts are inconsistent. Repair or reset participant identities before proceeding.'
      ;;
  esac
}

run_issue_credentials() {
  local credentials_output

  check_participant_accounts
  [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
    fail 'Provision complete participant identities and groups before issuing credentials.'


  credentials_output="$(participant_credentials_file)"
  run_account_helper \
    --reset-all-passwords \
    --credentials-output "$credentials_output"

  printf 'Protected participant credentials are available locally (mode 0600): %s\n' \
    "$credentials_output"
}

run_reset() {
  build_account_args
  "$RESET_HELPER" "${ACCOUNT_ARGS[@]}"
}

run_reset_participants() {
  build_account_args
  "$PARTICIPANT_RESET_HELPER" "${ACCOUNT_ARGS[@]}"
}

run_initialisation_menu() {
  local choice

  while true; do
    printf '\nManage participant cohort\n\n'
    printf '  1) Provision participant identities and groups\n'
    printf '  2) Issue and export participant credentials\n'
    printf '  3) Show participant-account status\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) run_initialise_identities ;;
      2) run_issue_credentials ;;
      3) check_participant_accounts ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, or 3.\n' >&2 ;;
    esac
  done
}

run_reset_menu() {
  local choice

  while true; do
    printf '\nReset active workshop cycle\n\n'
    printf '  1) Reset active workshop and participant cohort\n'
    printf '  2) Remove participant identities and credential exports only\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) run_reset ;;
      2) run_reset_participants ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, or 2.\n' >&2 ;;
    esac
  done
}

# Informational only: does not inspect state or change the deployment.
show_new_workshop_workflow() {
  cat <<'WORKFLOW'

Expected workflow for a new workshop
  1. Verify platform readiness and previous-cycle cleanup using status/readiness checks.
     If cleanup is incomplete or activation is blocked, stop and contact the
     administrator/maintainer. Do not manually bypass the cleanup marker.
  2. Manage participant cohort: provision participant identities and groups.
  3. After adding or updating a workshop/module, reconcile workshop applications.
  4. Open Workshops: select the workshop/module and prepare/publish its supported mode.
  5. Run the workshop-specific readiness checks before inviting participants.
     Publication alone does not prove runtime or participant execution readiness.
  6. Manage participant cohort: issue/export credentials when ready to distribute.
     Issuing credentials resets participant passwords; do not repeat unnecessarily.
  7. Distribute credentials securely. Do not commit credential exports to Git.

Infrastructure deployment is a separate administrator task.
Participant-only reset does not clean workspaces or stop existing runtimes.
WORKFLOW
}
