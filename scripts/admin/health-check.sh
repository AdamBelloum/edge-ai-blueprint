#!/usr/bin/env bash
# Read-only health and readiness checks for the DIGITAfrica workshop deployment.
#
# Usage:
#   ./scripts/admin/health-check.sh
#   ./scripts/admin/health-check.sh deployment
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
  deployment      Run infrastructure and JupyterHub deployment checks (default).
                  This scope does not require workshop Silo resources.
  all             Run deployment checks and explicit participant worker-runtime checks.
  infrastructure  Check k3s nodes, namespace deployments, pods, and events.
  jupyterhub      Check the JupyterHub Helm release, ingress, and public login path.
  silos           Check every inventory-derived participant worker runtime.
  help            Show this help text.

The checks are read-only. A non-zero exit code means one or more required
health conditions were not met. The OIDC check validates the redirect path,
not an interactive credentialed login or user-server spawn.
EOF
}

load_jupyterhub_health_configuration() {
  JUPYTERHUB_PUBLIC_URL="$(deployment_public_setting jupyterhub_public_url)"
  DEPLOYMENT_TLS_MODE="$(deployment_public_setting tls_mode)"
  OIDC_ENABLED="$(deployment_public_setting oidc_enabled)"

  if [[ "${OIDC_ENABLED}" == "true" ]]; then
    OIDC_ISSUER_URL="$(deployment_public_setting oidc_issuer_url)"
  else
    OIDC_ISSUER_URL=""
  fi
}

check_jupyterhub_public_endpoint() {
  local curl_args=() curl_result http_status effective_url

  load_jupyterhub_health_configuration
  require_command curl

  print_heading "JupyterHub public endpoint health"

  curl_args=(
    --silent
    --show-error
    --location
    --max-redirs 10
    --output /dev/null
    --write-out '%{http_code} %{url_effective}'
  )
  case "${DEPLOYMENT_TLS_MODE}" in
    letsencrypt)
      ;;
    selfsigned|none)
      # These modes can use a certificate that is not trusted by this host.
      # The endpoint remains reachable, but this check does not validate trust.
      curl_args+=(--insecure)
      ;;
    *)
      die "Unsupported TLS mode in deployment configuration: ${DEPLOYMENT_TLS_MODE}"
      ;;
  esac

  if ! curl_result="$(curl "${curl_args[@]}" "${JUPYTERHUB_PUBLIC_URL%/}/hub/login")"; then
    die "Could not reach the configured JupyterHub login endpoint."
  fi

  http_status="${curl_result%% *}"
  effective_url="${curl_result#* }"
  [[ "${http_status}" =~ ^2 ]] ||
    die "JupyterHub login path returned unexpected HTTP status ${http_status}."

  if [[ "${OIDC_ENABLED}" == "true" ]]; then
    case "${effective_url}" in
      "${OIDC_ISSUER_URL%/}"/*)
        log "JupyterHub login redirects to the configured OIDC issuer."
        ;;
      *)
        die "JupyterHub login did not redirect to the configured OIDC issuer."
        ;;
    esac
  else
    log "OIDC is disabled; verified the configured JupyterHub login endpoint."
  fi
}

check_infrastructure() {
  local remote_script

  print_heading "Infrastructure health: ${DIGITAFRICA_DEPLOYMENT_GROUP}"

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
  run_deployment_remote "${remote_script}"
}

check_jupyterhub() {
  print_heading "JupyterHub release and ingress health"

  run_deployment_remote "$(cat <<EOF
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

printf '%s\\n' '===== Helm release ====='
helm -n ${DIGITAFRICA_NAMESPACE} status jhub

printf '%s\\n' '===== JupyterHub-related resources ====='
k3s kubectl -n ${DIGITAFRICA_NAMESPACE} get deploy,svc,ingress -o wide

printf '%s\\n' '===== Ingress details ====='
k3s kubectl -n ${DIGITAFRICA_NAMESPACE} describe ingress || true

echo 'JupyterHub static health check passed.'
EOF
)"

  check_jupyterhub_public_endpoint
}

check_silos() {
  local worker_group
  local runtime_root
  local topology_output
  local worker
  local group_id
  local index
  local expected_group_q
  local runtime_root_q
  local -a workers

  print_heading "Federated-learning participant worker runtime readiness"

  worker_group="$(deployment_worker_group)"
  runtime_root="${WORKSHOP_RUNTIME_ROOT:-/opt/digitafrica/fl-workshop}"

  [[ "${runtime_root}" == /* ]] ||
    die "WORKSHOP_RUNTIME_ROOT must be an absolute path: ${runtime_root@Q}"

  require_command ansible-inventory

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
' "${worker_group}"
  )"; then
    die "Could not resolve ordered workers from inventory group: ${worker_group}"
  fi

  mapfile -t workers < <(printf '%s\n' "${topology_output}" | sed '/^$/d')
  ((${#workers[@]} > 0)) ||
    die "Inventory worker group ${worker_group} has no workers."

  for index in "${!workers[@]}"; do
    worker="${workers[$index]}"
    group_id="$(printf 'group_%02d' "$((index + 1))")"

    [[ "${worker}" =~ ^[A-Za-z0-9_.-]+$ ]] ||
      die "Unsafe worker name from inventory: ${worker@Q}"

    printf '\n===== %s / %s: worker runtime =====\n' "${group_id}" "${worker}"

    printf -v expected_group_q '%q' "${group_id}"
    printf -v runtime_root_q '%q' "${runtime_root}"

    run_inventory_target_remote "${worker}" "$(cat <<REMOTE_SCRIPT
set -euo pipefail

env \
  EXPECTED_GROUP_ID=${expected_group_q} \
  WORKSHOP_RUNTIME_ROOT=${runtime_root_q} \
  python3 - <<'PYTHON'
import csv
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ["WORKSHOP_RUNTIME_ROOT"])
group_id = os.environ["EXPECTED_GROUP_ID"]

client = root / "app" / "client" / "client.py"
requirements = root / "app" / "requirements.lock"
manifest_path = root / "data" / "partition-manifest.json"
partition_path = root / "data" / "train.csv"

for required in (client, requirements, manifest_path, partition_path):
    if not required.is_file():
        raise SystemExit(f"missing worker runtime asset: {required}")

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
        f"partition row count {rows} differs from manifest {expected_rows}"
    )

for line in requirements.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "==" not in line:
        raise SystemExit(f"unlocked requirement: {line}")

print(f"runtime_root={root}")
print(f"group_id={group_id}")
print(f"client_sha256={hashlib.sha256(client.read_bytes()).hexdigest()}")
print(f"partition_rows={rows}")
print(f"partition_sha256={digest}")
print("worker_runtime_integrity=PASSED")
PYTHON
REMOTE_SCRIPT
)"
  done

  log "Participant worker runtime health check passed."
}

run_scope() {
  local scope="$1"

  case "${scope}" in
    deployment)
      check_infrastructure
      check_jupyterhub
      ;;
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
  local scope="${1:-deployment}"

  case "${scope}" in
    help|--help|-h)
      usage
      ;;
    deployment|all|infrastructure|jupyterhub|silos)
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
