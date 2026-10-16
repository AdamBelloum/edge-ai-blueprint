#!/usr/bin/env bash
# Organiser-controlled runtime asset preparation, separate from publication.
# Never build images, start containers, change Docker enablement, or create accounts.
set -Eeuo pipefail

usage() {
  printf '%s\n' \
    'Usage: prepare-runtime.sh spark-only|livy 1|2 [--syntax-check]' \
    '' \
    'Specify the number of Spark worker containers per selected group VM.' \
    'spark-only: stage the existing Spark-only runtime configuration.' \
    'livy: stage the locked Livy archive and build/configuration assets as well.' \
    '--syntax-check: parse the preparation playbook without executing tasks.' \
    '' \
    'Real preparation may pull the pinned Spark image and download Livy.' \
    'It does not build the Livy image, start services, publish participant assets,' \
    'change authentication, or prove execution readiness.'
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi
if [[ $# -lt 2 || $# -gt 3 ]]; then
  usage >&2
  exit 2
fi

case "$1" in
  spark-only) livy_enabled=false ;;
  livy) livy_enabled=true ;;
  *) printf 'ERROR: mode must be spark-only or livy.\n' >&2; exit 2 ;;
esac
case "$2" in
  1|2) worker_count="$2" ;;
  *) printf 'ERROR: worker count must be 1 or 2.\n' >&2; exit 2 ;;
esac
ansible_options=()
if [[ $# -eq 3 ]]; then
  [[ "$3" == --syntax-check ]] || {
    printf 'ERROR: the only optional argument is --syntax-check.\n' >&2
    exit 2
  }
  ansible_options+=(--syntax-check)
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../lib/workshop-context.sh
source "${SCRIPT_DIR}/../../lib/workshop-context.sh"
load_workshop_context

command -v ansible-playbook >/dev/null 2>&1 || {
  printf 'ERROR: ansible-playbook is required.\n' >&2
  exit 2
}
: "${DIGITAFRICA_INVENTORY:?Inventory missing from context}"
: "${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP:?Worker group missing from context}"
: "${WORKSHOP_CONTEXT_REPOSITORY_ROOT:?Repository root missing from context}"
[[ "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || {
  printf 'ERROR: expected a single inventory worker-group name.\n' >&2
  exit 2
}
playbook="${WORKSHOP_CONTEXT_REPOSITORY_ROOT}/playbooks/prepare-big-data-spark-runtime.yml"
[[ -r "$playbook" ]] || {
  printf 'ERROR: preparation playbook is missing: %s\n' "$playbook" >&2
  exit 2
}

printf -v settings \
  '{"big_data_livy_enabled": %s, "big_data_spark_worker_count": %s}' \
  "$livy_enabled" "$worker_count"
printf 'Spark runtime configuration: mode=%s, workers-per-VM=%s, group=%s\n' \
  "$1" "$worker_count" "$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP"
if [[ ${#ansible_options[@]} -eq 0 ]]; then
  printf '%s\n' 'Preparing runtime assets only; no image build or service startup.'
fi

exec ansible-playbook \
  -i "$DIGITAFRICA_INVENTORY" \
  "$playbook" \
  --extra-vars "big_data_worker_group=${DIGITAFRICA_DEPLOYMENT_WORKER_GROUP}" \
  --extra-vars "$settings" \
  "${ansible_options[@]}"
