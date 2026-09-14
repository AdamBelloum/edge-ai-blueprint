#!/usr/bin/env bash
# Read-only health and readiness checks for the DIGITAfrica workshop deployment.
#
# Usage:
#   ./scripts/admin/health-check.sh
#   ./scripts/admin/health-check.sh all
#   ./scripts/admin/health-check.sh infrastructure
#   ./scripts/admin/health-check.sh jupyterhub
#   ./scripts/admin/health-check.sh silos

set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"

usage() {
  cat <<'EOF'
Usage: scripts/admin/health-check.sh [SCOPE]

Scopes:
  all             Run infrastructure, JupyterHub, and Silo workspace checks.
  infrastructure  Check k3s nodes, namespace deployments, pods, and events.
  jupyterhub      Check the JupyterHub Helm release and ingress objects.
  silos           Check every numbered Silo rollout and mounted runtime assets.
  help            Show this help text.

The checks are read-only. A non-zero exit code means one or more required
health conditions were not met. A successful static JupyterHub check does not
replace a real login and user-server spawn test.
EOF
}

check_infrastructure() {
  local remote_script

  print_heading "Tier-1 infrastructure health"

  remote_script="$(cat <<'REMOTE_SCRIPT'
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

printf '%s\n' '===== Nodes ====='
k3s kubectl get nodes -o wide

if ! k3s kubectl get nodes --no-headers | awk '$2 ~ /^Ready/ { next } { exit 1 }'; then
  echo 'ERROR: one or more Kubernetes nodes are not Ready.' >&2
  exit 1
fi

printf '%s\n' '===== Deployments ====='
k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get deployments -o wide

if ! k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get deployments -o name \
  | xargs -r -n 1 k3s kubectl -n __DIGITAFRICA_NAMESPACE__ rollout status --timeout=60s; then
  echo 'ERROR: one or more deployments did not complete their rollout.' >&2
  exit 1
fi

printf '%s\n' '===== Pods ====='
k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get pods -o wide

if ! k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get pods --no-headers \
  | awk '$3 ~ /^(Running|Completed)$/ { next } { exit 1 }'; then
  echo 'ERROR: one or more pods are not Running or Completed.' >&2
  exit 1
fi

printf '%s\n' '===== Recent warning events ====='
k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get events \
  --field-selector type=Warning \
  --sort-by=.lastTimestamp || true

echo 'Infrastructure health check passed.'
REMOTE_SCRIPT
)"

  remote_script="${remote_script//__DIGITAFRICA_NAMESPACE__/${DIGITAFRICA_NAMESPACE}}"
  run_tier1_remote "${remote_script}"
}

check_jupyterhub() {
  print_heading "JupyterHub release and ingress health"

  run_tier1_remote "$(cat <<EOF
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

printf '%s\\n' '===== Helm release ====='
helm -n ${DIGITAFRICA_NAMESPACE} status jhub

printf '%s\\n' '===== JupyterHub-related resources ====='
k3s kubectl -n ${DIGITAFRICA_NAMESPACE} get deploy,svc,ingress -o wide

printf '%s\\n' '===== Ingress details ====='
k3s kubectl -n ${DIGITAFRICA_NAMESPACE} describe ingress || true

echo 'JupyterHub static health check passed.'
echo 'NOTE: Perform a browser login and user-server spawn test separately.'
EOF
)"
}

check_silos() {
  local remote_script

  print_heading "Federated-learning Silo runtime readiness"

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
  silo_id="${deployment#fl-client-silo-}"

  printf '===== %s: rollout =====\n' "${deployment}"
  k3s kubectl -n __DIGITAFRICA_NAMESPACE__ rollout status \
    "deployment/${deployment}" --timeout=60s

  pod="$(k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get pods \
    -l "app=fl-client-silo,digitafrica.org/silo-id=${silo_id}" \
    -o jsonpath='{.items[0].metadata.name}')"
  group_id="$(k3s kubectl -n __DIGITAFRICA_NAMESPACE__ get pods \
    -l "app=fl-client-silo,digitafrica.org/silo-id=${silo_id}" \
    -o jsonpath='{.items[0].metadata.labels.digitafrica\.org/group-id}')"

  if [ -z "${pod}" ] || [[ ! "${group_id}" =~ ^group_[0-9]{2}$ ]]; then
    echo "ERROR: ${deployment} has no pod or valid group_NN label." >&2
    exit 1
  fi

  printf '===== %s: mounted runtime assets =====\n' "${deployment}"
  k3s kubectl -n __DIGITAFRICA_NAMESPACE__ exec "${pod}" -- \
    env EXPECTED_GROUP_ID="${group_id}" python3 -c '
import csv
import hashlib
import json
import os
from pathlib import Path

root = Path("/workspace")
group_id = os.environ["EXPECTED_GROUP_ID"]
client = root / "app" / "client" / "client.py"
requirements = root / "app" / "requirements.lock"
manifest_path = root / "data" / "partition-manifest.json"
partition_path = root / "data" / "train.csv"

for required in (client, requirements, manifest_path, partition_path):
    if not required.is_file():
        raise SystemExit(f"missing mounted runtime asset: {required}")

with manifest_path.open(encoding="utf-8") as handle:
    manifest = json.load(handle)

entry = manifest.get("partitions", {}).get(group_id)
if manifest.get("group_id_format") != "group_{NN}":
    raise SystemExit("manifest group_id_format is not group_{NN}")
if not entry:
    raise SystemExit(f"manifest has no partition entry for {group_id}")
if not isinstance(manifest.get("source_sha256"), str) or len(manifest["source_sha256"]) != 64:
    raise SystemExit("manifest lacks a valid source_sha256 reference")

digest = hashlib.sha256(partition_path.read_bytes()).hexdigest()
if digest != entry.get("sha256"):
    raise SystemExit("partition checksum differs from manifest")

with partition_path.open(newline="", encoding="utf-8") as handle:
    rows = sum(1 for _ in csv.reader(handle)) - 1
expected_rows = entry.get("rows")
if rows != expected_rows:
    raise SystemExit(
        "partition row count {} differs from manifest {}".format(rows, expected_rows)
    )

for line in requirements.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "==" not in line:
        raise SystemExit(f"unlocked requirement: {line}")

print(f"group_id={group_id}")
print(f"partition_rows={rows}")
print(f"partition_sha256={digest}")
print("mounted_runtime_integrity=PASSED")
'
done

echo 'Silo runtime health check passed.'
REMOTE_SCRIPT
)"

  remote_script="${remote_script//__DIGITAFRICA_NAMESPACE__/${DIGITAFRICA_NAMESPACE}}"
  run_tier1_remote "${remote_script}"
}
run_scope() {
  local scope="$1"

  case "${scope}" in
    all)
      check_infrastructure
      check_jupyterhub
      check_silos
      ;;
    infrastructure)
      check_infrastructure
      ;;
    jupyterhub)
      check_jupyterhub
      ;;
    silos)
      check_silos
      ;;
    *)
      usage >&2
      die "Unknown health-check scope: ${scope}"
      ;;
  esac
}

main() {
  local scope="${1:-all}"

  case "${scope}" in
    help|--help|-h)
      usage
      ;;
    all|infrastructure|jupyterhub|silos)
      show_context
      run_scope "${scope}"
      print_heading "Health-check result"
      log "All requested checks passed."
      ;;
    *)
      usage >&2
      die "Unknown option: ${scope}"
      ;;
  esac
}

main "$@"
