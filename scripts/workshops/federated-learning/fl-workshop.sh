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
WORKSHOP_CONTEXT="$SCRIPT_DIR/../lib/workshop-context.sh"
ORGANIZER_RUNTIME="$SCRIPT_DIR/../lib/organizer-runtime.sh"
COHORT_WORKFLOW="$SCRIPT_DIR/../identity/cohort-workshop.sh"
WORKSHOP_READINESS_CHECKER="$SCRIPT_DIR/check-workshop-readiness.sh"
COHORT_MAPPING_HELPER="$SCRIPT_DIR/../identity/reconcile-cohort-mapping.sh"
FLOWER_MANAGER="$SCRIPT_DIR/manage-flower-server.sh"

# Shared presentation for this standalone executable.
# shellcheck source=../lib/organizer-ui.sh
source "$SCRIPT_DIR/../lib/organizer-ui.sh"

usage() {
  cat <<'EOF'
Usage: scripts/workshops/fl-workshop.sh [ACTION]

Actions:
  menu              Show the interactive workshop-organiser menu. Default.
  preflight         Run organiser-owned workshop readiness checks.
  revisions         Record deployed source, dependency, and data evidence.
  inspect-workspaces  List application files in all assigned participant workspaces.
  checklist         Print the workshop readiness checklist.
  record-template   Print an experiment record template.
  tutorial-state    Show the current tutorial mode and solution-release state.
  set-tutorial-mode beginner|advanced
                    Set the tutorial mode for subsequently spawned servers.
  release-solutions Release reference solutions for an advanced workshop.
  new-cohort beginner|advanced [--yes]
                    Delete participant workspaces and initialise a fresh cohort.
                    --yes confirms the destructive workspace reset explicitly.
  prepare beginner|advanced [--yes]
                    Verify readiness, initialise a fresh cohort, and start Flower.
  flower            Manage the organiser-controlled Flower server.
  reconcile-cohort-mapping
                    Re-render inventory-derived JupyterHub group placement and
                    reconcile only the JupyterHub Helm release.
  delete-workspaces [--yes]
                    Delete participant workspaces without changing tutorial state.
  help              Show this help text.

This helper manages only the organiser-controlled Flower server. Participant
clients remain participant-driven and must use reviewed application source and
approved data-handling arrangements.
EOF
}

SELECTED_ACTION="menu"
TUTORIAL_MODE=""
COHORT_MODE=""
ASSUME_COHORT_RESET=false

while (($#)); do
  case "$1" in
    --yes)
      ASSUME_COHORT_RESET=true
      shift
      ;;
    menu|preflight|revisions|inspect-workspaces|checklist|record-template|tutorial-state|release-solutions|reconcile-cohort-mapping|delete-workspaces|flower|help|--help|-h)
      if [[ "$SELECTED_ACTION" != "menu" ]]; then
        printf 'Only one action may be specified.\n' >&2
        usage >&2
        exit 2
      fi
      SELECTED_ACTION="$1"
      shift
      ;;
    set-tutorial-mode)
      if [[ "$SELECTED_ACTION" != "menu" ]]; then
        printf 'Only one action may be specified.\n' >&2
        usage >&2
        exit 2
      fi
      (($# >= 2)) || {
        printf 'set-tutorial-mode requires beginner or advanced.\n' >&2
        usage >&2
        exit 2
      }
      case "$2" in
        beginner|advanced) ;;
        *)
          printf 'Invalid tutorial mode: %s (expected beginner or advanced).\n' "$2" >&2
          exit 2
          ;;
      esac
      SELECTED_ACTION="set-tutorial-mode"
      TUTORIAL_MODE="$2"
      shift 2
      ;;
    prepare)
      if [[ "$SELECTED_ACTION" != "menu" ]]; then
        printf 'Only one action may be specified.\n' >&2
        usage >&2
        exit 2
      fi
      (($# >= 2)) || {
        printf 'prepare requires beginner or advanced.\n' >&2
        usage >&2
        exit 2
      }
      case "$2" in
        beginner|advanced) ;;
        *)
          printf 'Invalid preparation mode: %s (expected beginner or advanced).\n' "$2" >&2
          exit 2
          ;;
      esac
      SELECTED_ACTION="prepare"
      COHORT_MODE="$2"
      shift 2
      ;;
    new-cohort)
      if [[ "$SELECTED_ACTION" != "menu" ]]; then
        printf 'Only one action may be specified.\n' >&2
        usage >&2
        exit 2
      fi
      (($# >= 2)) || {
        printf 'new-cohort requires beginner or advanced.\n' >&2
        usage >&2
        exit 2
      }
      case "$2" in
        beginner|advanced) ;;
        *)
          printf 'Invalid cohort mode: %s (expected beginner or advanced).\n' "$2" >&2
          exit 2
          ;;
      esac
      SELECTED_ACTION="new-cohort"
      COHORT_MODE="$2"
      shift 2
      ;;
    *)
      printf 'Unknown option or action: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if "$ASSUME_COHORT_RESET"; then
  case "$SELECTED_ACTION" in
    new-cohort|delete-workspaces|prepare) ;;
    *)
      printf '%s\n' '--yes is valid only with new-cohort, prepare, or delete-workspaces.' >&2
      exit 2
      ;;
  esac
