#!/usr/bin/env bash
# Workshop-owned Introduction to AI runtime reset boundary.
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: reset-workshop.sh --runtime-only --module module1|module2|module3' \
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
  module1|module2|module3) ;;
  *) printf 'ERROR: Unsupported AI module: %s\n' "$3" >&2; exit 2 ;;
esac

printf '%s\n' \
  "Introduction to AI runtime reset boundary: module=$3." \
  'No additional external runtime teardown is implemented.' \
  'Global reset must stop participant servers and delete participant homes.' \
  'Published teaching assets are preserved.' \
  'Full workshop cleanup is NOT verified.'
