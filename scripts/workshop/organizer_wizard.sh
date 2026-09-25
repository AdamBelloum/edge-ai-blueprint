#!/usr/bin/env bash
# Federated Learning Workshop Organizer Readiness Wizard v5.4.0
#
# Design:
# - MIN_CLIENTS is a fixed policy minimum (normally 2).
# - Silo/group topology is discovered dynamically from Kubernetes labels.
# - Downloaded source data and prepared partitions are runtime preparation artefacts,
#   not Git-release artefacts.
# - Each active Silo must expose a manifest-backed partition with an integrity check.
# - After a GO verdict, an interactive organiser may start the real Flower server.

set -euo pipefail

WIZARD_VERSION="5.4.0"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
WORKSHOP_CONTEXT="$SCRIPT_DIR/workshop-context.sh"
HELPER="$SCRIPT_DIR/fl-workshop.sh"
COMMON="$REPOSITORY_ROOT/scripts/lib/common.sh"

PASSED=0
WARNINGS=0
FAILURES=0
FAILURE_MESSAGES=()
WARNING_MESSAGES=()

pass() { printf 'PASS  %s\n' "$1"; PASSED=$((PASSED + 1)); }
wizard_warn() { printf 'WARN  %s\n' "$1"; WARNINGS=$((WARNINGS + 1)); WARNING_MESSAGES+=("$1"); }
fail() { printf 'FAIL  %s\n' "$1"; FAILURES=$((FAILURES + 1)); FAILURE_MESSAGES+=("$1"); }
heading() { printf '\n============================================================\n%s\n============================================================\n' "$1"; }
usage() {
  cat <<EOF
Usage: $(basename "$0") [--non-interactive] [--version]

Validates participant-driven federated-learning workshop platform readiness.

Options:
  --non-interactive  Never offer to start the organiser-controlled Flower server.
  --version          Print the Wizard version and exit.

In interactive mode, a GO verdict offers to start the organiser-controlled
Flower server. --non-interactive never starts the real server.

Detailed remote diagnostics are saved to a timestamped local log file.
EOF
}

NON_INTERACTIVE=false

while (($#)); do
  case "$1" in
    --non-interactive)
      NON_INTERACTIVE=true
      shift
      ;;
    --version)
      printf '%s\n' "$WIZARD_VERSION"
      exit 0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -r "$WORKSHOP_CONTEXT" ]] || {
  printf 'Missing workshop context helper: %s\n' "$WORKSHOP_CONTEXT" >&2
  exit 2
}
# shellcheck source=workshop-context.sh
source "$WORKSHOP_CONTEXT"
if ! load_workshop_context; then
  exit 2
fi

LOG_FILE="${TMPDIR:-/tmp}/edge-ai-workshop-wizard-$(date +%Y%m%dT%H%M%S).log"
if ! : >"$LOG_FILE"; then
  printf 'Cannot create wizard diagnostic log: %s\n' "$LOG_FILE" >&2
  exit 1
fi

heading "Federated Learning Workshop Organizer Readiness Wizard v$WIZARD_VERSION"
printf 'Detailed diagnostics: %s\n' "$LOG_FILE"

heading "Wizard v$WIZARD_VERSION — Step 1/6 — Validate organizer environment and release record"
if [[ -x "$HELPER" ]]; then pass "Workshop helper found: $HELPER"; else fail "Workshop helper is missing or not executable: $HELPER"; fi
if [[ -r "$COMMON" ]]; then
  # shellcheck source=/dev/null
  source "$COMMON"
  if declare -F run_deployment_remote >/dev/null &&
     declare -F run_inventory_target_remote >/dev/null &&
     declare -F deployment_worker_group >/dev/null; then
    pass "Selected deployment and worker remote helpers are available."
  else
    fail "Selected deployment remote helpers are incomplete in $COMMON."
  fi
else
  fail "Common helper is not readable: $COMMON"
fi
pass "Loaded active workshop topology from release record: $WORKSHOP_RELEASE_RECORD"

