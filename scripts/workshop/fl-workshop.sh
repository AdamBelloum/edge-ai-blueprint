#!/usr/bin/env bash
# Guided helper for a DIGITAfrica federated-learning workshop organiser.
#
# This script deliberately does not start a Flower server or clients because
# the correct invocation, data approval, and experiment configuration are
# application-specific. It prepares the organiser with verified platform and
# workspace evidence before the documented experiment procedure is followed.

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/workshop/fl-workshop.sh [--tier tier1|tier2] [--inventory PATH] [ACTION]

Options:
  --tier tier1|tier2  Select the deployment tier. Default: tier1.
  --inventory PATH   Override the Ansible inventory for this invocation.

Actions:
  menu              Show the interactive workshop-organiser menu. Default.
  preflight         Run platform and participant worker-runtime readiness checks.
  revisions         Record deployed source, dependency, and data evidence.
  inspect-workspaces  List application files in all assigned participant workspaces.
  checklist         Print the workshop readiness checklist.
  record-template   Print an experiment record template.
  help              Show this help text.

This helper does not launch training. Start a Flower server and clients only
with an experiment-specific command that has been reviewed against the current
application source and approved data-handling arrangements.
EOF
}

SELECTED_TIER="tier1"
INVENTORY_OVERRIDE=""
SELECTED_ACTION="menu"

while (($#)); do
  case "$1" in
    --tier)
      (($# >= 2)) || { printf '%s\n' "Missing value for --tier." >&2; usage >&2; exit 2; }
      SELECTED_TIER="$2"
      shift 2
      ;;
    --inventory)
      (($# >= 2)) || { printf '%s\n' "Missing value for --inventory." >&2; usage >&2; exit 2; }
      INVENTORY_OVERRIDE="$2"
      shift 2
      ;;
    menu|preflight|revisions|inspect-workspaces|checklist|record-template|help|--help|-h)
      if [[ "$SELECTED_ACTION" != "menu" ]]; then
        printf 'Only one action may be specified.\n' >&2
        usage >&2
        exit 2
      fi
      SELECTED_ACTION="$1"
      shift
      ;;
    *)
      printf 'Unknown option or action: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$SELECTED_TIER" in
  tier1|tier2)
    ;;
  *)
    printf 'Invalid tier: %s (expected tier1 or tier2).\n' "$SELECTED_TIER" >&2
    exit 2
    ;;
esac

if [[ -n "$INVENTORY_OVERRIDE" && ! -r "$INVENTORY_OVERRIDE" ]]; then
  printf 'Inventory is not readable: %s\n' "$INVENTORY_OVERRIDE" >&2
  exit 2
fi

export DIGITAFRICA_DEPLOYMENT_TIER="$SELECTED_TIER"
export DIGITAFRICA_DEPLOYMENT_GROUP="${SELECTED_TIER}_server"
if [[ -n "$INVENTORY_OVERRIDE" ]]; then
  export DIGITAFRICA_INVENTORY="$INVENTORY_OVERRIDE"
fi

# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"
readonly HEALTH_SCRIPT="${DIGITAFRICA_SCRIPTS_DIR}/admin/health-check.sh"

require_workshop_scripts() {
  require_file "${HEALTH_SCRIPT}"
}

run_preflight() {
  print_heading "Workshop platform preflight"
  require_workshop_scripts

  log "Running infrastructure, JupyterHub static, and participant worker-runtime checks."
  bash "${HEALTH_SCRIPT}" all

  cat <<'EOF'

Manual checks still required before participants arrive:
  1. Open the public JupyterHub URL in a browser.
  2. Authenticate using the workshop identity method.
  3. Spawn a real user server.
  4. Confirm the assigned group ID and local partition path are visible.
  5. Confirm the intended seeded notebooks are visible.
  6. Create and reopen a small test file to confirm expected persistence.
  7. Run the guided local-data notebook and the guided Flower-client notebook
     with a real participant account before the workshop starts.
EOF
}

