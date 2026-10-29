#!/usr/bin/env bash
# Scoped removal of organiser-staged Spark participant credential objects.
# Runs on the control plane; the worker-side teardown cannot reach them.
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    'Usage: cleanup-credentials.sh --execute' \
    '' \
    'Delete only Kubernetes Secrets and ConfigMaps labelled' \
    'managed-by=organiser, module=spark and workshop=big-data, then verify absence.' \
    'NetworkPolicies are handled separately by ownership-checked runtime teardown.' \
    'Participant servers must already be stopped.'
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi
if [[ $# -ne 1 || "$1" != --execute ]]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../lib/workshop-context.sh
source "${SCRIPT_DIR}/../../lib/workshop-context.sh"
load_workshop_context

command -v ansible >/dev/null 2>&1 || {
  printf 'ERROR: ansible is required.\n' >&2
  exit 2
}
: "${DIGITAFRICA_INVENTORY:?Inventory missing from context}"
: "${DIGITAFRICA_DEPLOYMENT_GROUP:?Control-plane group missing from context}"

: "${DIGITAFRICA_NAMESPACE:?Namespace missing from context}"
[[ "$DIGITAFRICA_DEPLOYMENT_GROUP" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || {
  printf '%s\n' 'ERROR: expected a single control-plane inventory group name.' >&2
  exit 2
}
namespace="$DIGITAFRICA_NAMESPACE"
[[ ${#namespace} -le 63 && "$namespace" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || {
  printf 'ERROR: invalid Kubernetes namespace: %s\n' "$namespace" >&2
  exit 2
}
selector='digitafrica.eu/managed-by=organiser,digitafrica.eu/module=spark,digitafrica.eu/workshop=big-data'

remote="$(cat <<REMOTE
set -eu
k3s kubectl -n '${namespace}' delete secret,configmap -l '${selector}' --ignore-not-found
left="\$(k3s kubectl -n '${namespace}' get secret,configmap -l '${selector}' -o name)"
if [ -n "\$left" ]; then
  printf 'ERROR: Spark credential objects remain:\n%s\n' "\$left" >&2
  exit 1
fi
echo 'Spark participant credential objects are absent; policy cleanup is checked separately.'
REMOTE
)"

printf 'Spark credential cleanup: namespace=%s, control-plane group=%s\n' \
  "$namespace" "$DIGITAFRICA_DEPLOYMENT_GROUP"

ANSIBLE_STDOUT_CALLBACK=minimal exec ansible \
  -i "$DIGITAFRICA_INVENTORY" "$DIGITAFRICA_DEPLOYMENT_GROUP" \
  -b -m ansible.builtin.shell -a "$remote"