WORKSHOP_RUNTIME_ROOT_FROM_RELEASE="${WORKSHOP_RUNTIME_ROOT:-}"
WORKSHOP_RUNTIME_ROOT="${WORKSHOP_RUNTIME_ROOT:-/opt/digitafrica/fl-workshop}"
if [[ -z "$WORKSHOP_RUNTIME_ROOT_FROM_RELEASE" ]]; then
  wizard_warn "Release record has no WORKSHOP_RUNTIME_ROOT; using compatibility default $WORKSHOP_RUNTIME_ROOT. Add the field in the next release-record migration."
fi

DATASET_CITATION_URL="${DATASET_CITATION_URL:-}"
EDGE_AI_BLUEPRINT_REF="${EDGE_AI_BLUEPRINT_REF:-}"
RUNTIME_REQUIREMENTS_SHA256="${RUNTIME_REQUIREMENTS_SHA256:-}"
PARTITION_MANIFEST_SHA256="${PARTITION_MANIFEST_SHA256:-}"
EXPERIMENT_MODE="${EXPERIMENT_MODE:-}"
MIN_CLIENTS="${MIN_CLIENTS:-2}"
FLOWER_SERVER_ADDRESS="${FLOWER_SERVER_ADDRESS:-}"
FLOWER_SERVER_HOST="${FLOWER_SERVER_HOST:-${SERVER_HOST:-}}"
FLOWER_SERVER_PORT="${FLOWER_SERVER_PORT:-${SERVER_PORT:-8080}}"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-/workspace}"
FLOWER_RUNTIME_ROOT="${FLOWER_RUNTIME_ROOT:-/home/adam/fl-workshop}"
FLOWER_RUNTIME_PYTHON="${FLOWER_RUNTIME_PYTHON:-/home/adam/.venvs/fl-workshop/bin/python}"
FLOWER_SERVER_ENTRYPOINT="${FLOWER_SERVER_ENTRYPOINT:-${FLOWER_RUNTIME_ROOT}/app/server/server.py}"
READINESS_UNIT="fl-workshop-readiness-probe"
READINESS_PROBE_STARTED=false

if [[ -n "$FLOWER_SERVER_ADDRESS" ]]; then
  if [[ "$FLOWER_SERVER_ADDRESS" =~ ^([A-Za-z0-9.-]+):([1-9][0-9]{0,4})$ ]]; then
    FLOWER_SERVER_HOST="${BASH_REMATCH[1]}"
    FLOWER_SERVER_PORT="${BASH_REMATCH[2]}"
  else
    fail "FLOWER_SERVER_ADDRESS must have the form host:port; found: ${FLOWER_SERVER_ADDRESS@Q}."
  fi
fi

is_sha256() {
  [[ "$1" =~ ^[0-9a-f]{64}$ ]]
}

[[ -n "$DATASET_CITATION_URL" ]] || fail "Release record field DATASET_CITATION_URL is not completed."
[[ "$EDGE_AI_BLUEPRINT_REF" =~ ^[0-9a-f]{40,64}$ ]] || fail "EDGE_AI_BLUEPRINT_REF must be a committed Git SHA."
is_sha256 "$RUNTIME_REQUIREMENTS_SHA256" || fail "RUNTIME_REQUIREMENTS_SHA256 must be a lowercase SHA-256 digest."
is_sha256 "$PARTITION_MANIFEST_SHA256" || fail "PARTITION_MANIFEST_SHA256 must be a lowercase SHA-256 digest."
[[ "$EXPERIMENT_MODE" == "workflow_demo" || "$EXPERIMENT_MODE" == "validated_model" ]] || fail "EXPERIMENT_MODE must be workflow_demo or validated_model."
[[ "$MIN_CLIENTS" =~ ^[2-9][0-9]*$ ]] || fail "MIN_CLIENTS must be an integer of at least 2; found: ${MIN_CLIENTS@Q}."
[[ "$FLOWER_SERVER_HOST" =~ ^[A-Za-z0-9.-]+$ ]] || fail "FLOWER_SERVER_HOST (or SERVER_HOST) is missing or invalid."
[[ "$FLOWER_SERVER_PORT" =~ ^[1-9][0-9]{0,4}$ ]] && ((FLOWER_SERVER_PORT <= 65535)) || fail "FLOWER_SERVER_PORT (or SERVER_PORT) is invalid."

