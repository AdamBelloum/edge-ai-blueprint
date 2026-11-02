#!/usr/bin/env bash
# Callable pilot integration; final organiser menu belongs to Task 4.
set -Eeuo pipefail

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  printf '%s\n' \
    'Usage: warm-transition.sh --limit EXACT_HOST [--syntax-check]' \
    'Stages candidate assets, builds the isolated image, then verifies the runtime.' \
    'Reuses Step 1; no account creation, workspace publication or reset.' \
    'Requires participants and other administrators to pause submissions/writes.' \
    'Participant SSH-forwarded REST computation is NOT verified here.'
  exit 0
fi

pilot=''
syntax=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit)
      [[ -z "$pilot" && $# -ge 2 ]] || {
        printf 'ERROR: one --limit host required.\n' >&2; exit 2;
      }
      pilot="$2"
      shift 2
      ;;
    --syntax-check)
      [[ "$syntax" == false ]] || {
        printf 'ERROR: duplicate syntax flag.\n' >&2; exit 2;
      }
      syntax=true
      shift
      ;;
    *)
      printf 'ERROR: use --limit EXACT_HOST [--syntax-check].\n' >&2
      exit 2
      ;;
  esac
done

[[ "$pilot" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]] || {
  printf 'ERROR: exact pilot hostname required, not an expression.\n' >&2
  exit 2
}
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
expected_root="$(cd -- "$SCRIPT_DIR/../../../.." && pwd -P)"
source "$SCRIPT_DIR/../../lib/workshop-context.sh"
load_workshop_context
: "${DIGITAFRICA_INVENTORY:?Inventory missing from release context}"
: "${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:?Worker group missing from release context}"
: "${WORKSHOP_CONTEXT_REPOSITORY_ROOT:?Repository root missing from release context}"

[[ "$(cd -- "$WORKSHOP_CONTEXT_REPOSITORY_ROOT" && pwd -P)" == "$expected_root" ]] || {
  printf 'ERROR: release context points to a different checkout.\n' >&2
  exit 2
}
for command in python ansible-inventory ansible-playbook; do
  command -v "$command" >/dev/null || {
    printf 'ERROR: required command missing: %s\n' "$command" >&2
    exit 2
  }
done

python "$SCRIPT_DIR/livy_transition_scope.py" \
  "$DIGITAFRICA_INVENTORY" "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" "$pilot"

confirmed=false
options=()
if [[ "$syntax" == true ]]; then
  options+=(--syntax-check)
  printf 'Syntax check only for exact pilot %s; no VM tasks.\n' "$pilot"
else
  printf '%s\n' \
    "Exact pilot: $pilot" \
    'Participants must not submit; other administrators must not alter Docker/runtime files.' \
    'The direct client will stop; only missing Livy services may start.' \
    'No automatic rollback. Participant REST computation remains unverified.'
  answer=''
  read -r -p "Type transition-${pilot}-submissions-paused to confirm: " answer || exit 1
  [[ "$answer" == "transition-${pilot}-submissions-paused" ]] || exit 1
  confirmed=true
fi

extra="$(python - "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" "$pilot" "$confirmed" <<'JSON'
import json
import sys
print(json.dumps({
    "big_data_worker_group": sys.argv[1],
    "big_data_livy_pilot_host": sys.argv[2],
    "big_data_livy_stage_maintenance_confirmed": sys.argv[3] == "true",
    "big_data_livy_build_candidate": True,
    "big_data_livy_transition_maintenance_confirmed": sys.argv[3] == "true",
    "big_data_livy_transition_submissions_paused": sys.argv[3] == "true",
}))
JSON
)"

exec ansible-playbook \
  -i "$DIGITAFRICA_INVENTORY" \
  "$WORKSHOP_CONTEXT_REPOSITORY_ROOT/playbooks/transition-big-data-spark-livy.yml" \
  --limit "$pilot" --extra-vars "$extra" "${options[@]}"
