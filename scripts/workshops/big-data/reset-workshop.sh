#!/usr/bin/env bash
# Workshop-owned Big Data reset entry point.
# Delegates worker runtime, Kubernetes credentials and local SSH export cleanup.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: reset-workshop.sh --runtime-only --module spark

Remove ownership-verified Spark/Livy containers, the private network,
generated runtime files and the staged worker-side Spark seed/data bundle.
Requires administrative control of Docker and stopped participant servers.
No concurrent credential generation, staging or workshop preparation.
Removes reviewed SSH exports for selected inventory workers on the organiser host.
Preserves other worker exports, bind configuration and unrelated secrets.

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
credentials="$SCRIPT_DIR/spark/cleanup-credentials.sh"
exports="$SCRIPT_DIR/spark/cleanup-local-exports.sh"

[[ -x "$teardown" ]] || {
  printf 'ERROR: Missing executable Spark teardown helper: %s\n' "$teardown" >&2
  exit 2
}
[[ -x "$credentials" ]] || {
  printf 'ERROR: Missing executable Spark credential cleanup helper: %s\n' "$credentials" >&2
  exit 2
}

[[ -x "$exports" ]] || {
  printf 'ERROR: Missing executable Spark local-export cleanup helper: %s\n' "$exports" >&2
  exit 2
}

printf '%s\n' 'Big Data reset: validating local SSH exports without deletion.'
if "$exports" --check; then
  printf '%s\n' 'Big Data local-export preflight passed; no export files deleted.'
else
  status=$?
  printf '%s\n' 'ERROR: Spark local-export preflight failed; runtime teardown was not started.' >&2
  exit "$status"
fi

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

printf '%s\n' 'Big Data reset: removing organiser-staged Spark participant credentials.'
if "$credentials" --execute; then
  printf '%s\n' 'Big Data credential cleanup verified: no labelled Spark credential Secret or ConfigMap remains.'
  printf '%s\n' \
    'NOTE: Participant homes keep their existing ~/.ssh/spark-direct credentials; this runtime-only reset does not touch them.' \
    'Unmodified credentials with a valid organiser marker can rotate at the next server start after new credentials are staged; conflicts block startup.' \
    'Init:CrashLoopBackOff on digitafrica-spark-credentials is a startup failure, not a unique credential diagnosis.' \
    'Possible causes include missing staged resources, group/node binding mismatch, filesystem errors or conflicting credentials.' \
    'Inspect the sanitised init-container status/reason and group/node binding first; never log credential payloads.' \
    'Do not automatically delete ~/.ssh/spark-direct or reset participant workspaces; use reviewed recovery after confirming the cause.'
else
  status=$?
  printf '%s\n' 'ERROR: Spark credential cleanup failed; cleanup remains unverified.' >&2
  exit "$status"
fi

printf '%s\n' 'Big Data reset: removing selected worker SSH exports on the organiser host.'
if "$exports" --execute; then
  printf '%s\n' \
    'Big Data local-export cleanup verified: selected worker SSH export directories are absent.' \
    'Full workshop reset is NOT verified by this local helper.'
else
  status=$?
  printf '%s\n' 'ERROR: Spark local-export cleanup failed; cleanup remains unverified.' >&2
  exit "$status"
fi
