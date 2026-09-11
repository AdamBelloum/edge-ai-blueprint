#!/usr/bin/env bash
# Federated Learning Workshop Organizer Readiness Wizard v4.0.0
#
# Design:
# - MIN_CLIENTS is a fixed policy minimum (normally 2).
# - Silo/group topology is discovered dynamically from Kubernetes labels.
# - Downloaded source data and prepared partitions are runtime preparation artefacts,
#   not Git-release artefacts.
# - Each active Silo must expose a manifest-backed partition with an integrity check.

set -euo pipefail

WIZARD_VERSION="5.0.0"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
RELEASE_RECORD="$SCRIPT_DIR/workshop-release.env"
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

Validates dynamic federated-learning workshop preparation and runtime readiness.
EOF
}

NON_INTERACTIVE=false
while (($#)); do
  case "$1" in
    --non-interactive) NON_INTERACTIVE=true ;;
    --version) printf '%s\n' "$WIZARD_VERSION"; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

heading "Federated Learning Workshop Organizer Readiness Wizard v$WIZARD_VERSION"

heading "Wizard v$WIZARD_VERSION — Step 1/6 — Validate organizer environment and release record"
if [[ -x "$HELPER" ]]; then pass "Workshop helper found: $HELPER"; else fail "Workshop helper is missing or not executable: $HELPER"; fi
if [[ -r "$COMMON" ]]; then
  # shellcheck source=/dev/null
  source "$COMMON"
  if declare -F run_tier1_remote >/dev/null; then pass "Tier-1 remote helper is available."; else fail "run_tier1_remote is not defined by $COMMON."; fi
else
  fail "Common helper is not readable: $COMMON"
fi
if [[ -r "$RELEASE_RECORD" ]]; then
  # shellcheck source=/dev/null
  source "$RELEASE_RECORD"
  pass "Loaded release record: $RELEASE_RECORD"
else
  fail "Release record is not readable: $RELEASE_RECORD"
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

remote() {
  local description="$1"
  local script="$2"
  local output
  if output="$(run_tier1_remote "$script" 2>&1)"; then
    printf '%s\n' "$output"
    return 0
  fi
  printf '%s\n' "$output"
  return 1
}

