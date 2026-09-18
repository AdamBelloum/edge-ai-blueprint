#!/usr/bin/env bash
# Create/reconcile one Keycloak participant identity and group per Tier-2 worker.
# New passwords are written only to the requested mode-0600 credentials file.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DEFAULT_INVENTORY="${REPO_ROOT}/inventories/workshop/tier2/hosts.ini"
DEFAULT_WORKER_GROUP="tier2_agents"
DEFAULT_REALM="digitafrica"
DEFAULT_GROUP_PREFIX="group_"

inventory="${DEFAULT_INVENTORY}"
worker_group="${DEFAULT_WORKER_GROUP}"
server_url=""
realm="${DEFAULT_REALM}"
group_prefix="${DEFAULT_GROUP_PREFIX}"
credentials_output=""
admin_realm="master"
admin_client_id=""
admin_client_secret_file=""
admin_user=""
password_file="${KEYCLOAK_ADMIN_PASSWORD_FILE:-}"
dry_run=false

usage() {
  cat <<'EOF'
Usage:
  create-participant-accounts.sh --server-url URL --credentials-output FILE \
    [--inventory FILE] [--worker-group NAME] [--realm NAME] [options]

Creates or reconciles one Keycloak user and group per worker in the Ansible
inventory. With the defaults, workers yield identities group_01, group_02, ... .
Each identity is added to the matching Keycloak group of the same name.

Required:
  --server-url URL             Public Keycloak base URL, e.g. https://host/keycloak
  --credentials-output FILE    New mode-0600 TSV file for newly created accounts

Inventory and identity options:
  --inventory FILE             Ansible inventory (default: inventories/workshop/tier2/hosts.ini)
  --worker-group NAME          Inventory group containing worker hosts (default: tier2_workers)
  --realm NAME                 Keycloak participant realm (default: digitafrica)
  --group-prefix PREFIX        Account/group prefix (default: group_)

Authentication: choose one method
  Service account (recommended):
    --admin-client-id ID --admin-client-secret-file FILE [--admin-realm NAME]

  Administrator fallback:
    --admin-user USER [--admin-realm NAME]
    The password is read privately from /dev/tty, unless
    KEYCLOAK_ADMIN_PASSWORD_FILE points to a readable mode-0600 file.

Safety:
  --dry-run                    Show intended actions without changing Keycloak
  -h, --help                   Show this help

Notes:
  Existing accounts are never reset and their passwords cannot be recovered.
  The TSV output therefore contains passwords only for accounts created by this run.
EOF
}

fail() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }
info() { printf '[INFO] %s\n' "$*" >&2; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"; }

require_mode_600() {
  local file="$1" mode
  [[ -r "${file}" ]] || fail "Credential file is not readable: ${file}"
  mode="$(stat -c '%a' "${file}" 2>/dev/null || stat -f '%Lp' "${file}")"
  [[ "${mode}" == "600" ]] || fail "Credential file must have mode 0600: ${file} (found ${mode})"
}

urlencode() { jq -rn --arg value "$1" '$value|@uri'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url) server_url="${2:-}"; shift 2 ;;
    --inventory) inventory="${2:-}"; shift 2 ;;
    --worker-group) worker_group="${2:-}"; shift 2 ;;
    --realm) realm="${2:-}"; shift 2 ;;
    --group-prefix) group_prefix="${2:-}"; shift 2 ;;
    --credentials-output) credentials_output="${2:-}"; shift 2 ;;
    --admin-realm) admin_realm="${2:-}"; shift 2 ;;
    --admin-client-id) admin_client_id="${2:-}"; shift 2 ;;
    --admin-client-secret-file) admin_client_secret_file="${2:-}"; shift 2 ;;
    --admin-user) admin_user="${2:-}"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