resolve_participant_workers() {
  local worker_group
  local topology_output
  local index
  local worker

  worker_group="$(deployment_worker_group)"
  command -v ansible-inventory >/dev/null 2>&1 ||
    die "Required command not found: ansible-inventory"

  if ! topology_output="$(
    ansible-inventory -i "${DIGITAFRICA_INVENTORY}" --list |
      python3 -c '
import json
import sys

inventory = json.load(sys.stdin)
group = inventory.get(sys.argv[1])
if not isinstance(group, dict) or not isinstance(group.get("hosts"), list):
    raise SystemExit("missing ordered inventory worker group: " + sys.argv[1])

for host in group["hosts"]:
    if not isinstance(host, str) or not host:
        raise SystemExit("invalid worker name in inventory")
    print(host)
' "$worker_group"
  )"; then
    die "Could not resolve ordered workers from inventory group: $worker_group"
  fi

  mapfile -t WORKSHOP_WORKERS < <(printf '%s\n' "$topology_output" | sed '/^$/d')
  ((${#WORKSHOP_WORKERS[@]} > 0)) ||
    die "Inventory worker group $worker_group has no workers."

  WORKSHOP_GROUP_IDS=()
  for index in "${!WORKSHOP_WORKERS[@]}"; do
    worker="${WORKSHOP_WORKERS[$index]}"
    [[ "$worker" =~ ^[A-Za-z0-9_.-]+$ ]] ||
      die "Unsafe worker name from inventory: ${worker@Q}"
    WORKSHOP_GROUP_IDS+=("$(printf 'group_%02d' "$((index + 1))")")
  done
}

show_revisions_and_server_entrypoint() {
  local worker
  local group_id
  local index
  local central_runtime_root="${FLOWER_RUNTIME_ROOT:-/home/adam/fl-workshop}"
  local worker_runtime_root="${WORKSHOP_RUNTIME_ROOT:-/opt/digitafrica/fl-workshop}"

  print_heading "Deployed application and dependency evidence"
  resolve_participant_workers

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
printf '%s\n' '===== Prepared server entry point ====='
test -r "$central_runtime_root/app/server/server.py"
sha256sum "$central_runtime_root/app/server/server.py"
test -r "$central_runtime_root/app/requirements.lock"
sha256sum "$central_runtime_root/app/requirements.lock"
REMOTE
)"

  for index in "${!WORKSHOP_WORKERS[@]}"; do
    worker="${WORKSHOP_WORKERS[$index]}"
    group_id="${WORKSHOP_GROUP_IDS[$index]}"

    printf '\n===== %s / %s =====\n' "$group_id" "$worker"
    run_inventory_target_remote "$worker" "$(cat <<REMOTE
set -euo pipefail
cd "$worker_runtime_root"
sha256sum \
  app/client/client.py \
  app/requirements.lock \
  data/partition-manifest.json \
  data/train.csv
REMOTE
)"
  done

  cat <<'EOF'

Record the edge-ai-blueprint commit from the release record together with these
checksums. Together they identify the server source, dependency lock, partition
manifest, and each prepared participant partition used in the workshop.
EOF
}

inspect_all_participant_sources() {
  local worker
  local group_id
  local index
  local worker_runtime_root="${WORKSHOP_RUNTIME_ROOT:-/opt/digitafrica/fl-workshop}"

  print_heading "Inspecting prepared participant runtime workspaces"
  resolve_participant_workers

  for index in "${!WORKSHOP_WORKERS[@]}"; do
    worker="${WORKSHOP_WORKERS[$index]}"
    group_id="${WORKSHOP_GROUP_IDS[$index]}"

    printf '\n===== %s / %s =====\n' "$group_id" "$worker"
    run_inventory_target_remote "$worker" "$(cat <<REMOTE
set -euo pipefail
cd "$worker_runtime_root"
echo "===== Runtime root ====="
pwd
echo "===== Files, depth three ====="
find . -maxdepth 3 -type f | sort | head -n 160
echo "===== Prepared asset checksums ====="
sha256sum app/client/client.py app/requirements.lock data/partition-manifest.json data/train.csv
REMOTE
)"
  done
}

