#!/usr/bin/env bash
#
# introduction_to_ai.sh
# Sourced by scripts/workshop/organizer-main.sh.
# It expects the organiser's shared configuration and helper functions.

set_introduction_to_ai_workshop_state() {
  local module="$1"
  local mode="$2"
  local solutions_released=false

  case "${module}:${mode}" in
    module1:beginner|module2:beginner|module2:advanced)
      ;;
    module1:*)
      fail 'Introduction to AI Module 1 supports only mode=beginner.'
      ;;
    module2:*)
      fail 'Introduction to AI Module 2 requires mode=beginner or mode=advanced.'
      ;;
    *)
      fail "Unsupported Introduction to AI module: $module"
      ;;
  esac

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"introduction-to-ai","introduction_to_ai_module":"${module}","mode":"${mode}","solutions_released":"${solutions_released}"}}'
REMOTE
)"
  printf '%s\n' \
    "Introduction to AI ${module} (${mode}) is now active for subsequently spawned participant servers."
}

select_introduction_to_ai_module2_mode() {
  local choice

  if [[ -n "${INTRODUCTION_TO_AI_MODE:-}" ]]; then
    case "$INTRODUCTION_TO_AI_MODE" in
      beginner|advanced)
        printf '%s\n' "$INTRODUCTION_TO_AI_MODE"
        return 0
        ;;
      *)
        fail 'INTRODUCTION_TO_AI_MODE must be either beginner or advanced.'
        ;;
    esac
  fi

  [[ -t 0 ]] || fail \
    'Module 2 publication requires an interactive terminal or INTRODUCTION_TO_AI_MODE=beginner|advanced.'

  while true; do
    printf '\nIntroduction to AI — Module 2 track\n\n' >&2
    printf '  1) Beginner — guided hands-on notebook\n' >&2
    printf '  2) Advanced — TODO-based notebook\n' >&2
    printf 'Selection: ' >&2
    read -r choice

    case "$choice" in
      1) printf '%s\n' beginner; return 0 ;;
      2) printf '%s\n' advanced; return 0 ;;
      *) printf 'Choose 1 or 2.\n' >&2 ;;
    esac
  done
}

run_introduction_to_ai_prepare() {
  check_participant_accounts
  [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
    fail 'Provision complete participant identities and groups before starting Introduction to AI.'

  ensure_workshop_activation_allowed introduction-to-ai
  "$MODULE1_HELPER" publish
  set_introduction_to_ai_workshop_state module1 beginner
}

run_introduction_to_ai_module2_publish() {
  local mode

  mode="$(select_introduction_to_ai_module2_mode)"

  check_participant_accounts
  [[ "$PARTICIPANT_ACCOUNT_STATUS" == complete ]] ||
    fail 'Provision complete participant identities and groups before starting Introduction to AI Module 2.'

  ensure_workshop_activation_allowed introduction-to-ai
  "$MODULE2_HELPER" check --mode "$mode"
  set_introduction_to_ai_workshop_state module2 "$mode"
}

run_introduction_to_ai_module2_check() {
  local mode

  mode="$(select_introduction_to_ai_module2_mode)"
  "$MODULE2_HELPER" check --mode "$mode"
}

run_introduction_to_ai_module2_release_solutions() {
  print_heading "Release Introduction to AI — Module 2 solutions"
  printf '%s\n' \
    'This is a one-way organiser action for subsequently spawned participant servers.' \
    'Existing participant servers and notebooks are not modified.' \
    'It is available only while Introduction to AI Module 2 is active.'

  if ! confirm "Release Module 2 reference solutions after the workshop"; then
    log 'No Module 2 solution release was performed.'
    return 0
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail

workshop_type="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}')"
module="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.introduction_to_ai_module}')"
mode="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

if [ "\$workshop_type" != "introduction-to-ai" ] || \
   [ "\$module" != "module2" ] || \
   [ "\$mode" != "advanced" ]; then
  printf '%s\n' \
    'Module 2 solutions can be released only while Introduction to AI Module 2 is active.' \
    "Current state: workshop_type=\${workshop_type:-unset}, module=\${module:-unset}, mode=\${mode:-unset}" >&2
  exit 1
fi

solution_notebook="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-notebooks-introduction-to-ai-module2-solutions \
  -o jsonpath='{.data.02_foundations_of_ml_solutions\.ipynb}')"
if [ -z "\$solution_notebook" ]; then
  printf '%s\n' \
    'Module 2 solutions ConfigMap does not contain the expected notebook.' \
    'Run reconcile-applications before releasing solutions.' >&2
  exit 1
fi

k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"solutions_released":"true"}}'

printf '%s\n' 'Module 2 solutions released for subsequently spawned participant servers.'
REMOTE
)"

  "$MODULE2_HELPER" status
}

run_introduction_to_ai_menu() {
  local choice

  while true; do
    printf '\nIntroduction to AI\n\n'
    printf '  1) Module 1 — publish and activate for new participant spawns\n'
    printf '  2) Module 1 — check publication readiness\n'
    printf '  3) Module 2 — activate guided beginner and advanced TODO material\n'
    printf '  4) Module 2 — check selected track readiness\n'
    printf '  5) Module 2 — release reference solutions after the workshop\n'
    printf '  6) Module 3 — not configured yet\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) run_introduction_to_ai_prepare ;;
      2) "$MODULE1_HELPER" check ;;
      3) run_introduction_to_ai_module2_publish ;;
      4) run_introduction_to_ai_module2_check ;;
      5) run_introduction_to_ai_module2_release_solutions ;;
      6) printf 'This module has not been configured yet.\n' ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, 4, 5, or 6.\n' >&2 ;;
    esac
  done
}
