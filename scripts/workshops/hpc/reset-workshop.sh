#!/usr/bin/env bash
# Workshop-owned HPC staging reset entry point.
# Participant workspaces, account options and neutral reconciliation remain global.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: reset-workshop.sh --runtime-only --module openmp-01-basics|mpi-01-basics
                         [--source-revision FULL_COMMIT_SHA]

Delegate cleanup of verified installation-created HPC staging assets.
Both modules share the same staged OpenMP/MPI assets and runtime definitions.
Requires stopped participant servers and an administrator-approved maintenance window.
No concurrent preparation, publication, reconciliation or participant spawning.

This helper does not stop servers, delete participant homes/PVCs, manage accounts,
remove credentials, alter shared infrastructure or perform neutral reconciliation.
The global reset remains responsible for its workspace/account options and
neutral reconciliation, including removal of the HPC runtime ConfigMap.

Full workshop reset is NOT verified by this local helper.
USAGE
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi

if [[ $# -ne 3 && $# -ne 5 ]]; then
  usage >&2
  exit 2
fi
if [[ "$1" != --runtime-only || "$2" != --module ]]; then
  usage >&2
  exit 2
fi
case "$3" in
  openmp-01-basics|mpi-01-basics) module="$3" ;;
  *)
    printf 'ERROR: Unsupported HPC module: %s\n' "$3" >&2
    usage >&2
    exit 2
    ;;
esac

source_args=()
if [[ $# -eq 5 ]]; then
  [[ "$4" == --source-revision && "$5" =~ ^[0-9a-f]{40}$ ]] || {
    usage >&2; exit 2;
  }
  source_args=(--source-revision "$5")
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cleanup="$SCRIPT_DIR/cleanup-staging.sh"
[[ -x "$cleanup" ]] || {
  printf 'ERROR: Missing executable HPC staging cleanup helper: %s\n' "$cleanup" >&2
  exit 2
}

printf 'HPC staging reset: module=%s; shared OpenMP/MPI staging.\n' "$module"
printf '%s\n' 'Checking HPC staging cleanup targets without deletion...'
if "$cleanup" --check "${source_args[@]}"; then
  printf '%s\n' 'HPC staging preflight passed; no staging files deleted.'
else
  status=$?
  printf '%s\n' \
    'ERROR: HPC staging preflight failed; cleanup execution was not started.' >&2
  exit "$status"
fi

printf '%s\n' 'Executing the reviewed HPC staging cleanup...'
if "$cleanup" --execute "${source_args[@]}"; then
  printf '%s\n' \
    'HPC staging cleanup helper returned successfully.' \
    'Participant homes, identities, exports and shared infrastructure were not targeted by this helper.' \
    'Full workshop reset is NOT verified; global workspace/account handling and neutral reconciliation remain separate.'
else
  status=$?
  printf '%s\n' 'ERROR: HPC staging cleanup failed; cleanup remains unverified.' >&2
  exit "$status"
fi
