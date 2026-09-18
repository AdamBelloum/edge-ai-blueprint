#!/usr/bin/env bash
# Reconcile the DIGITAfrica Keycloak realm integration for JupyterHub.
#
# This script uses Keycloak's Admin REST API. It never prints an administrator
# password, bearer token, or JupyterHub client secret. The client secret is
# written only to the requested output file with mode 0600.
#
# version: 0.3.0
#
set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"

SCRIPT_VERSION="0.3.0"
SERVER_URL=""
REALM="digitafrica"
CLIENT_ID="jupyterhub"
REDIRECT_URI=""
WEB_ORIGIN=""
ADMIN_REALM="master"
ADMIN_USER=""
ADMIN_CLIENT_ID=""
ADMIN_CLIENT_SECRET_FILE=""
ADMIN_CLIENT_SECRET=""
CLIENT_SECRET_OUTPUT=""
GROUP_SCOPE_NAME="jupyterhub-groups"

ADMIN_PASSWORD=""
ACCESS_TOKEN=""

info() { printf '[INFO] %s\n' "$*"; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage:
  ${SCRIPT_NAME} --server-url URL --realm NAME --client-id ID \\
    --redirect-uri URL --web-origin URL --client-secret-output FILE \
    [authentication options] [options]

Required:
  --server-url URL             Keycloak public base URL, e.g. https://host/keycloak
  --redirect-uri URL           Exact JupyterHub OAuth callback URL
  --web-origin URL             Public browser origin, e.g. https://host
  --client-secret-output FILE  Destination for the JupyterHub client secret

Optional:
  --realm NAME                 Target realm (default: digitafrica)
  --client-id ID               JupyterHub confidential client ID (default: jupyterhub)
  --admin-client-id ID         Service-account client ID in the target realm
  --admin-client-secret-file FILE
                               Readable mode-0600 file containing its secret
  --admin-realm NAME           Realm containing the administrator (default: master)
  --group-scope-name NAME      Default groups scope name (default: jupyterhub-groups)
  --version                    Print the script version
  -h, --help                   Show this help

Authentication — choose one method:

  Service account (recommended):
  Supply both --admin-client-id and --admin-client-secret-file.

  Administrator fallback:
  Supply --admin-user. The script prompts for its password without echoing it.
  Alternatively, set KEYCLOAK_ADMIN_PASSWORD_FILE to a readable mode-0600 file.
  Passwords and client secrets are never logged or stored by this script.
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_nonempty() {
  local option="$1" value="$2"
  [[ -n "$value" ]] || die "Missing required option: ${option}"
}

require_https_url() {
  local option="$1" value="$2"
  [[ "$value" =~ ^https://[^[:space:]]+$ ]] || die "${option} must be an https URL."
}

json_error_message() {
  local body_file="$1"
  jq -r '.error_description // .errorMessage // .error // "no error message returned"' "$body_file" 2>/dev/null ||
    printf 'no parseable error message returned'
}

# Writes successful response bodies to stdout. It intentionally does not print
# request payloads, credentials, access tokens, or client secrets.
api() {
  local method="$1" path="$2" payload="${3:-}"
  local body_file http_status curl_args=()

  body_file="$(mktemp)"
  curl_args=(
    --silent --show-error --output "$body_file" --write-out '%{http_code}'
    --request "$method"
    --header "Authorization: Bearer ${ACCESS_TOKEN}"
    --header 'Accept: application/json'
  )
  if [[ -n "$payload" ]]; then
    curl_args+=(--header 'Content-Type: application/json' --data "$payload")
  fi

  if ! http_status="$(curl "${curl_args[@]}" "${SERVER_URL}/${path}")"; then
    rm -f "$body_file"
    die "Keycloak request failed: ${method} /${path}"
  fi
  if [[ "$http_status" != 2* ]]; then
    local message
    message="$(json_error_message "$body_file")"
    rm -f "$body_file"
    die "Keycloak returned HTTP ${http_status} for ${method} /${path}: ${message}"
  fi
  cat "$body_file"
  rm -f "$body_file"
}

resource_exists() {
  local path="$1" body_file http_status
  body_file="$(mktemp)"
  if ! http_status="$(curl --silent --show-error --output "$body_file" --write-out '%{http_code}' \
    --header "Authorization: Bearer ${ACCESS_TOKEN}" \
    --header 'Accept: application/json' \
    "${SERVER_URL}/${path}")"; then
    rm -f "$body_file"
    die "Keycloak request failed: GET /${path}"
  fi
  case "$http_status" in
    2*) cat "$body_file"; rm -f "$body_file"; return 0 ;;
    404) rm -f "$body_file"; return 1 ;;
    *)
      local message
      message="$(json_error_message "$body_file")"
      rm -f "$body_file"
      die "Keycloak returned HTTP ${http_status} for GET /${path}: ${message}"
      ;;
  esac
}