if declare -F run_tier1_remote >/dev/null && ((FAILURES == 0)); then
  heading "Wizard v$WIZARD_VERSION — Step 2/6 — Discover active Silo topology"
  discovery_script=$(cat <<'REMOTE'
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
k3s kubectl -n digitafrica get pods -l app=fl-client-silo -o jsonpath='{range .items[*]}{.metadata.name}{"|"}{.metadata.labels.digitafrica\.org/silo-id}{"|"}{.metadata.labels.digitafrica\.org/group-id}{"|"}{.status.phase}{"\n"}{end}'
REMOTE
)
  if discovery="$(remote "Discover Silos" "$discovery_script")"; then
    printf '%s\n' "$discovery"
    mapfile -t SILOS < <(printf '%s\n' "$discovery" | awk -F'|' '/^[^|]+\|[^|]+\|[^|]+\|Running$/ {print}')
    if ((${#SILOS[@]} < MIN_CLIENTS)); then
      fail "Discovered ${#SILOS[@]} running, labelled Silos; MIN_CLIENTS=$MIN_CLIENTS requires at least $MIN_CLIENTS."
    else
      pass "Discovered ${#SILOS[@]} running, labelled Silos; policy minimum is MIN_CLIENTS=$MIN_CLIENTS."
      printf '      Active topology: %s\n' "$(printf '%s; ' "${SILOS[@]}")"
    fi
  else
    fail "Could not discover active Silo pods."
    SILOS=()
  fi

  heading "Wizard v$WIZARD_VERSION — Step 3/6 — Verify dynamically prepared data and manifests"
  if ((${#SILOS[@]} == 0)); then
    fail "No usable Silo topology is available for preparation validation."
  else
    preparation_ok=true
    for record in "${SILOS[@]}"; do
      IFS='|' read -r pod silo_id group_id phase <<<"$record"
      # Values originate in Kubernetes labels and fixed local configuration; reject unsafe values before interpolation.
      if [[ ! "$pod" =~ ^[a-z0-9.-]+$ || ! "$silo_id" =~ ^[0-9]{2}$ || ! "$group_id" =~ ^group_[0-9]{2}$ || "$group_id" != "group_${silo_id}" ]]; then
        fail "Unsafe, incomplete, or inconsistent Silo metadata for record: $record"
        preparation_ok=false
        continue
      fi
      check_script=$(cat <<REMOTE
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
k3s kubectl -n digitafrica exec "$pod" -- env \
  GROUP_ID="$group_id" \
  EXPECTED_SILO_COUNT="${#SILOS[@]}" \
  EXPECTED_REQUIREMENTS_SHA256="$RUNTIME_REQUIREMENTS_SHA256" \
  EXPECTED_MANIFEST_SHA256="$PARTITION_MANIFEST_SHA256" \
  WORKSPACE_ROOT="$WORKSPACE_ROOT" \
  python3 -c '
import csv
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["WORKSPACE_ROOT"])
group = os.environ["GROUP_ID"]
expected_silo_count = int(os.environ["EXPECTED_SILO_COUNT"])
expected_requirements_sha = os.environ["EXPECTED_REQUIREMENTS_SHA256"]
expected_manifest_sha = os.environ["EXPECTED_MANIFEST_SHA256"]

requirements_path = root / "app" / "requirements.lock"
manifest_path = root / "data" / "partition-manifest.json"
partition_path = root / "data" / "train.csv"

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

for required in (requirements_path, manifest_path, partition_path):
    if not required.is_file():
        raise SystemExit("missing mounted runtime asset: " + str(required))

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
if manifest.get("groups") != expected_silo_count:
    raise SystemExit("manifest group count differs from discovered Silo count")
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
print("requirements_sha256=" + requirements_sha)
print("manifest_sha256=" + manifest_sha)
print("partition_sha256=" + partition_sha)
print("partition_rows=" + str(row_count))
'
REMOTE
)
      if result="$(remote "Validate prepared data for $pod" "$check_script")"; then
        printf '%s\n' "$result"
        pass "Silo $silo_id / group $group_id has a manifest-backed, checksum-valid prepared partition."
      else
        fail "Silo $silo_id / group $group_id lacks valid prepared data or a valid partition manifest."
        preparation_ok=false
      fi
    done
    if "$preparation_ok"; then pass "Dynamic preparation validation completed for all discovered Silos."; fi
  fi

  heading "Wizard v$WIZARD_VERSION — Step 4/6 — Confirm Flower server listener"
  listener_script=$(cat <<REMOTE
set -euo pipefail
if command -v ss >/dev/null 2>&1; then
  ss -ltnH | awk '{print \$4}' | grep -Eq '(^|:)$FLOWER_SERVER_PORT$'
else
  python3 -c 'import socket; s=socket.create_connection(("$FLOWER_SERVER_HOST", $FLOWER_SERVER_PORT), 3); s.close()'
fi
REMOTE
)
  if remote "Check Flower listener" "$listener_script" >/dev/null; then
    pass "A TCP listener is present for Flower on port $FLOWER_SERVER_PORT."
  else
    fail "No TCP listener is present for Flower on port $FLOWER_SERVER_PORT."
  fi

  heading "Wizard v$WIZARD_VERSION — Step 5/6 — Test every Silo-to-Flower connection"
  connectivity_ok=true
  for record in "${SILOS[@]}"; do
    IFS='|' read -r pod silo_id group_id phase <<<"$record"
    connection_script=$(cat <<REMOTE
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
k3s kubectl -n digitafrica exec "$pod" -- python3 -c 'import socket; s=socket.create_connection(("$FLOWER_SERVER_HOST", $FLOWER_SERVER_PORT), 5); s.close()'
REMOTE
)
    if remote "Test $pod connection" "$connection_script" >/dev/null; then
      pass "Silo $silo_id / group $group_id can reach $FLOWER_SERVER_HOST:$FLOWER_SERVER_PORT."
    else
      fail "Silo $silo_id / group $group_id cannot reach $FLOWER_SERVER_HOST:$FLOWER_SERVER_PORT."
      connectivity_ok=false
    fi
  done
  "$connectivity_ok" && ((${#SILOS[@]} > 0)) && pass "All discovered Silos can reach the Flower server."

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
printf '\nVERDICT: GO — organizer-controlled dynamic preparation and runtime checks passed.\n'
exit 0