print_checklist() {
  cat <<'EOF'

DIGITAfrica federated-learning workshop checklist

Before the workshop
  [ ] Infrastructure preflight passed.
  [ ] A real JupyterHub participant login and spawn were tested.
  [ ] Deployed source, dependency, manifest, and partition checksums were recorded.
  [ ] Server entry point and supported experiment configuration were reviewed.
  [ ] Flower/Python dependency versions were recorded.
  [ ] Each dataset has an approved owner, location, version, and permitted use.
  [ ] No raw private data is stored in the shared source repository.
  [ ] Server address, transport security, and any authentication settings were confirmed.
  [ ] Storage location and access controls for logs, metrics, and models were agreed.
  [ ] A fallback plan exists if a participant worker, network connection, or client fails.

At the start of the experiment
  [ ] Record the experiment identifier, date, and responsible organiser.
  [ ] Record the server command and complete configuration.
  [ ] Record the client command for each participating group.
  [ ] After explicit organiser confirmation, start the server and then the intended clients.
  [ ] Confirm each expected participant client registers with the server.

During and after the experiment
  [ ] Record completed rounds and unexpected events.
  [ ] Preserve server and client logs.
  [ ] Preserve metrics and model/checkpoint artefacts.
  [ ] Record deviations from the original plan.
  [ ] Stop application processes deliberately.
  [ ] Store the completed experiment record with the outputs.
EOF
}

print_record_template() {
  cat <<'EOF'
# Federated-learning experiment record

## Identification

- Experiment identifier:
- Date and time:
- Workshop organiser:
- Participants and participating groups:

## Platform and source provenance

- Blueprint repository revision:
- Inventory/environment identifier:
- Selected deployment tier and inventory/environment identifier:
- Server source repository, reference, and commit SHA:
- Participant group source repository, reference, and commit SHA:
- Python and Flower versions:

## Data and governance

- Participant group dataset identifier, version, owner, and approved location:
- Data permissions and applicable governance/ethics conditions:
- Security and transport settings:

## Experiment configuration

- Server command:
- Participant group client command:
- Model and initialisation:
- Aggregation strategy:
- Number of planned rounds:
- Local epochs, batch size, optimiser, and learning rate:
- Metrics collected:

## Execution evidence

- Server start time:
- Client registration evidence:
- Completed rounds:
- Failures, retries, dropouts, or deviations:
- Server log location:
- Participant group client log location:

## Outputs and interpretation

- Model/checkpoint location:
- Metrics location:
- Main result:
- Limitations and comparability notes:
- End time:
EOF
}

interactive_menu() {
  local choice

  while true; do
    print_heading "DIGITAfrica federated-learning workshop helper"
    show_context
    cat <<'EOF'

Choose an action:
  1) Run workshop platform preflight
  2) Show source revisions and server entry-point evidence
  3) Inspect all assigned participant workspaces
  4) Show workshop readiness checklist
  5) Show experiment record template
  0) Exit
EOF
    read -r -p "Selection: " choice

    case "${choice}" in
      1) run_preflight ;;
      2) show_revisions_and_server_entrypoint ;;
      3) inspect_all_participant_sources ;;
      4) print_checklist ;;
      5) print_record_template ;;
      0) log "Exiting."; return 0 ;;
      *) warn "Choose a number from 0 to 6." ;;
    esac
  done
}

main() {
  local action="${1:-menu}"

  case "${action}" in
    menu)
      interactive_menu
      ;;
    preflight)
      run_preflight
      ;;
    revisions)
      show_revisions_and_server_entrypoint
      ;;
    inspect-workspaces)
      inspect_all_participant_sources
      ;;
    checklist)
      print_checklist
      ;;
    record-template)
      print_record_template
      ;;
    help|--help|-h)
      usage
      ;;
    *)
      usage >&2
      die "Unknown action: ${action}"
      ;;
  esac
}

main "$SELECTED_ACTION"