urlencode() { jq -rn --arg value "$1" '$value | @uri'; }

obtain_access_token() {
  local token_response token_endpoint token_body http_status message

  token_endpoint="${SERVER_URL}/realms/${ADMIN_REALM}/protocol/openid-connect/token"
  token_body="$(mktemp)"

  if ! http_status="$(curl --silent --show-error \
    --output "$token_body" --write-out '%{http_code}' \
    --request POST "$token_endpoint" \
    --header 'Content-Type: application/x-www-form-urlencoded' \
    --data 'grant_type=password' \
    --data 'client_id=admin-cli' \
    --data-urlencode "username=${ADMIN_USER}" \
    --data-urlencode "password=${ADMIN_PASSWORD}")"; then
    rm -f "$token_body"
    die "Could not reach the Keycloak token endpoint."
  fi

  if [[ "$http_status" != 2* ]]; then
    message="$(json_error_message "$token_body")"
    rm -f "$token_body"
    die "Keycloak administrator token request returned HTTP ${http_status}: ${message}"
  fi

  token_response="$(<"$token_body")"
  rm -f "$token_body"

  ACCESS_TOKEN="$(jq -er '.access_token' <<<"$token_response")" \
    || die "Keycloak token response did not contain an access token."
}

read_admin_password() {
  if [[ -n "${KEYCLOAK_ADMIN_PASSWORD_FILE:-}" ]]; then
    [[ -r "${KEYCLOAK_ADMIN_PASSWORD_FILE}" ]] || die "KEYCLOAK_ADMIN_PASSWORD_FILE is not readable."
    [[ "$(stat -c '%a' "${KEYCLOAK_ADMIN_PASSWORD_FILE}")" == "600" ]] ||
      die "KEYCLOAK_ADMIN_PASSWORD_FILE must have mode 0600."
    ADMIN_PASSWORD="$(<"${KEYCLOAK_ADMIN_PASSWORD_FILE}")"
  else
    read -r -s -p "Keycloak administrator password for ${ADMIN_USER} in realm ${ADMIN_REALM}: " ADMIN_PASSWORD
    printf '\n'
  fi
  [[ -n "$ADMIN_PASSWORD" ]] || die "A Keycloak administrator password is required."
}


read_admin_client_secret() {
  [[ -r "$ADMIN_CLIENT_SECRET_FILE" ]] ||
    die "--admin-client-secret-file is not readable."
  [[ "$(stat -c '%a' "$ADMIN_CLIENT_SECRET_FILE")" == "600" ]] ||
    die "--admin-client-secret-file must have mode 0600."

  ADMIN_CLIENT_SECRET="$(<"$ADMIN_CLIENT_SECRET_FILE")"
  [[ -n "$ADMIN_CLIENT_SECRET" ]] ||
    die "--admin-client-secret-file must not be empty."
}

obtain_client_access_token() {
  local token_response token_endpoint token_body http_status message

  token_endpoint="${SERVER_URL}/realms/${REALM}/protocol/openid-connect/token"
  token_body="$(mktemp)"

  if ! http_status="$(curl --silent --show-error \
    --output "$token_body" --write-out '%{http_code}' \
    --request POST "$token_endpoint" \
    --header 'Content-Type: application/x-www-form-urlencoded' \
    --data 'grant_type=client_credentials' \
    --data-urlencode "client_id=${ADMIN_CLIENT_ID}" \
    --data-urlencode "client_secret=${ADMIN_CLIENT_SECRET}")"; then
    rm -f "$token_body"
    die "Could not reach the Keycloak token endpoint."
  fi

  if [[ "$http_status" != 2* ]]; then
    message="$(json_error_message "$token_body")"
    rm -f "$token_body"
    die "Keycloak service-account token request returned HTTP ${http_status}: ${message}"
  fi

  token_response="$(<"$token_body")"
  rm -f "$token_body"

  ACCESS_TOKEN="$(jq -er '.access_token' <<<"$token_response")" ||
    die "Keycloak token response did not contain an access token."
}

