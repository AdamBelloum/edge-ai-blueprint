#!/usr/bin/env bash
# Delete inventory-derived participant identities and matching local credential exports.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
ACCOUNT_HELPER="${SCRIPT_DIR}/create-participant-accounts.sh"

server_url=""
realm="digitafrica"
admin_realm=""
admin_user="admin"
admin_client_id=""
admin_client_secret_file=""
credentials_dir="${REPOSITORY_ROOT}/secrets/workshops"
assume_yes=false

usage() {
  cat <<USAGE
Usage:
  reset-participant-environment.sh --server-url URL [options]

Deletes inventory-derived participant Keycloak users and matching groups, then
removes matching local credential exports from secrets/workshops.

Required:
  --server-url URL                 Public Keycloak base URL (HTTPS)

Identity options:
  --realm NAME                     Participant realm (default: digitafrica)

Authentication: choose one method
  --admin-user USER                Administrator username (default: admin)
  --admin-client-id ID --admin-client-secret-file FILE
                                  Service-account authentication
  --admin-realm NAME               Administration realm, when required

Local credential-export options:
  --credentials-dir DIR            Directory containing protected exports
                                  (default: <repository>/secrets/workshops)
  --yes                            Do not request confirmation
  -h, --help                       Show this help
USAGE
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --server-url) server_url="${2:-}"; shift 2 ;;
    --realm) realm="${2:-}"; shift 2 ;;
    --admin-realm) admin_realm="${2:-}"; shift 2 ;;
    --admin-user) admin_user="${2:-}"; shift 2 ;;
    --admin-client-id) admin_client_id="${2:-}"; shift 2 ;;
    --admin-client-secret-file) admin_client_secret_file="${2:-}"; shift 2 ;;
    --credentials-dir) credentials_dir="${2:-}"; shift 2 ;;
    --yes) assume_yes=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

[[ -x "$ACCOUNT_HELPER" ]] || fail "Missing executable account helper: $ACCOUNT_HELPER"
[[ "$server_url" =~ ^https:// ]] || fail '--server-url must be an HTTPS URL.'
[[ -n "$realm" ]] || fail '--realm must not be empty.'

if [[ -n "$admin_client_id$admin_client_secret_file" ]]; then
  [[ -n "$admin_client_id" && -n "$admin_client_secret_file" ]] || \
    fail 'Both --admin-client-id and --admin-client-secret-file are required.'
  [[ -z "$admin_user" || "$admin_user" == "admin" ]] || \
    fail 'Choose either service-account or administrator authentication.'
else
  [[ -n "$admin_user" ]] || fail '--admin-user must not be empty.'
fi

credential_host="${server_url#https://}"
credential_host="${credential_host%%/*}"
[[ -n "$credential_host" ]] || fail 'Could not derive a credential-export hostname from --server-url.'

credential_files=()
if [[ -d "$credentials_dir" ]]; then
  shopt -s nullglob
  for credential_file in "$credentials_dir/${credential_host}-"*-credentials.tsv; do
    [[ -f "$credential_file" ]] && credential_files+=("$credential_file")
  done
  shopt -u nullglob
fi

printf '%s\n' \
  'This permanently deletes only inventory-derived participant Keycloak users and matching groups.' \
  'Administrators, service accounts, unrelated identities, workspaces, JupyterHub servers, and Flower are not changed.'

if ((${#credential_files[@]})); then
  printf 'Matching local participant credential export(s) to remove:\n'
  printf '  %s\n' "${credential_files[@]}"
else
  printf '%s\n' 'No matching local participant credential exports were found.'
fi

if [[ "$assume_yes" != true ]]; then
  printf 'Delete these participant identities and credential exports? [y/N]: '
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) printf 'No change made.\n'; exit 0 ;;
  esac
fi

account_args=(
  --server-url "$server_url"
  --realm "$realm"
  --delete-all-participants
)
[[ -n "$admin_realm" ]] && account_args+=(--admin-realm "$admin_realm")

if [[ -n "$admin_client_id" ]]; then
  account_args+=(
    --admin-client-id "$admin_client_id"
    --admin-client-secret-file "$admin_client_secret_file"
  )
else
  account_args+=(--admin-user "$admin_user")
fi

"$ACCOUNT_HELPER" "${account_args[@]}"

if ((${#credential_files[@]})); then
  rm -f -- "${credential_files[@]}"
  printf 'Removed local participant credential export(s).\n'
fi

printf 'Participant identity environment cleanup completed.\n'
