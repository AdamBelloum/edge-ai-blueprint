#!/usr/bin/env bash
#
# Compatibility façade for the Introduction to AI organiser workflow.
#
# Sourced by scripts/workshop/organizer-main.sh. The course implementation is
# intentionally kept under introduction-to-ai/, while this stable controller
# path preserves the existing organiser workflow and CLI dispatch contract.

INTRODUCTION_TO_AI_CONTROLLER_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
INTRODUCTION_TO_AI_COURSE_MAIN="$INTRODUCTION_TO_AI_CONTROLLER_DIR/../introduction-to-ai/course-main.sh"

if [[ ! -r "$INTRODUCTION_TO_AI_COURSE_MAIN" ]]; then
  printf 'Missing Introduction to AI course workflow: %s\n' \
    "$INTRODUCTION_TO_AI_COURSE_MAIN" >&2
  return 1
fi

# shellcheck source=../introduction-to-ai/course-main.sh
source "$INTRODUCTION_TO_AI_COURSE_MAIN"