fi

[[ -r "$WORKSHOP_CONTEXT" ]] || {
  printf 'Missing workshop context helper: %s\n' "$WORKSHOP_CONTEXT" >&2
  exit 2
}
# shellcheck source=workshop-context.sh
source "$WORKSHOP_CONTEXT"
if ! load_workshop_context; then
  exit 2
fi

# shellcheck source=../../lib/common.sh
source "${SCRIPT_DIR}/../../lib/common.sh"

[[ -r "$ORGANIZER_RUNTIME" ]] ||
  die "Missing organiser runtime helper: $ORGANIZER_RUNTIME"
# shellcheck source=../lib/organizer-runtime.sh
source "$ORGANIZER_RUNTIME"

run_preflight() {
  print_heading "Workshop platform preflight"
  [[ -x "$WORKSHOP_READINESS_CHECKER" ]] ||
    die "Workshop readiness checker is missing or not executable: $WORKSHOP_READINESS_CHECKER"

  log "Running organiser-owned workshop readiness checks."
  bash "$WORKSHOP_READINESS_CHECKER" --non-interactive

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

run_flower_manager_menu() {
  local choice
  local rounds
  local min_clients

  while true; do
    workshop_ui_heading "Federated Learning / Flower server"
    workshop_ui_section "INSPECT"
    workshop_ui_option 1 "Show status and effective parameters"
    workshop_ui_option 6 "Show recent server logs"
    workshop_ui_section "LIFECYCLE"
    workshop_ui_option 2 "Start server"
    workshop_ui_option 3 "Stop server"
    workshop_ui_option 4 "Restart server"
    workshop_ui_section "CONFIGURE"
    workshop_ui_option 5 "Set rounds and required clients"
    workshop_ui_note "Configuration leaves the server stopped."
    printf '\n'
    workshop_ui_option 0 "Back"
    workshop_ui_prompt
    read -r choice
    case "$choice" in
      1) "$FLOWER_MANAGER" status ;;
      2)
        ensure_workshop_activation_allowed federated-learning
        "$FLOWER_MANAGER" start
        ;;
      3) "$FLOWER_MANAGER" stop ;;
      4)
        ensure_workshop_activation_allowed federated-learning
        "$FLOWER_MANAGER" restart
        ;;
      5)
        read -r -p "Number of federated-training rounds: " rounds
        read -r -p "Required participating clients in every round: " min_clients
        "$FLOWER_MANAGER" configure --rounds "$rounds" --min-clients "$min_clients"
        ;;
      6) "$FLOWER_MANAGER" logs ;;
      0) return 0 ;;
      *) warn "Choose a number from 0 to 6." ;;
    esac
  done
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
    workshop_ui_heading "DIGITAfrica / Federated Learning helper"
    show_context
    workshop_ui_section "CHECK AND INSPECT"
    workshop_ui_option 1 "Run platform preflight"
    workshop_ui_option 2 "Show source revisions and server entry-point evidence"
    workshop_ui_option 3 "Inspect participant workspaces"
    workshop_ui_option 6 "Show tutorial mode and solution-release state"
    workshop_ui_section "WORKSHOP RECORDS"
    workshop_ui_option 4 "Show readiness checklist"
    workshop_ui_option 5 "Show experiment record template"
    workshop_ui_section "PREPARE"
    workshop_ui_option 7 "Set tutorial mode for new participant spawns"
    workshop_ui_option 9 "Start a fresh cohort"
    workshop_ui_option 10 "Prepare fresh workshop and start Flower"
    workshop_ui_note "Options 9 and 10 reset participant workspaces."
    workshop_ui_section "RUNTIME"
    workshop_ui_option 11 "Manage Flower server"
    workshop_ui_section "AFTER THE WORKSHOP"
    workshop_ui_option 8 "Release advanced reference solutions"
    printf '\n'
    workshop_ui_option 0 "Exit"
    workshop_ui_prompt
    read -r choice

    case "${choice}" in
      1) run_preflight ;;
      2) show_revisions_and_server_entrypoint ;;
      3) inspect_all_participant_sources ;;
      4) print_checklist ;;
      5) print_record_template ;;
      6) show_tutorial_state ;;
      7)
        read -r -p "Tutorial mode (beginner/advanced): " choice
        case "$choice" in
          beginner|advanced) set_tutorial_mode "$choice" ;;
          *) warn "Choose beginner or advanced." ;;
        esac
        ;;
      8) release_reference_solutions ;;
      9)
        read -r -p "New cohort mode (beginner/advanced): " choice
        case "$choice" in
          beginner|advanced) start_new_cohort "$choice" ;;
          *) warn "Choose beginner or advanced." ;;
        esac
        ;;
      10)
        read -r -p "Preparation mode (beginner/advanced): " choice
        case "$choice" in
          beginner|advanced) prepare_federated_learning_workshop "$choice" ;;
          *) warn "Choose beginner or advanced." ;;
        esac
        ;;
      11) run_flower_manager_menu ;;
      0) log "Exiting."; return 0 ;;
      *) warn "Choose a number from 0 to 11." ;;
    esac
  done
}

