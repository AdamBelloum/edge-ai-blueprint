#!/usr/bin/env bash
# Workshop-owned Big Data reset entry point.
# Currently delegates verified Spark/Livy runtime teardown only.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: reset-workshop.sh --runtime-only --module spark

Remove ownership-verified Spark/Livy containers and the private network through
the existing teardown helper. Requires administrative control of Docker.

Preserves images, source datasets, staged runtime assets and participant
workspaces/accounts. This stage does not verify full workshop reset.
USAGE
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi

if [[ $# -ne 3 ]]; then
  usage >&2
  exit 2
fi

if [[ "$1" != --runtime-only || "$2" != --module || "$3" != spark ]]; then
  printf '%s\n' 'ERROR: Only explicit Spark runtime cleanup is supported.' >&2
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
teardown="$SCRIPT_DIR/spark/teardown-runtime.sh"

[[ -x "$teardown" ]] || {
  printf 'ERROR: Missing executable Spark teardown helper: %s\n' "$teardown" >&2
  exit 2
}

printf '%s\n' 'Big Data reset: tearing down the verified Spark/Livy runtime.'
if "$teardown" --execute; then
  printf '%s\n' \
    'Spark/Livy container and network cleanup verified.' \
    'Staged-file cleanup and full workshop reset are NOT verified.'
else
  status=$?
  printf '%s\n' 'ERROR: Spark/Livy teardown failed; cleanup remains unverified.' >&2
  exit "$status"
fi
