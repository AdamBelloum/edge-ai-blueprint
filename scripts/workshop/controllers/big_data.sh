#!/usr/bin/env bash
#
# Compatibility façade for the Big Data organiser workflow.
#
# Sourced by scripts/workshop/organizer-main.sh. Course implementation
# remains under big-data/, following the existing workshop architecture.

BIG_DATA_CONTROLLER_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
BIG_DATA_COURSE_MAIN="$BIG_DATA_CONTROLLER_DIR/../big-data/course-main.sh"

if [[ ! -r "$BIG_DATA_COURSE_MAIN" ]]; then
  printf 'Missing Big Data course workflow: %s\n' \
    "$BIG_DATA_COURSE_MAIN" >&2
  return 1
fi

# shellcheck source=../big-data/course-main.sh
source "$BIG_DATA_COURSE_MAIN"
