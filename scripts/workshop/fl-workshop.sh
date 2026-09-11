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
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"

readonly HEALTH_SCRIPT="${DIGITAFRICA_SCRIPTS_DIR}/admin/health-check.sh"

usage() {
  cat <<'EOF'
Usage: scripts/workshop/fl-workshop.sh [ACTION]

Actions:
  menu              Show the interactive workshop-organiser menu. Default.
  preflight         Run platform and Silo workspace readiness checks.
  revisions         Record deployed source, dependency, and data evidence.
  inspect-silos     List application files in all detected Silo workspaces.
  checklist         Print the workshop readiness checklist.
  record-template   Print an experiment record template.
  help              Show this help text.

This helper does not launch training. Start a Flower server and clients only
with an experiment-specific command that has been reviewed against the current
application source and approved data-handling arrangements.
EOF
}

require_workshop_scripts() {
  require_file "${HEALTH_SCRIPT}"
}

run_preflight() {
  print_heading "Workshop platform preflight"
  require_workshop_scripts

  log "Running infrastructure, JupyterHub static, and Silo workspace checks."
  bash "${HEALTH_SCRIPT}" all

  cat <<'EOF'

Manual checks still required before participants arrive:
  1. Open the public JupyterHub URL in a browser.
  2. Authenticate using the workshop identity method.
  3. Spawn a real user server.
  4. Confirm the intended seeded notebooks are visible.
  5. Create and reopen a small test file to confirm expected persistence.
EOF
}

show_revisions_and_server_entrypoint() {
  local remote_script

  print_heading "Deployed application and dependency evidence"

  remote_script="$(cat <<'REMOTE_SCRIPT'
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

printf '%s\n' '===== Prepared server entry point ====='
test -r /home/adam/fl-workshop/app/server/server.py
sha256sum /home/adam/fl-workshop/app/server/server.py
test -r /home/adam/fl-workshop/app/requirements.lock
sha256sum /home/adam/fl-workshop/app/requirements.lock

printf '%s\n' '===== Silo mounted runtime evidence ====='
mapfile -t deployments < <(
  k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get deployments \
    -l app=fl-client-silo \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort
)

if [ "${#deployments[@]}" -eq 0 ]; then
  echo 'ERROR: no numbered Silo deployments found.' >&2
  exit 1
fi

for deployment in "${deployments[@]}"; do
  silo_id="${deployment#fl-client-silo-}"
  pod="$(k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get pods \
    -l "app=fl-client-silo,digitafrica.org/silo-id=${silo_id}" \
    -o jsonpath='{.items[0].metadata.name}')"

  test -n "${pod}"
  printf '%s\n' "===== ${deployment} ====="
  k3s kubectl -n __DIGITAFRICA_NAMESPACE__ exec "${pod}" -- sh -ec '
    sha256sum \
      /workspace/app/client/client.py \
      /workspace/app/requirements.lock \
      /workspace/data/partition-manifest.json \
      /workspace/data/train.csv
  '
done
REMOTE_SCRIPT
)"

  remote_script="${remote_script//__DIGITAFRICA_NAMESPACE__/${DIGITAFRICA_NAMESPACE}}"
  run_tier1_remote "${remote_script}"

  cat <<'EOF'

