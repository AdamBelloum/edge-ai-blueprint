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
  local account_choice deletion_confirmation status

  printf '\nReset workshop: participant accounts\n'
  printf '  1) Keep accounts, groups, passwords and credential exports (default)\n'
  printf '  2) Delete participant accounts, matching groups and credential exports\n'
  printf '  0) Cancel reset\n'
  printf 'Selection [1]: '
  if ! IFS= read -r account_choice; then
    printf 'Reset cancelled; no cleanup performed.\n'
    return 0
  fi

  case "$account_choice" in
    ""|1)
      "$RESET_HELPER" --accounts keep
      ;;
    2)
      printf 'Account deletion is permanent. Workshop cleanup is confirmed separately.\n'
      printf 'Delete participant accounts and matching credential exports? [y/N]: '
      if ! IFS= read -r deletion_confirmation; then
        printf 'Reset cancelled; no cleanup performed.\n'
        return 0
      fi
      case "$deletion_confirmation" in
        y|Y|yes|YES) ;;
        *)
          printf 'Reset cancelled; no cleanup performed.\n'
          return 0
          ;;
      esac

      build_account_args
      printf 'Checking Keycloak access before workshop cleanup...\n'
      if run_account_helper --status; then
        "$RESET_HELPER" --accounts delete "${ACCOUNT_ARGS[@]}"
      else
        status=$?
        printf 'Keycloak preflight failed; workshop cleanup was not started.\n' >&2
        return "$status"
      fi
      ;;
    0)
      printf 'Reset cancelled; no cleanup performed.\n'
      return 0
      ;;
    *)
      printf 'Invalid selection; no cleanup performed. Choose 0, 1 or 2.\n' >&2
      return 2
      ;;
  esac
}

run_reset_participants() {
  build_account_args
  "$PARTICIPANT_RESET_HELPER" "${ACCOUNT_ARGS[@]}"
}

run_initialisation_menu() {
  local choice

  while true; do
    workshop_ui_heading "Organiser / Participant cohort"
    workshop_ui_section "SETUP"
    workshop_ui_option 1 "Provision identities and groups: creates cohort without login passwords"
    workshop_ui_section "ACCESS"
    workshop_ui_option 2 "Issue and export credentials: resets passwords; distribute export securely"
    workshop_ui_section "CHECK"
    workshop_ui_option 3 "Show participant-account status"
    printf '\n'
    workshop_ui_option 0 "Back to main menu"
    workshop_ui_prompt
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
    workshop_ui_heading "Organiser / Reset workshop cycle"
    workshop_ui_warning "Destructive actions. Review the scope before confirming."
    workshop_ui_section "WORKSHOP CYCLE"
    workshop_ui_option 1 "Reset active workshop (choose whether to keep accounts): activation blocked until cleanup verified"
    workshop_ui_section "IDENTITIES ONLY"
    workshop_ui_option 2 "Remove identities and credential exports: preserves workspaces, servers, runtimes and selection"
    printf '\n'
    workshop_ui_option 0 "Back to main menu"
    workshop_ui_prompt
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
  workshop_ui_heading "Workshops / Preparation guide"
  workshop_ui_section "1. CHECK"
  workshop_ui_note "Verify platform readiness and previous-cycle cleanup."
  workshop_ui_note "Cleanup incomplete? Stop; contact the administrator."
  workshop_ui_note "Never bypass cleanup markers or activation safeguards."
  workshop_ui_section "2. PREPARE"
  workshop_ui_note "Main > 1: Provision identities/groups; Main > 2: Reconcile apps."
  workshop_ui_note "Choose a course below; prepare/publish a supported mode."
  workshop_ui_section "3. VERIFY AND SHARE"
  workshop_ui_note "Check workshop readiness; publication is not execution readiness."
  workshop_ui_note "Main > 1: Issue credentials when ready; reissuing resets passwords."
  workshop_ui_note "Share credentials securely; never commit them."
  printf '\n'
  workshop_ui_note "Deployment: administrator task. Participant-only reset preserves workspaces/runtimes."
}