require_command ansible-inventory
require_command curl
require_command jq
require_command python3
[[ -n "${server_url}" ]] || fail "--server-url is required"
[[ -n "${credentials_output}" ]] || fail "--credentials-output is required"
[[ -f "${inventory}" ]] || fail "Inventory not found: ${inventory}"
[[ "${server_url}" =~ ^https:// ]] || fail "--server-url must use https://"
[[ "${group_prefix}" =~ ^[A-Za-z0-9_-]+$ ]] || fail "--group-prefix may contain only letters, numbers, _ and -"

if [[ "${dry_run}" != true ]]; then
  if [[ -n "${admin_client_id}${admin_client_secret_file}" ]]; then
    [[ -n "${admin_client_id}" && -n "${admin_client_secret_file}" ]] || \
      fail "Service-account authentication requires both --admin-client-id and --admin-client-secret-file"
    [[ -z "${admin_user}" ]] || fail "Choose either service-account authentication or --admin-user, not both"
    require_mode_600 "${admin_client_secret_file}"
  elif [[ -n "${admin_user}" ]]; then
    if [[ -n "${password_file}" ]]; then
      require_mode_600 "${password_file}"
    else
      read -r -s -p "Keycloak administrator password for ${admin_user} in realm ${admin_realm}: " admin_password </dev/tty
      printf '\n' >&2
      [[ -n "${admin_password}" ]] || fail "A Keycloak administrator password is required."
    fi
  else
    fail "Choose service-account authentication or supply --admin-user"
  fi
fi

if [[ -e "${credentials_output}" ]]; then
  fail "Credentials output already exists; choose a new path to prevent accidental overwrite: ${credentials_output}"
fi

server_url="${server_url%/}"
api_base="${server_url}/admin/realms/${realm}"
inventory_json="$(ansible-inventory -i "${inventory}" --list)"

if ! jq -e --arg group "${worker_group}" 'has($group)' >/dev/null <<<"${inventory_json}"; then
  fail "Worker group '${worker_group}' was not found in ${inventory}"
fi

mapfile -t workers < <(
  jq -r --arg group "${worker_group}" '
    def members($root; $name):
      $root[$name] as $entry |
      ($entry.hosts // [])[],
      (($entry.children // [])[] as $child | members($root; $child));
    [members(.; $group)] | unique[]
  ' <<<"${inventory_json}"
)

[[ ${#workers[@]} -gt 0 ]] || fail "No hosts resolved from inventory group '${worker_group}'"
info "Resolved ${#workers[@]} worker(s) from ${worker_group}: ${workers[*]}"

if [[ "${dry_run}" == true ]]; then
  for index in "${!workers[@]}"; do
    printf 'Would reconcile user and group: %s (worker: %s)\n' \
      "$(printf '%s%02d' "${group_prefix}" "$((index + 1))")" "${workers[index]}"
  done
  printf 'Dry run complete: %d participant account(s) would be reconciled.\n' "${#workers[@]}"
  exit 0
fi

mkdir -p "$(dirname "${credentials_output}")"
( umask 077; : > "${credentials_output}" )
chmod 600 "${credentials_output}"

get_token() {
  local endpoint secret
  local -a payload
  endpoint="${server_url}/realms/$(urlencode "${admin_realm}")/protocol/openid-connect/token"
  if [[ -n "${admin_client_id}" ]]; then
    secret="$(<"${admin_client_secret_file}")"
    payload=(--data-urlencode 'grant_type=client_credentials' --data-urlencode "client_id=${admin_client_id}" --data-urlencode "client_secret=${secret}")
  else
    if [[ -n "${password_file}" ]]; then admin_password="$(<"${password_file}")"; fi
    payload=(--data-urlencode 'grant_type=password' --data-urlencode "client_id=admin-cli" --data-urlencode "username=${admin_user}" --data-urlencode "password=${admin_password}")
  fi
  curl --silent --show-error --fail --request POST "${endpoint}" "${payload[@]}" | jq -er '.access_token'
}

access_token="$(get_token)" || { rm -f "${credentials_output}"; fail "Could not obtain a Keycloak administrator access token"; }
unset admin_password

api() {
  local method="$1" path="$2"; shift 2
  curl --silent --show-error --fail \
    --request "${method}" \
    --header "Authorization: Bearer ${access_token}" \
    --header 'Content-Type: application/json' \
    "${api_base}${path}" "$@"
}

find_group_id() {
  local name="$1" encoded
  encoded="$(urlencode "${name}")"
  api GET "/groups?search=${encoded}&exact=true" | jq -er --arg name "${name}" '.[] | select(.name == $name) | .id' | head -n 1
}

find_user_id() {
  local username="$1" encoded
  encoded="$(urlencode "${username}")"
  api GET "/users?username=${encoded}&exact=true" | jq -er --arg username "${username}" '.[] | select(.username == $username) | .id' | head -n 1
}

random_password() {
  python3 - <<'PY'
import secrets
alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#%+=_-'
print(''.join(secrets.choice(alphabet) for _ in range(24)))
PY
}

created=0
existing=0
for index in "${!workers[@]}"; do
  number=$((index + 1))
  username="$(printf '%s%02d' "${group_prefix}" "${number}")"

  if group_id="$(find_group_id "${username}" 2>/dev/null)"; then
    :
  else
    api POST '/groups' --data "$(jq -cn --arg name "${username}" '{name: $name}')" >/dev/null
    group_id="$(find_group_id "${username}")" || fail "Created group '${username}' but could not retrieve it"
    info "Created Keycloak group: ${username}"
  fi

  if user_id="$(find_user_id "${username}" 2>/dev/null)"; then
    api PUT "/users/${user_id}/groups/${group_id}" >/dev/null
    info "Reconciled existing participant: ${username}"
    existing=$((existing + 1))
    continue
  fi

  api POST '/users' --data "$(jq -cn --arg username "${username}" '{username: $username, enabled: true, emailVerified: false}')" >/dev/null
  user_id="$(find_user_id "${username}")" || fail "Created user '${username}' but could not retrieve it"
  password="$(random_password)"
  api PUT "/users/${user_id}/reset-password" --data "$(jq -cn --arg value "${password}" '{type: "password", value: $value, temporary: true}')" >/dev/null
  api PUT "/users/${user_id}/groups/${group_id}" >/dev/null

  printf '%s\t%s\t%s\n' "${username}" "${password}" "${workers[index]}" >> "${credentials_output}"
  info "Created participant: ${username}"
  unset password
  created=$((created + 1))
done

printf 'Participant account preparation complete: created=%d, existing=%d, total=%d.\n' \
  "${created}" "${existing}" "${#workers[@]}"
printf 'New credentials (mode 0600): %s\n' "${credentials_output}"
