#!/usr/bin/env bash
# Compatibility façade sourced by organizer-main.sh.
# HPC implementation remains under scripts/workshops/hpc/.

HPC_CONTROLLER_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
HPC_COURSE_MAIN="$HPC_CONTROLLER_DIR/../hpc/course-main.sh"

[[ -r "$HPC_COURSE_MAIN" ]] || {
  printf 'ERROR: Missing HPC course workflow: %s\n' \
    "$HPC_COURSE_MAIN" >&2
  return 1
}
# shellcheck source=../hpc/course-main.sh
source "$HPC_COURSE_MAIN"