ensure_realm() {
  if resource_exists "admin/realms/${REALM}" >/dev/null; then
    info "Realm exists: ${REALM}"
    return
  fi
  info "Creating realm: ${REALM}"
  api POST 'admin/realms' "$(jq -cn --arg realm "$REALM" '{realm: $realm, enabled: true}')" >/dev/null
}

find_client_uuid() {
  local clients client_uuid
  clients="$(api GET "admin/realms/${REALM}/clients?clientId=$(urlencode "$CLIENT_ID")")"
  client_uuid="$(jq -er --arg client_id "$CLIENT_ID" '.[] | select(.clientId == $client_id) | .id' <<<"$clients" | head -n 1)" || return 1
  printf '%s\n' "$client_uuid"
}

ensure_client() {
  local client_uuid current desired
  if client_uuid="$(find_client_uuid)"; then
    info "Reconciling confidential OIDC client: ${CLIENT_ID}"
    current="$(api GET "admin/realms/${REALM}/clients/${client_uuid}")"
    desired="$(jq --arg redirect_uri "$REDIRECT_URI" --arg web_origin "$WEB_ORIGIN" --arg client_id "$CLIENT_ID" \
      '.clientId = $client_id |
       .name = "JupyterHub" |
       .enabled = true |
       .protocol = "openid-connect" |
       .publicClient = false |
       .standardFlowEnabled = true |
       .directAccessGrantsEnabled = false |
       .serviceAccountsEnabled = false |
       .redirectUris = [$redirect_uri] |
       .webOrigins = [$web_origin] |
       .attributes = ((.attributes // {}) + {"pkce.code.challenge.method": "S256"})' <<<"$current")"
    api PUT "admin/realms/${REALM}/clients/${client_uuid}" "$desired" >/dev/null
  else
    info "Creating confidential OIDC client: ${CLIENT_ID}"
    desired="$(jq -cn --arg client_id "$CLIENT_ID" --arg redirect_uri "$REDIRECT_URI" --arg web_origin "$WEB_ORIGIN" \
      '{clientId: $client_id, name: "JupyterHub", enabled: true, protocol: "openid-connect",
        publicClient: false, standardFlowEnabled: true, directAccessGrantsEnabled: false,
        serviceAccountsEnabled: false, redirectUris: [$redirect_uri], webOrigins: [$web_origin],
        attributes: {"pkce.code.challenge.method": "S256"}}')"
    api POST "admin/realms/${REALM}/clients" "$desired" >/dev/null
    client_uuid="$(find_client_uuid)" || die "Created client ${CLIENT_ID}, but could not retrieve its internal ID."
  fi
  JUPYTERHUB_CLIENT_UUID="$client_uuid"
}

find_scope_uuid() {
  local scopes scope_uuid
  scopes="$(api GET "admin/realms/${REALM}/client-scopes")"
  scope_uuid="$(jq -er --arg scope_name "$GROUP_SCOPE_NAME" '.[] | select(.name == $scope_name) | .id' <<<"$scopes" | head -n 1)" || return 1
  printf '%s\n' "$scope_uuid"
}

ensure_groups_scope_and_mapper() {
  local scope_uuid mapper_id mappers mapper
  if scope_uuid="$(find_scope_uuid)"; then
    info "Client scope exists: ${GROUP_SCOPE_NAME}"
  else
    info "Creating client scope: ${GROUP_SCOPE_NAME}"
    api POST "admin/realms/${REALM}/client-scopes" "$(jq -cn --arg scope_name "$GROUP_SCOPE_NAME" \
      '{name: $scope_name, protocol: "openid-connect", attributes: {"include.in.token.scope": "true", "display.on.consent.screen": "false"}}')" >/dev/null
    scope_uuid="$(find_scope_uuid)" || die "Created scope ${GROUP_SCOPE_NAME}, but could not retrieve its internal ID."
  fi

  mappers="$(api GET "admin/realms/${REALM}/client-scopes/${scope_uuid}/protocol-mappers/models")"
  mapper_id="$(jq -r '.[] | select(.name == "groups") | .id' <<<"$mappers" | head -n 1)"
  mapper="$(jq -cn '{name: "groups", protocol: "openid-connect", protocolMapper: "oidc-group-membership-mapper", consentRequired: false, config: {"full.path": "false", "id.token.claim": "true", "access.token.claim": "true", "userinfo.token.claim": "true", "claim.name": "groups"}}')"

  if [[ -n "$mapper_id" && "$mapper_id" != "null" ]]; then
    info "Reconciling groups protocol mapper."
    mapper="$(jq --arg id "$mapper_id" '. + {id: $id}' <<<"$mapper")"
    api PUT "admin/realms/${REALM}/client-scopes/${scope_uuid}/protocol-mappers/models/${mapper_id}" "$mapper" >/dev/null
  else
    info "Creating groups protocol mapper."
    api POST "admin/realms/${REALM}/client-scopes/${scope_uuid}/protocol-mappers/models" "$mapper" >/dev/null
  fi

  if api GET "admin/realms/${REALM}/clients/${JUPYTERHUB_CLIENT_UUID}/default-client-scopes" |
      jq -e --arg scope_id "$scope_uuid" '.[] | select(.id == $scope_id)' >/dev/null; then
    info "Client scope is already assigned by default: ${GROUP_SCOPE_NAME}"
  else
    info "Assigning default client scope: ${GROUP_SCOPE_NAME}"
    api PUT "admin/realms/${REALM}/clients/${JUPYTERHUB_CLIENT_UUID}/default-client-scopes/${scope_uuid}" >/dev/null
  fi
}

write_client_secret() {
  local secret output_dir temp_file
  secret="$(api GET "admin/realms/${REALM}/clients/${JUPYTERHUB_CLIENT_UUID}/client-secret" | jq -er '.value')" ||
    die "Keycloak did not return a client secret for ${CLIENT_ID}."
  output_dir="$(dirname "$CLIENT_SECRET_OUTPUT")"
  mkdir -p "$output_dir"
  temp_file="$(mktemp "${output_dir}/.${CLIENT_ID}.secret.XXXXXX")"
  chmod 600 "$temp_file"
  printf '%s\n' "$secret" >"$temp_file"
  mv -f "$temp_file" "$CLIENT_SECRET_OUTPUT"
  chmod 600 "$CLIENT_SECRET_OUTPUT"
  info "Wrote JupyterHub client secret to ${CLIENT_SECRET_OUTPUT} (mode 0600)."
}

while (($#)); do
  case "$1" in
    --server-url) SERVER_URL="${2:-}"; shift 2 ;;
    --realm) REALM="${2:-}"; shift 2 ;;
    --client-id) CLIENT_ID="${2:-}"; shift 2 ;;
    --redirect-uri) REDIRECT_URI="${2:-}"; shift 2 ;;
    --web-origin) WEB_ORIGIN="${2:-}"; shift 2 ;;
    --admin-realm) ADMIN_REALM="${2:-}"; shift 2 ;;
    --admin-user) ADMIN_USER="${2:-}"; shift 2 ;;
    --admin-client-id) ADMIN_CLIENT_ID="${2:-}"; shift 2 ;;
    --admin-client-secret-file) ADMIN_CLIENT_SECRET_FILE="${2:-}"; shift 2 ;;
    --client-secret-output) CLIENT_SECRET_OUTPUT="${2:-}"; shift 2 ;;
    --group-scope-name) GROUP_SCOPE_NAME="${2:-}"; shift 2 ;;
    --version) printf '%s\n' "${SCRIPT_VERSION}"; exit 0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "Unknown option: $1" ;;
  esac
