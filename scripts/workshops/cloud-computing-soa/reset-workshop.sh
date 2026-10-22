#!/usr/bin/env bash
# Workshop-owned Cloud Computing SOA runtime reset boundary.
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: reset-workshop.sh --runtime-only --module module1|module2|module3|module4|module5' \
    'Modules 3/4 refuse cleanup until external-resource ownership is implemented.' \
    'Participant server/home cleanup and neutral reconciliation remain global.' \
    'Full workshop reset is not verified by this script.'
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi

if [[ $# -ne 3 ]]; then
  usage >&2
  exit 2
fi
[[ "$1" == --runtime-only && "$2" == --module ]] || {
  usage >&2
  exit 2
}

case "$3" in
  module1|module2)
    printf '%s\n' \
      "Cloud runtime reset boundary: module=$3." \
      'No additional external runtime teardown is implemented.'
    ;;
  module3)
    printf '%s\n' \
      'ERROR: Module 3 Docker/Kubernetes/NFS cleanup is not implemented.' \
      'Target resources and ownership must be established first.' >&2
    exit 3
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
