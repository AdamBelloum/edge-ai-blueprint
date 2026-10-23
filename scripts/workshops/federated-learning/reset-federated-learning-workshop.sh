#!/usr/bin/env bash
# Workshop-owned FL reset entry point.
# Currently delegates runtime stopping only; data cleanup remains pending.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: reset-workshop.sh --runtime-only

Stop and verify the installed Flower server using the existing manager.
Preserves service definitions, application assets and dependencies.

This stage does not clean generated partitions or results, delete participant
workspaces/accounts, restore neutral JupyterHub, or verify full workshop reset.
USAGE
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi

if [[ $# -ne 1 || "$1" != --runtime-only ]]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
manager="$SCRIPT_DIR/manage-flower-server.sh"

[[ -x "$manager" ]] || {
  printf 'ERROR: Missing executable Flower manager: %s\n' "$manager" >&2
  exit 2
}

printf '%s\n' 'FL reset: stopping and verifying the installed Flower runtime.'
if "$manager" stop; then
  printf '%s\n' \
    'FL runtime stop verified; installed assets preserved.' \
    'FL data cleanup and full workshop reset are NOT verified.'
else
  status=$?
  printf '%s\n' 'ERROR: FL runtime stop failed; cleanup remains unverified.' >&2
  exit "$status"
fi