main() {
  local action="${1:-menu}"

  case "${action}" in
    menu)
      workshop_ui_heading "Welcome to DIGITAfrica Federated Learning"
      workshop_ui_note "Prepare workshops, inspect readiness, and manage Flower."
      workshop_ui_note "Fresh-cohort actions reset participant workspaces."
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
    tutorial-state)
      show_tutorial_state
      ;;
    set-tutorial-mode)
      set_tutorial_mode "$TUTORIAL_MODE"
      ;;
    release-solutions)
      release_reference_solutions
      ;;
    reconcile-cohort-mapping)
      exec "$SCRIPT_DIR/../identity/reconcile-cohort-mapping.sh"
      ;;
    new-cohort)
      start_new_cohort "$COHORT_MODE"
      ;;
    prepare)
      prepare_federated_learning_workshop "$COHORT_MODE"
      ;;
    flower)
      run_flower_manager_menu
      ;;
    delete-workspaces)
      start_new_cohort ""
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

# Lifecycle implementations share this dispatcher's loaded context.
# shellcheck source=prepare-workshop.sh
source "$SCRIPT_DIR/prepare-workshop.sh"
# shellcheck source=publish-workshop.sh
source "$SCRIPT_DIR/publish-workshop.sh"

main "$SELECTED_ACTION"
