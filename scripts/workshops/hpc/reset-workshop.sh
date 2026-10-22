#!/usr/bin/env bash
# Workshop-owned HPC runtime reset boundary. MPI integration is deferred.
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: reset-workshop.sh --runtime-only --module openmp-01-basics' \
    'MPI module support is deferred until its controller is available.' \
    'Participant server/home cleanup and neutral reconciliation remain global.' \
    'Full workshop reset is not verified by this script.'
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi

if [[ $# -ne 3 ]]; then
  usage >&2
  exit 2
fi
if [[ "$1" != --runtime-only || "$2" != --module ||
      "$3" != openmp-01-basics ]]; then
  usage >&2
  exit 2
fi

printf '%s\n' \
  'HPC runtime reset boundary: module=openmp-01-basics.' \
  'The participant toolchain is installed inside participant homes.' \
  'Global reset must stop participant servers and delete participant homes.' \
  'Staged source files and toolchain specifications are preserved.' \
  'Full workshop cleanup is NOT verified.'
