#!/usr/bin/env bash
#
# Compatibility façade for the Cloud Computing SOA organiser workflow.
#
# Sourced by scripts/workshop/organizer-main.sh. The course implementation is
# intentionally kept under cloud-computing-soa/, while this stable controller
# path preserves a modular organiser architecture.

CLOUD_COMPUTING_SOA_CONTROLLER_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
CLOUD_COMPUTING_SOA_COURSE_MAIN="$CLOUD_COMPUTING_SOA_CONTROLLER_DIR/../cloud-computing-soa/course-main.sh"

if [[ ! -r "$CLOUD_COMPUTING_SOA_COURSE_MAIN" ]]; then
  printf 'Missing Cloud Computing SOA course workflow: %s\n' \
    "$CLOUD_COMPUTING_SOA_COURSE_MAIN" >&2
  return 1
fi

# shellcheck source=../cloud-computing-soa/course-main.sh
source "$CLOUD_COMPUTING_SOA_COURSE_MAIN"
