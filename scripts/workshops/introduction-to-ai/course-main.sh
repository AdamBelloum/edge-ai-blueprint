#!/usr/bin/env bash
#
# Introduction to AI course-level organiser workflow.
#
# Sourced through controllers/introduction_to_ai.sh by organizer-main.sh.
# This file owns Introduction to AI module routing. Each module script owns
# its own assets, tracks, publication checks, activation, and solution release.

INTRODUCTION_TO_AI_COURSE_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"

INTRODUCTION_TO_AI_MODULE1_HELPER="$INTRODUCTION_TO_AI_COURSE_DIR/module1.sh"
INTRODUCTION_TO_AI_MODULE2_HELPER="$INTRODUCTION_TO_AI_COURSE_DIR/module2.sh"
INTRODUCTION_TO_AI_MODULE3_HELPER="$INTRODUCTION_TO_AI_COURSE_DIR/module3.sh"

check_introduction_to_ai_course_helpers() {
  local helper

  for helper in \
    "$INTRODUCTION_TO_AI_MODULE1_HELPER" \
    "$INTRODUCTION_TO_AI_MODULE2_HELPER" \
    "$INTRODUCTION_TO_AI_MODULE3_HELPER"; do
    [[ -x "$helper" ]] ||
      fail "Missing executable Introduction to AI module helper: $helper"
  done
}

run_introduction_to_ai_module() {
  local helper="$1"
  shift

  check_introduction_to_ai_course_helpers
  "$helper" "$@"
}

run_introduction_to_ai_prepare() {
  run_introduction_to_ai_module     "$INTRODUCTION_TO_AI_MODULE1_HELPER"     publish-and-activate
}

run_introduction_to_ai_module1_check() {
  run_introduction_to_ai_module     "$INTRODUCTION_TO_AI_MODULE1_HELPER"     check
}

run_introduction_to_ai_module2_publish() {
  run_introduction_to_ai_module     "$INTRODUCTION_TO_AI_MODULE2_HELPER"     activate
}

run_introduction_to_ai_module2_check() {
  run_introduction_to_ai_module     "$INTRODUCTION_TO_AI_MODULE2_HELPER"     check
}

run_introduction_to_ai_module2_release_solutions() {
  run_introduction_to_ai_module     "$INTRODUCTION_TO_AI_MODULE2_HELPER"     release-solutions
}

run_introduction_to_ai_module3_publish() {
  run_introduction_to_ai_module     "$INTRODUCTION_TO_AI_MODULE3_HELPER"     activate
}

run_introduction_to_ai_module3_check() {
  run_introduction_to_ai_module     "$INTRODUCTION_TO_AI_MODULE3_HELPER"     check
}

run_introduction_to_ai_module3_release_solutions() {
  run_introduction_to_ai_module     "$INTRODUCTION_TO_AI_MODULE3_HELPER"     release-solutions
}

run_introduction_to_ai_module_menu() {
  local module="$1"
  local choice

  while true; do
    printf '\nIntroduction to AI — Module %s\n\n' "$module"
    printf '  1) Publish and activate for new participant spawns\n'
    printf '  2) Check publication readiness\n'
    if [[ "$module" != "1" ]]; then
      printf '  3) Release reference solutions after the workshop\n'
    fi
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice || return 0

    case "$module:$choice" in
      1:1) run_introduction_to_ai_prepare ;;
      1:2) run_introduction_to_ai_module1_check ;;
      2:1) run_introduction_to_ai_module2_publish ;;
      2:2) run_introduction_to_ai_module2_check ;;
      2:3) run_introduction_to_ai_module2_release_solutions ;;
      3:1) run_introduction_to_ai_module3_publish ;;
      3:2) run_introduction_to_ai_module3_check ;;
      3:3) run_introduction_to_ai_module3_release_solutions ;;
      *:0) return 0 ;;
      *)
        if [[ "$module" == "1" ]]; then
          printf 'Choose a number from 0 to 2.\n' >&2
        else
          printf 'Choose a number from 0 to 3.\n' >&2
        fi
        ;;
    esac
  done
}

run_introduction_to_ai_menu() {
  local choice

  while true; do
    printf '\nIntroduction to AI\n\n'
    printf '  1) Module 1\n'
    printf '  2) Module 2\n'
    printf '  3) Module 3\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice || return 0

    case "$choice" in
      1|2|3) run_introduction_to_ai_module_menu "$choice" ;;
      0) return 0 ;;
      *) printf 'Choose a number from 0 to 3.\n' >&2 ;;
    esac
  done
}