append_remote_log() {
  local outcome="$1"
  local description="$2"
  local output="$3"

  {
    printf '\n===== %s — %s =====\n' "$outcome" "$description"
    printf '%s\n' "$output"
  } >>"$LOG_FILE"
}

remote() {
  local description="$1"
  local script="$2"
  local output

  if output="$(run_deployment_remote "$script" 2>&1)"; then
    append_remote_log "REMOTE SUCCESS" "$description" "$output"
    printf '%s\n' "$output"
    return 0
  fi

  append_remote_log "REMOTE FAILURE" "$description" "$output"
  printf '%s\n' "$output"
  return 1
}

worker_remote() {
  local worker="$1"
  local description="$2"
  local script="$3"
  local output

  if output="$(run_inventory_target_remote "$worker" "$script" 2>&1)"; then
    append_remote_log "REMOTE SUCCESS" "$description" "$output"
    printf '%s\n' "$output"
    return 0
  fi

  append_remote_log "REMOTE FAILURE" "$description" "$output"
  printf '%s\n' "$output"
  return 1
}

stop_readiness_probe() {
  local stop_script

  [[ "$READINESS_PROBE_STARTED" == true ]] || return 0

  stop_script=$(cat <<REMOTE
set -euo pipefail
systemctl stop "${READINESS_UNIT}.service" || true
systemctl reset-failed "${READINESS_UNIT}.service" || true
REMOTE
)

  if remote "Stop temporary Flower readiness probe" "$stop_script" >/dev/null; then
    READINESS_PROBE_STARTED=false
    return 0
  fi
  return 1
}

# Never leave a probe process behind if the wizard is interrupted or fails.
trap 'stop_readiness_probe >/dev/null 2>&1 || true' EXIT

start_workshop_server() {
  local start_script start_result

  start_script=$(cat <<REMOTE
set -euo pipefail

systemctl start fl-workshop-server.service

for _ in {1..10}; do
  if systemctl is-active --quiet fl-workshop-server.service && \
     ss -ltnH | awk '{print \$4}' | grep -Eq '(^|:)$FLOWER_SERVER_PORT$'; then
    echo "Flower server is active and listening on port $FLOWER_SERVER_PORT."
    journalctl --no-pager -u fl-workshop-server.service -n 30
    exit 0
  fi
  sleep 1
done

echo "Flower server did not become active and listen on port $FLOWER_SERVER_PORT." >&2
systemctl --no-pager --full status fl-workshop-server.service >&2 || true
journalctl --no-pager -u fl-workshop-server.service -n 50 >&2 || true
exit 1
REMOTE
)

  if start_result="$(remote "Start organiser-controlled Flower server" "$start_script")"; then
    printf 'WORKSHOP SERVER STARTED — it is now waiting for the authorised Silo clients.\n'
    printf 'Server diagnostics: %s\n' "$LOG_FILE"
    return 0
  fi

  printf 'ERROR: The Flower server could not be started; do not ask students to start clients.\n' >&2
  printf 'See diagnostic log: %s\n' "$LOG_FILE" >&2
  return 1
}

if declare -F run_deployment_remote >/dev/null &&
   declare -F run_inventory_target_remote >/dev/null &&
   declare -F deployment_worker_group >/dev/null &&
   ((FAILURES == 0)); then
  heading "Wizard v$WIZARD_VERSION — Step 2/6 — Resolve participant group topology"
  WORKERS=()
  GROUP_IDS=()
  WORKER_GROUP="$(deployment_worker_group)"

  printf 'Workshop inventory     : %s\n' "${DIGITAFRICA_INVENTORY}"
  printf 'Control-plane group    : %s\n' "${DIGITAFRICA_DEPLOYMENT_GROUP}"
  printf 'Worker group           : %s\n' "$WORKER_GROUP"
  printf 'Namespace              : %s\n' "${DIGITAFRICA_NAMESPACE}"

  if ! command -v ansible-inventory >/dev/null 2>&1; then
    fail "Required command not found: ansible-inventory"
  else
    topology_output=""
    if topology_output="$(
      ansible-inventory -i "${DIGITAFRICA_INVENTORY}" --list |
        python3 -c '
