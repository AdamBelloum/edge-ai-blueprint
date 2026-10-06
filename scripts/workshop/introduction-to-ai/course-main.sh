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

run_introduction_to_ai_menu() {
  local choice

  while true; do
    printf '\nIntroduction to AI\n\n'
    printf '  1) Module 1 — publish and activate for new participant spawns\n'
    printf '  2) Module 1 — check publication readiness\n'
    printf '  3) Module 2 — activate guided beginner and advanced TODO material\n'
    printf '  4) Module 2 — check selected track readiness\n'
    printf '  5) Module 2 — release reference solutions after the workshop\n'
    printf '  6) Module 3 — activate guided beginner and advanced TODO material\n'
    printf '  7) Module 3 — check selected track readiness\n'
    printf '  8) Module 3 — release reference solutions after the workshop\n'
    printf '  0) Back\n\n'
    printf 'Selection: '
    read -r choice

    case "$choice" in
      1) run_introduction_to_ai_prepare ;;
      2) run_introduction_to_ai_module1_check ;;
      3) run_introduction_to_ai_module2_publish ;;
      4) run_introduction_to_ai_module2_check ;;
      5) run_introduction_to_ai_module2_release_solutions ;;
      6) run_introduction_to_ai_module3_publish ;;
      7) run_introduction_to_ai_module3_check ;;
      8) run_introduction_to_ai_module3_release_solutions ;;
      0) return 0 ;;
      *) printf 'Choose a number from 0 to 8.\n' >&2 ;;
    esac
  done
}
