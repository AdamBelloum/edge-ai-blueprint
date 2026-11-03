#!/usr/bin/env bash
# Callable pilot integration; final organiser menu belongs to Task 4.
set -Eeuo pipefail

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  printf '%s\n' \
    'Usage: warm-transition.sh --all-workers [--syntax-check]; compatibility: --limit EXACT_HOST [--syntax-check]' \
    'Stages candidate assets, builds the isolated image, then verifies the runtime.' \
    'Reuses Step 1; no account creation, workspace publication or reset.' \
    'Requires participants and other administrators to pause submissions/writes.' \
    'Participant SSH-forwarded REST computation is NOT verified here.'
  exit 0
fi

# Inventory-cohort mode used by the organiser menu.
# The exact-host compatibility implementation below remains unchanged.
if [[ "${1:-}" == --all-workers ]]; then
  shift
  cohort_syntax=false
  if [[ $# -eq 1 && "$1" == --syntax-check ]]; then
    cohort_syntax=true
    shift
  fi
  [[ $# -eq 0 ]] || {
    printf 'ERROR: use --all-workers [--syntax-check]; do not combine scopes.\n' >&2
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
  for command in python ansible-playbook; do
    command -v "$command" >/dev/null || {
      printf 'ERROR: required command missing: %s\n' "$command" >&2
      exit 2
    }
  done
  umask 077
  cohort_temp="$(mktemp -d)"
  trap 'rm -rf -- "$cohort_temp"' EXIT
  python "$SCRIPT_DIR/livy_cohort_scope.py" \
    "$DIGITAFRICA_INVENTORY" "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" \
    > "$cohort_temp/plan.json"
  python - "$cohort_temp/plan.json" <<'PLAN'
import json, sys
plan = json.load(open(sys.argv[1]))
print('Inventory-derived local Livy targets:')
for item in plan['groups']:
    print(f"  {item['group_id']} -> {item['worker']}")
print(f"Total worker VMs: {len(plan['groups'])}")
PLAN
  cohort_confirmed=false
  cohort_options=()
  if [[ "$cohort_syntax" == true ]]; then
    cohort_options+=(--syntax-check)
    printf 'Configuration check for all inventory workers; no VM tasks.\n'
  else
    printf '\n%s\n' \
      'NOTE ============================================================' \
      'Switch all inventory-derived worker VMs to local Livy submission?' \
      'Reuse Step 1 credentials, SSH endpoints and participant workspaces.' \
      'Participant submissions must be paused on ALL workers.' \
      'Other administrators must not alter Docker or runtime files.' \
      'Direct clients will stop; missing local Livy services may start.' \
      'Stop on failure; no automatic rollback or retry.' \
      'Participant SSH-forwarded computation remains unverified.' \
      '================================================================='
    cohort_answer=''
    IFS= read -r -p 'Continue? [y/N]: ' cohort_answer || exit 1
    [[ "$cohort_answer" =~ ^[yY]$ ]] || exit 1
    cohort_confirmed=true
  fi
  # File transport avoids command-line size limits as the cohort grows.
  python - "$cohort_temp/plan.json" "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" \
    "$cohort_confirmed" > "$cohort_temp/vars.json" <<'VARS'
import json, sys
workers = [item['worker'] for item in json.load(open(sys.argv[1]))['groups']]
confirmed = sys.argv[3] == 'true'
print(json.dumps({
    'big_data_worker_group': sys.argv[2],
    'big_data_livy_cohort_workers': workers,
    'big_data_livy_stage_maintenance_confirmed': confirmed,
    'big_data_livy_build_candidate': True,
    'big_data_livy_transition_maintenance_confirmed': confirmed,
    'big_data_livy_transition_submissions_paused': confirmed,
}))
VARS
  # Independent playbook guards require the complete canonical worker scope.
  ansible-playbook -i "$DIGITAFRICA_INVENTORY" \
    "$WORKSHOP_CONTEXT_REPOSITORY_ROOT/playbooks/transition-big-data-spark-livy.yml" \
    --limit "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" \
    --extra-vars "@$cohort_temp/vars.json" "${cohort_options[@]}"
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
  printf 'ERROR: a single valid workshop machine name is required.\n' >&2
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
  printf 'Configuration check only for workshop machine %s; no VM tasks.\n' "$pilot"
else
  printf '%s\n' \
    'Other administrators must not alter runtime files during this operation.' \
    'The direct submission client will stop; missing Livy services may start.' \
    'No automatic rollback. Participant access via Livy remains unverified.'
  printf '\n%s\n' \
    'NOTE ============================================================' \
    "Switch the selected workshop machine ($pilot) to Livy submission mode?" \
    'Participant submissions must be paused.' \
    'Returning to direct submission requires RESET.' \
    '================================================================='
  answer=''
  IFS= read -r -p 'Continue? [y/N]: ' answer || exit 1
  [[ "$answer" =~ ^[yY]$ ]] || exit 1
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