done

require_command curl
require_command jq
require_command stat
require_nonempty --server-url "$SERVER_URL"
require_nonempty --redirect-uri "$REDIRECT_URI"
require_nonempty --web-origin "$WEB_ORIGIN"
require_nonempty --client-secret-output "$CLIENT_SECRET_OUTPUT"
if [[ -n "$ADMIN_CLIENT_ID" || -n "$ADMIN_CLIENT_SECRET_FILE" ]]; then
  require_nonempty --admin-client-id "$ADMIN_CLIENT_ID"
  require_nonempty --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE"
  [[ -z "$ADMIN_USER" ]] ||
    die "Use either --admin-user or --admin-client-id, not both."
else
  require_nonempty --admin-user "$ADMIN_USER"
fi
require_https_url --server-url "$SERVER_URL"
require_https_url --redirect-uri "$REDIRECT_URI"
require_https_url --web-origin "$WEB_ORIGIN"

SERVER_URL="${SERVER_URL%/}"
if [[ -n "$ADMIN_CLIENT_ID" ]]; then
  read_admin_client_secret
  obtain_client_access_token
else
  read_admin_password
  obtain_access_token
fi
ensure_realm
ensure_client
ensure_groups_scope_and_mapper
write_client_secret
ADMIN_PASSWORD=""
ADMIN_CLIENT_SECRET=""
ACCESS_TOKEN=""
info "Keycloak bootstrap completed for realm ${REALM} and client ${CLIENT_ID}."