import json
import sys

inventory = json.load(sys.stdin)
group_name = sys.argv[1]
group = inventory.get(group_name)

if not isinstance(group, dict):
    raise SystemExit("inventory worker group is missing: " + group_name)

hosts = group.get("hosts")
if not isinstance(hosts, list):
    raise SystemExit("inventory worker group has no ordered hosts list: " + group_name)

for host in hosts:
    if not isinstance(host, str) or not host:
        raise SystemExit("inventory worker group contains an invalid host name")
    print(host)
' "$WORKER_GROUP"
    )"; then
      append_remote_log "LOCAL SUCCESS" "Resolve ordered participant workers from ${WORKER_GROUP}" "$topology_output"
      mapfile -t WORKERS < <(printf '%s\n' "$topology_output" | sed '/^$/d')

      topology_safe=true
      for worker in "${WORKERS[@]}"; do
        if [[ ! "$worker" =~ ^[A-Za-z0-9_.-]+$ ]]; then
          fail "Unsafe worker inventory name derived from $WORKER_GROUP: ${worker@Q}"
          topology_safe=false
        fi
      done

      if "$topology_safe" && ((${#WORKERS[@]} >= MIN_CLIENTS)); then
        for index in "${!WORKERS[@]}"; do
          group_id="$(printf 'group_%02d' "$((index + 1))")"
          GROUP_IDS+=("$group_id")
          printf '      %s → %s\n' "$group_id" "${WORKERS[$index]}"
        done
        pass "Resolved ${#WORKERS[@]} participant groups from ordered inventory group $WORKER_GROUP; MIN_CLIENTS=$MIN_CLIENTS."
      elif "$topology_safe"; then
        fail "Inventory worker group $WORKER_GROUP has ${#WORKERS[@]} workers; MIN_CLIENTS=$MIN_CLIENTS requires at least $MIN_CLIENTS."
      fi
    else
      append_remote_log "LOCAL FAILURE" "Resolve ordered participant workers from ${WORKER_GROUP}" "$topology_output"
      fail "Could not resolve ordered workers from inventory group $WORKER_GROUP."
    fi
  fi

  heading "Wizard v$WIZARD_VERSION — Step 3/6 — Verify prepared participant partitions on assigned workers"
  if ((${#WORKERS[@]} == 0 || ${#GROUP_IDS[@]} != ${#WORKERS[@]})); then
    fail "No usable participant group topology is available for partition validation."
  else
    preparation_ok=true
    for index in "${!WORKERS[@]}"; do
      worker="${WORKERS[$index]}"
      group_id="${GROUP_IDS[$index]}"

      if [[ ! "$group_id" =~ ^group_[0-9]{2,}$ ]]; then
        fail "Unsafe participant group identifier derived for worker $worker: ${group_id@Q}"
        preparation_ok=false
        continue
      fi

      check_script=$(cat <<REMOTE
set -euo pipefail

export GROUP_ID="$group_id"
export EXPECTED_WORKER_COUNT="${#WORKERS[@]}"
export EXPECTED_REQUIREMENTS_SHA256="$RUNTIME_REQUIREMENTS_SHA256"
export EXPECTED_MANIFEST_SHA256="$PARTITION_MANIFEST_SHA256"
export WORKSHOP_RUNTIME_ROOT="$WORKSHOP_RUNTIME_ROOT"
python3 - <<'PYTHON_CHECK'
import csv
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["WORKSHOP_RUNTIME_ROOT"])
group = os.environ["GROUP_ID"]
expected_worker_count = int(os.environ["EXPECTED_WORKER_COUNT"])
expected_requirements_sha = os.environ["EXPECTED_REQUIREMENTS_SHA256"]
expected_manifest_sha = os.environ["EXPECTED_MANIFEST_SHA256"]

requirements_path = root / "app" / "requirements.lock"
manifest_path = root / "data" / "partition-manifest.json"
partition_path = root / "data" / "train.csv"

def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()

for required in (requirements_path, manifest_path, partition_path):
    if not required.is_file():
        raise SystemExit("missing workshop runtime asset: " + str(required))

requirements_sha = digest(requirements_path)
manifest_sha = digest(manifest_path)
partition_sha = digest(partition_path)

if requirements_sha != expected_requirements_sha:
    raise SystemExit("requirements checksum differs from release record")
if manifest_sha != expected_manifest_sha:
    raise SystemExit("manifest checksum differs from release record")

with manifest_path.open(encoding="utf-8") as handle:
    manifest = json.load(handle)

entry = manifest.get("partitions", {}).get(group)
if manifest.get("group_id_format") != "group_{NN}":
    raise SystemExit("manifest group_id_format is not group_{NN}")
if manifest.get("groups") != expected_worker_count:
    raise SystemExit("manifest group count differs from inventory worker count")
if not entry:
    raise SystemExit("manifest has no partition entry for " + group)
if not isinstance(manifest.get("source_sha256"), str) or len(manifest["source_sha256"]) != 64:
    raise SystemExit("manifest lacks a valid source_sha256 reference")
if partition_sha != entry.get("sha256"):
    raise SystemExit("partition checksum differs from manifest")

with partition_path.open(newline="", encoding="utf-8") as handle:
    row_count = sum(1 for _ in csv.reader(handle)) - 1
if row_count != entry.get("rows"):
    raise SystemExit("partition row count differs from manifest")

print("group=" + group)
print("manifest_groups=" + str(manifest.get("groups")))
print("partition_rows=" + str(row_count))
PYTHON_CHECK
REMOTE
)

      if worker_remote "$worker" "Validate prepared partition for $worker / $group_id" "$check_script" >/dev/null; then
        pass "Worker $worker / group $group_id has a manifest-backed, checksum-valid prepared partition."
      else
        fail "Worker $worker / group $group_id lacks a valid prepared partition or manifest."
        preparation_ok=false
      fi
    done

    if "$preparation_ok"; then
      pass "Prepared partition validation completed for every assigned worker."
    fi
  fi

  heading "Wizard v$WIZARD_VERSION — Step 4/6 — Validate rendered participant JupyterHub mapping"
  JUPYTERHUB_VALUES_PATH="/opt/digitafrica/k8s/jhub-values.yaml"
  JUPYTERHUB_WORKSHOP_MOUNT="/home/jovyan/digitafrica/workshop"
  expected_group_nodes_json="{"

  for index in "${!WORKERS[@]}"; do
    if ((index > 0)); then
      expected_group_nodes_json+=","
    fi
    expected_group_nodes_json+="\"${GROUP_IDS[$index]}\":\"${WORKERS[$index]}\""
  done
  expected_group_nodes_json+="}"

  expected_group_nodes_b64="$(printf '%s' "$expected_group_nodes_json" | base64 | tr -d '\n')"

  jupyterhub_mapping_script=$(cat <<REMOTE
set -euo pipefail

export EXPECTED_GROUP_NODES_B64="$expected_group_nodes_b64"
export EXPECTED_WORKSHOP_RUNTIME_ROOT="$WORKSHOP_RUNTIME_ROOT"
export EXPECTED_WORKSHOP_MOUNT="$JUPYTERHUB_WORKSHOP_MOUNT"
export JUPYTERHUB_VALUES_PATH="$JUPYTERHUB_VALUES_PATH"
python3 - <<'PYTHON_CHECK'
import ast
import base64
import json
import os
import re
from pathlib import Path

import yaml

values_path = Path(os.environ["JUPYTERHUB_VALUES_PATH"])
expected_nodes = json.loads(
    base64.b64decode(os.environ["EXPECTED_GROUP_NODES_B64"]).decode("utf-8")
)
expected_runtime_root = os.environ["EXPECTED_WORKSHOP_RUNTIME_ROOT"]
expected_mount = os.environ["EXPECTED_WORKSHOP_MOUNT"]

if not values_path.is_file():
    raise SystemExit("missing rendered JupyterHub values file")

with values_path.open(encoding="utf-8") as handle:
    values = yaml.safe_load(handle) or {}

extra_config = (
    values.get("hub", {})
    .get("extraConfig", {})
    .get("10-digitafrica-group-workspace")
)
if not isinstance(extra_config, str):
    raise SystemExit("missing participant workspace extraConfig")

mapping_match = re.search(
    r"^\\s*WORKSHOP_GROUP_NODES\\s*=\\s*(\\{.*?\\})\\s*$",
    extra_config,
    flags=re.MULTILINE | re.DOTALL,
)
if not mapping_match:
    raise SystemExit("missing WORKSHOP_GROUP_NODES mapping")

try:
    rendered_nodes = ast.literal_eval(mapping_match.group(1))
except (SyntaxError, ValueError) as exc:
    raise SystemExit("WORKSHOP_GROUP_NODES mapping is not a literal dictionary") from exc

if rendered_nodes != expected_nodes:
    raise SystemExit("rendered group-to-worker mapping differs from ordered inventory")

def assigned_string(name):
    match = re.search(
        rf"^\s*{re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]\s*$",
        extra_config,
        flags=re.MULTILINE,
    )
    if not match:
        raise SystemExit("missing " + name + " assignment")
    return match.group(1)

if assigned_string("WORKSHOP_HOST_PATH") != expected_runtime_root:
    raise SystemExit("rendered workshop host path differs from expected runtime root")
if assigned_string("WORKSHOP_MOUNT_PATH") != expected_mount:
    raise SystemExit("rendered workshop mount path differs from expected participant mount")

if 'environment["GROUP_ID"] = group_id' not in extra_config:
    raise SystemExit("rendered participant hook does not set GROUP_ID")
if not re.search(r'["\\']readOnly["\\']\\s*:\\s*True', extra_config):
    raise SystemExit("rendered participant runtime mount is not read-only")

client_data_path = (
    values.get("singleuser", {})
    .get("extraEnv", {})
    .get("CLIENT_DATA_PATH")
)
if client_data_path != expected_mount + "/data/train.csv":
    raise SystemExit("rendered CLIENT_DATA_PATH differs from participant runtime partition path")

print("mapping_groups=" + str(len(rendered_nodes)))
print("runtime_root=" + expected_runtime_root)
print("participant_mount=" + expected_mount)
print("client_data_path=" + client_data_path)
PYTHON_CHECK
REMOTE
)

  if remote "Read-only validate rendered JupyterHub participant mapping" "$jupyterhub_mapping_script" >/dev/null; then
    pass "Rendered JupyterHub mapping assigns every inventory group to its ordered worker with the read-only participant runtime mount."
  else
    fail "Rendered JupyterHub participant mapping is absent, inconsistent with inventory, or lacks required participant runtime settings."
  fi

  heading "Wizard v$WIZARD_VERSION — Step 5/6 — Verify managed Flower runtime and bounded listener"
  runtime_ready=false
  runtime_script=$(cat <<REMOTE
set -euo pipefail
test -x "${FLOWER_RUNTIME_PYTHON}"
test -r "${FLOWER_SERVER_ENTRYPOINT}"
"${FLOWER_RUNTIME_PYTHON}" -c 'import flwr; print(flwr.__version__)'
test -r /etc/systemd/system/fl-workshop-server.service
REMOTE
)
  if runtime_result="$(remote "Verify managed Flower runtime" "$runtime_script")"; then
    pass "Managed Flower runtime, entry point, and organiser-controlled service are installed."
    runtime_ready=true
  else
    fail "Managed Flower runtime, entry point, or organiser-controlled service is unavailable."
  fi

  listener_script=$(cat <<REMOTE
set -euo pipefail
ss -ltnH | awk '{print \$4}' | grep -Eq '(^|:)$FLOWER_SERVER_PORT$'
REMOTE
)

  if "$runtime_ready"; then
    if remote "Check active Flower listener" "$listener_script" >/dev/null; then
      pass "An active Flower listener is present on port $FLOWER_SERVER_PORT."
    else
      readiness_clients="$MIN_CLIENTS"
      readiness_script=$(cat <<REMOTE
set -euo pipefail
if systemctl is-active --quiet fl-workshop-server.service; then
  echo "The organiser-controlled Flower experiment service is active but is not listening on port $FLOWER_SERVER_PORT." >&2
  exit 1
fi

systemctl stop "${READINESS_UNIT}.service" 2>/dev/null || true
systemctl reset-failed "${READINESS_UNIT}.service" 2>/dev/null || true

systemd-run --quiet --collect --unit="${READINESS_UNIT}" \
  --property=Type=simple \
  --property=User=adam \
  --property=Group=adam \
  --property=WorkingDirectory="${FLOWER_RUNTIME_ROOT}/app/server" \
  --setenv=PYTHONUNBUFFERED=1 \
  --setenv=FLOWER_SERVER_HOST=0.0.0.0 \
  --setenv=FLOWER_SERVER_PORT=$FLOWER_SERVER_PORT \
  --setenv=MIN_FIT_CLIENTS=$readiness_clients \
  --setenv=MIN_AVAILABLE_CLIENTS=$readiness_clients \
  --setenv=MIN_EVALUATE_CLIENTS=$readiness_clients \
  --setenv=NUM_ROUNDS=5 \
  "${FLOWER_RUNTIME_PYTHON}" "${FLOWER_SERVER_ENTRYPOINT}"

for _ in {1..10}; do
  if ss -ltnH | awk '{print \$4}' | grep -Eq '(^|:)$FLOWER_SERVER_PORT$'; then
    exit 0
  fi
  sleep 1
done

journalctl --no-pager -u "${READINESS_UNIT}.service" -n 40 >&2 || true
exit 1
REMOTE
)
      READINESS_PROBE_STARTED=true
      if remote "Start bounded Flower readiness probe" "$readiness_script" >/dev/null; then
        pass "A bounded Flower readiness probe is listening on port $FLOWER_SERVER_PORT with MIN_CLIENTS=$readiness_clients."
      else
        stop_readiness_probe || true
        fail "Could not start a bounded Flower readiness probe on port $FLOWER_SERVER_PORT."
      fi
    fi
  fi

  if "$READINESS_PROBE_STARTED"; then
    if stop_readiness_probe; then
      pass "Temporary Flower readiness probe was stopped cleanly."
    else
      fail "Temporary Flower readiness probe could not be stopped cleanly."
    fi
  fi

  heading "Wizard v$WIZARD_VERSION — Step 6/6 — Confirm experiment scope"
  wizard_warn "The organizer must describe this as a workflow demonstration unless the configured client code uses approved feature data and an evaluation protocol has been validated."
else
  heading "Wizard v$WIZARD_VERSION — Remaining checks"
  fail "Remote checks were not run because the Tier-1 helper or release-record validation failed."
fi

heading "Workshop readiness report — Wizard v$WIZARD_VERSION"
printf 'Passed checks:   %d\nWarnings:        %d\nBlocking issues: %d\n' "$PASSED" "$WARNINGS" "$FAILURES"
if ((${#WARNING_MESSAGES[@]})); then
  printf '\nWarnings:\n'
  printf '  - %s\n' "${WARNING_MESSAGES[@]}"
fi
if ((FAILURES)); then
  printf '\nVERDICT: NO-GO — do not start the workshop yet.\nResolve every blocking issue below, then rerun Wizard v%s:\n' "$WIZARD_VERSION"
  printf '  - %s\n' "${FAILURE_MESSAGES[@]}"
  exit 1
fi
printf '\nVERDICT: PLATFORM GO — selected worker topology, staged partitions,\nJupyterHub group mapping, and Flower server readiness checks passed.\n\nRemaining operational gate: each participant group must complete the\nJupyterHub notebook/client smoke test before federated training begins.\n'

if "$NON_INTERACTIVE"; then
  printf 'Non-interactive mode: the organiser-controlled Flower server was not started.\n'
elif [[ ! -t 0 ]]; then
  printf 'No interactive terminal: the organiser-controlled Flower server was not started.\n'
else
  printf 'PLATFORM GO — start the organiser-controlled Flower server now? [y/N]: '
  start_answer=""
  if ! read -r start_answer; then
    start_answer=""
  fi

  case "$start_answer" in
    [yY]|[yY][eE][sS])
      start_workshop_server || exit 1
      ;;
    *)
      printf 'Flower server was not started. Start it later by rerunning the wizard after a PLATFORM GO verdict.\n'
      ;;
  esac
fi

exit 0
