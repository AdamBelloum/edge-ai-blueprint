#!/usr/bin/env bash
# Workshop-owned Big Data reset entry point.
# Currently delegates verified Spark/Livy runtime teardown only.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: reset-workshop.sh --runtime-only --module spark

Remove ownership-verified Spark/Livy containers, the private network,
generated runtime files and the staged worker-side Spark seed/data bundle.
Requires administrative control of Docker and stopped participant servers.

Deletes generated runtime files, including submission logs, reports and outputs.
Deletes the staged participant seed/data bundle and verified locked Spark/Livy image references.
No forced image removal, Docker prune or unrelated image-reference deletion.
The global reset handles participant workspaces and its selected account option.
This local stage does not verify full workshop reset.
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
    'Big Data worker cleanup verified: containers, networks, locked image references, runtime files and staged seed/data.' \
    'Full workshop reset is NOT verified by this local helper; the global reset handles participant workspaces, account options and neutral reconciliation.'
else
  status=$?
  printf '%s\n' 'ERROR: Spark/Livy teardown failed; cleanup remains unverified.' >&2
  exit "$status"
fi
