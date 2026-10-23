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
    workshop_ui_heading "Introduction to AI / Module $module"
    workshop_ui_section "CHECKS"
    workshop_ui_option 1 "Check publication readiness"
    workshop_ui_section "PUBLICATION"
    workshop_ui_option 2 "Publish Beginner workshop: selects Beginner for new participant spawns"
    if [[ "$module" == "1" ]]; then
      workshop_ui_option 3 "Publish Advanced workshop - TODO: not implemented"
    else
      workshop_ui_option 3 "Publish Advanced workshop: selects Advanced for new participant spawns"
    fi
    workshop_ui_section "AFTER THE WORKSHOP"
    if [[ "$module" == "1" ]]; then
      workshop_ui_option 4 "Release advanced reference solutions - TODO: not implemented"
    else
      workshop_ui_option 4 "Release advanced reference solutions"
    fi
    printf '\n'
    workshop_ui_option 0 "Back to Introduction to AI"
    workshop_ui_prompt
    read -r choice || return 0

    case "$module:$choice" in
      1:1) run_introduction_to_ai_module1_check ;;
      1:2) run_introduction_to_ai_prepare ;;
      1:3|1:4)
        printf '%s\n' 'TODO: this Module 1 feature is not implemented. No changes made.'
        ;;
      2:1) run_introduction_to_ai_module2_check ;;
      2:2) run_introduction_to_ai_module "$INTRODUCTION_TO_AI_MODULE2_HELPER" activate --mode beginner ;;
      2:3) run_introduction_to_ai_module "$INTRODUCTION_TO_AI_MODULE2_HELPER" activate --mode advanced ;;
      2:4) run_introduction_to_ai_module2_release_solutions ;;
      3:1) run_introduction_to_ai_module3_check ;;
      3:2) run_introduction_to_ai_module "$INTRODUCTION_TO_AI_MODULE3_HELPER" activate --mode beginner ;;
      3:3) run_introduction_to_ai_module "$INTRODUCTION_TO_AI_MODULE3_HELPER" activate --mode advanced ;;
      3:4) run_introduction_to_ai_module3_release_solutions ;;
      *:0) return 0 ;;
      *) printf 'Choose a value from 0 through 4.\n' >&2 ;;
    esac
  done
}

run_introduction_to_ai_menu() {
  local choice

  while true; do
    workshop_ui_heading "Workshops / Introduction to AI"
    workshop_ui_section "SELECT A MODULE"
    workshop_ui_option 1 "Module 1"
    workshop_ui_option 2 "Module 2"
    workshop_ui_option 3 "Module 3"
    printf '\n'
    workshop_ui_option 0 "Back to workshops"
    workshop_ui_prompt
    read -r choice || return 0

    case "$choice" in
      1|2|3) run_introduction_to_ai_module_menu "$choice" ;;
      0) return 0 ;;
      *) printf 'Choose a number from 0 to 3.\n' >&2 ;;
    esac
  done
}
