#!/usr/bin/env bash
# Workshop-owned Cloud Computing SOA runtime reset boundary.
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: reset-workshop.sh --runtime-only --module module1|module2|module3|module4|module5' \
    'Module 3 accepts --confirm-no-external-module3-runtime only after operator review.' \
    'Without that confirmation, Modules 3/4 refuse external cleanup.' \
    'Participant server/home cleanup and neutral reconciliation remain global.' \
    'Full workshop reset is not verified by this script.'
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi

if [[ $# -ne 3 && $# -ne 4 ]]; then
  usage >&2
  exit 2
fi
[[ "$1" == --runtime-only && "$2" == --module ]] || {
  usage >&2
  exit 2
}

# This is operator attestation, not automated external-resource discovery.
CONFIRMED_NO_EXTERNAL_RUNTIME=false
if [[ $# -eq 4 ]]; then
  [[ "$3" == module3 &&
     "$4" == --confirm-no-external-module3-runtime ]] || {
    usage >&2
    exit 2
  }
  CONFIRMED_NO_EXTERNAL_RUNTIME=true
fi

case "$3" in
  module1|module2)
    printf '%s\n' \
      "Cloud runtime reset boundary: module=$3." \
      'No additional external runtime teardown is implemented.'
    ;;
  module3)
    if [[ "$CONFIRMED_NO_EXTERNAL_RUNTIME" != true ]]; then
      printf '%s\n' \
        'ERROR: Module 3 Docker/Kubernetes/NFS cleanup is not implemented.' \
        'Target resources and ownership must be established first.' >&2
      exit 3
    fi
    printf '%s\n' \
      'Cloud runtime reset boundary: module=module3, teaching-file-only cycle.' \
      'Operator confirmed no external Module 3 exercise resources were created.' \
      'No Docker, Compose, Kubernetes or NFS resources are inspected or removed.' \
      'External-resource absence is operator-attested, not automatically verified.'
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    endpoint_path_args=()
    if [[ -n "${CLOUD_MODULE3_ENDPOINTS_PATH:-}" ]]; then
      endpoint_path_args=(--path "$CLOUD_MODULE3_ENDPOINTS_PATH")
    fi
    endpoints_file="$(python3 "$script_dir/module3_endpoints.py" \
      ${endpoint_path_args[@]+"${endpoint_path_args[@]}"} path)" || {
      printf '%s\n' 'ERROR: Could not resolve the Module 3 endpoint file path.' >&2
      exit 3
    }
    [[ -n "$endpoints_file" ]] || {
      printf '%s\n' 'ERROR: Module 3 endpoint file path is empty.' >&2
      exit 3
    }
    rm -f -- "$endpoints_file" || {
      printf 'ERROR: Could not remove Module 3 endpoint file: %s\n' "$endpoints_file" >&2
      exit 3
    }
    printf 'Module 3 endpoint file cleanup done (removed if present): %s\n' \
      "$endpoints_file"
    ;;
  module4)
    printf '%s\n' \
      'ERROR: Module 4 OpenStack cleanup is not implemented.' \
      'Target resources and ownership must be established first.' >&2
    exit 3
    ;;
  module5)
    printf '%s\n' \
      'Cloud runtime reset boundary: module=module5, offline rehearsal only.' \
      'Inspected organiser rehearsal installs no OpenFaaS runtime.' \
      'Any live external deployment requires separate verified cleanup.'
    ;;
  *)
    printf 'ERROR: Unsupported Cloud module: %s\n' "$3" >&2
    exit 2
    ;;
esac

printf '%s\n' \
  'Global reset must clean participant homes and disable active integration.' \
  'Published teaching assets are preserved.' \
  'Full workshop cleanup is NOT verified.'