Record the edge-ai-blueprint commit from the release record together with these
deployed checksums. Together they identify the source, dependency lock,
partition manifest, and per-Silo data partition used in the workshop.
EOF
}
inspect_silo_source() {
  local deployment="$1"
  local silo_id="${deployment#fl-client-silo-}"

  print_heading "Inspecting ${deployment} mounted application workspace"

  run_tier1_remote "$(cat <<EOF
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

pod=\$(k3s kubectl -n ${DIGITAFRICA_NAMESPACE} get pods \
  -l "app=fl-client-silo,digitafrica.org/silo-id=${silo_id}" \
  -o jsonpath='{.items[0].metadata.name}')

test -n "\${pod}"
k3s kubectl -n ${DIGITAFRICA_NAMESPACE} exec "\${pod}" -- sh -ec '
  cd /workspace
  echo "===== Working directory ====="
  pwd
  echo "===== Files, depth three ====="
  find . -maxdepth 3 -type f | sort | head -n 160
  echo "===== Mounted asset checksums ====="
  sha256sum app/client/client.py app/requirements.lock data/partition-manifest.json data/train.csv
'
EOF
)"
}
inspect_all_silo_sources() {
  local remote_script

  print_heading "Inspecting all detected Silo mounted application workspaces"

  remote_script="$(cat <<'REMOTE_SCRIPT'
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

mapfile -t deployments < <(
  k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get deployments \
    -l app=fl-client-silo \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | sort
)

if [ "${#deployments[@]}" -eq 0 ]; then
  echo 'ERROR: no numbered Silo deployments found.' >&2
  exit 1
fi

for deployment in "${deployments[@]}"; do
  pod="$(k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get pods \
    -l "app=fl-client-silo,digitafrica.org/silo-id=${deployment#fl-client-silo-}" \
    -o jsonpath='{.items[0].metadata.name}')"

  printf '\n===== %s =====\n' "${deployment}"
  k3s kubectl -n __DIGITAFRICA_NAMESPACE__ exec "${pod}" -- sh -ec '
    cd /workspace
    find . -maxdepth 3 -type f | sort | head -n 80
    sha256sum app/client/client.py app/requirements.lock data/partition-manifest.json data/train.csv
  '
done
REMOTE_SCRIPT
)"

  remote_script="${remote_script//__DIGITAFRICA_NAMESPACE__/${DIGITAFRICA_NAMESPACE}}"
  run_tier1_remote "${remote_script}"
}
print_checklist() {
  cat <<'EOF'

DIGITAfrica federated-learning workshop checklist

Before the workshop
  [ ] Infrastructure preflight passed.
  [ ] A real JupyterHub user login and spawn were tested.
  [ ] Deployed source, dependency, manifest, and partition checksums were recorded.
  [ ] Server entry point and supported experiment configuration were reviewed.
  [ ] Flower/Python dependency versions were recorded.
  [ ] Each dataset has an approved owner, location, version, and permitted use.
  [ ] No raw private data is stored in the shared source repository.
  [ ] Server address, transport security, and any authentication settings were confirmed.
  [ ] Storage location and access controls for logs, metrics, and models were agreed.
  [ ] A fallback plan exists if a Silo, network connection, or client fails.

At the start of the experiment
  [ ] Record the experiment identifier, date, and responsible organiser.
  [ ] Record the server command and complete configuration.
  [ ] Record the client command for each participating Silo.
  [ ] Start the server, then the intended clients.
  [ ] Confirm each expected client registers with the server.

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
- Participants and participating Silos:

## Platform and source provenance

- Blueprint repository revision:
- Inventory/environment identifier:
- Tier-1 namespace:
- Server source repository, reference, and commit SHA:
- Silo A source repository, reference, and commit SHA:
- Silo B source repository, reference, and commit SHA:
- Python and Flower versions:

## Data and governance

- Silo A dataset identifier, version, owner, and approved location:
- Silo B dataset identifier, version, owner, and approved location:
- Data permissions and applicable governance/ethics conditions:
- Security and transport settings:

## Experiment configuration

- Server command:
- Silo A client command:
- Silo B client command:
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
- Silo A log location:
- Silo B log location:

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
  3) Inspect all detected Silo application workspaces
  4) Show workshop readiness checklist
  5) Show experiment record template
  0) Exit
EOF
    read -r -p "Selection: " choice

    case "${choice}" in
      1) run_preflight ;;
      2) show_revisions_and_server_entrypoint ;;
      3) inspect_all_silo_sources ;;
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
    inspect-silos)
      inspect_all_silo_sources
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

main "$@"
