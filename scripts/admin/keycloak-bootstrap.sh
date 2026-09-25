#!/usr/bin/env bash
# Reconcile a DIGITAfrica Keycloak realm and JupyterHub OIDC client.
#
# This command is standalone. It may be invoked directly or by setup-wizard.sh.
# It never prints passwords, access tokens, or client secrets.

set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"

SERVER_URL=""
CA_CERT=""
REALM="digitafrica"
ADMIN_REALM="master"
ADMIN_USER="admin"
REALM_MANAGER_CLIENT_ID="realm-manager"
REALM_MANAGER_SECRET_OUTPUT=""
JUPYTERHUB_CLIENT_ID="jupyterhub"
JUPYTERHUB_SECRET_OUTPUT=""
JUPYTERHUB_REDIRECT_URI=""
JUPYTERHUB_WEB_ORIGIN=""
ROTATE_REALM_MANAGER_SECRET="false"
ROTATE_JUPYTERHUB_SECRET="false"

MASTER_TOKEN=""
MANAGER_TOKEN=""
ADMIN_PASSWORD=""

info() { printf '[INFO] %s\n' "$*" >&2; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<USAGE
Usage:
  ${SCRIPT_NAME} --server-url URL --realm NAME [OPTIONS]

Required:
  --server-url URL                    Trusted public Keycloak base URL.
  --jupyterhub-redirect-uri URL       JupyterHub OAuth callback URL.
  --jupyterhub-web-origin URL         Public JupyterHub web origin.

Options:
  --ca-cert FILE                      Additional trusted CA certificate.
  --realm NAME                        Target realm; default: digitafrica.
  --admin-realm NAME                  Initial administrator realm; default: master.
  --admin-user NAME                   Initial administrator user; default: admin.
  --realm-manager-client-id ID        Default: realm-manager.
  --realm-manager-secret-output FILE  Protected local output path.
  --jupyterhub-client-id ID           Default: jupyterhub.
  --jupyterhub-secret-output FILE     Protected local output path.
  --rotate-realm-manager-secret       Deliberately rotate that secret.
  --rotate-jupyterhub-secret          Deliberately rotate that secret.
  -h, --help                          Show this help.

Authentication:
  Set KEYCLOAK_ADMIN_PASSWORD_FILE to an existing mode-0600 password file,
  or enter the initial master-administrator password interactively.
USAGE
}

require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    die "Required command not found: $1"
}

urlencode() {
  jq -rn --arg value "$1" '$value | @uri'
}

curl_args() {
  local -a args=(--fail --silent --show-error)
  [[ -n "$CA_CERT" ]] && args+=(--cacert "$CA_CERT")
  printf '%s\0' "${args[@]}"
}

curl_request() {
  local -a args=()
  while IFS= read -r -d '' arg; do args+=("$arg"); done < <(curl_args)
  curl "${args[@]}" "$@"
}

validate_inputs() {
  [[ "$SERVER_URL" =~ ^https://[^[:space:]]+$ ]] ||
    die "--server-url must be an HTTPS URL."
  [[ "$REALM" =~ ^[A-Za-z0-9._-]+$ ]] ||
    die "Invalid realm name."
  [[ "$ADMIN_REALM" =~ ^[A-Za-z0-9._-]+$ ]] ||
    die "Invalid administrator realm."
  [[ "$ADMIN_USER" =~ ^[A-Za-z0-9._-]+$ ]] ||
    die "Invalid administrator username."
  [[ -n "$JUPYTERHUB_REDIRECT_URI" ]] ||
    die "--jupyterhub-redirect-uri is required."
  [[ -n "$JUPYTERHUB_WEB_ORIGIN" ]] ||
    die "--jupyterhub-web-origin is required."
  [[ "$JUPYTERHUB_REDIRECT_URI" =~ ^https:// ]] ||
    die "JupyterHub redirect URI must use HTTPS."
  [[ "$JUPYTERHUB_WEB_ORIGIN" =~ ^https:// ]] ||
    die "JupyterHub web origin must use HTTPS."
  [[ -z "$CA_CERT" || -r "$CA_CERT" ]] ||
    die "CA certificate is not readable: ${CA_CERT}"

  SERVER_URL="${SERVER_URL%/}"
  [[ -n "$REALM_MANAGER_SECRET_OUTPUT" ]] ||
    REALM_MANAGER_SECRET_OUTPUT="secrets/keycloak/${REALM}/realm-manager-client.secret"
  [[ -n "$JUPYTERHUB_SECRET_OUTPUT" ]] ||
    JUPYTERHUB_SECRET_OUTPUT="secrets/keycloak/${REALM}/jupyterhub-client.secret"
}

verify_discovery() {
  local endpoint="${SERVER_URL}/realms/master/.well-known/openid-configuration"
  info "Verifying trusted Keycloak HTTPS endpoint."
  curl_request "$endpoint" | jq -e '.issuer and .token_endpoint' >/dev/null ||
    die "Keycloak discovery is unavailable or does not present trusted TLS: ${endpoint}"
}

read_admin_password() {
  if [[ -n "${KEYCLOAK_ADMIN_PASSWORD_FILE:-}" ]]; then
    [[ -r "$KEYCLOAK_ADMIN_PASSWORD_FILE" ]] ||
      die "KEYCLOAK_ADMIN_PASSWORD_FILE is not readable."
    [[ "$(stat -c '%a' "$KEYCLOAK_ADMIN_PASSWORD_FILE")" == "600" ]] ||
      die "KEYCLOAK_ADMIN_PASSWORD_FILE must have mode 0600."
    ADMIN_PASSWORD="$(<"$KEYCLOAK_ADMIN_PASSWORD_FILE")"
  else
    read -r -s -p \
      "Keycloak administrator password for ${ADMIN_USER} in ${ADMIN_REALM}: " \
      ADMIN_PASSWORD
    printf '\n'
  fi

  [[ -n "$ADMIN_PASSWORD" ]] ||
    die "Keycloak administrator password must not be empty."
}

obtain_master_token() {
  local response
  response="$(
    curl_request \
      --request POST \
      "${SERVER_URL}/realms/$(urlencode "$ADMIN_REALM")/protocol/openid-connect/token" \
      --header 'Content-Type: application/x-www-form-urlencoded' \
      --data 'grant_type=password' \
      --data 'client_id=admin-cli' \
      --data-urlencode "username=${ADMIN_USER}" \
      --data-urlencode "password=${ADMIN_PASSWORD}"
  )" || die "Initial administrator authentication failed."

  MASTER_TOKEN="$(jq -er '.access_token' <<<"$response")" ||
    die "Token response did not contain an access token."
  unset ADMIN_PASSWORD
}

api() {
  local token="$1"
  local method="$2"
  local path="$3"
  local payload="${4:-}"
  local -a options=(
    --request "$method"
    --header "Authorization: Bearer ${token}"
    --header 'Accept: application/json'
  )

  [[ -n "$payload" ]] &&
    options+=(--header 'Content-Type: application/json' --data "$payload")

  if ! curl_request "${options[@]}" "${SERVER_URL}/${path}"; then
    die "Keycloak API request failed: ${method} /${path}"
  fi
}

api_exists() {
  local token="$1"
  local path="$2"
  local status body

  body="$(mktemp)"
  status="$(
    curl_request --output "$body" --write-out '%{http_code}' \
      --header "Authorization: Bearer ${token}" \
      --header 'Accept: application/json' \
      "${SERVER_URL}/${path}" || true
  )"

  case "$status" in
    2*) cat "$body"; rm -f "$body"; return 0 ;;
    404) rm -f "$body"; return 1 ;;
    *) rm -f "$body"; die "Keycloak returned HTTP ${status} for GET /${path}" ;;
  esac
}

client_uuid() {
  local token="$1"
  local client_id="$2"

  api "$token" GET \
    "admin/realms/$(urlencode "$REALM")/clients?clientId=$(urlencode "$client_id")" |
    jq -er --arg id "$client_id" \
      '.[] | select(.clientId == $id) | .id' | head -n 1
}

ensure_realm() {
  if api_exists "$MASTER_TOKEN" \
    "admin/realms/$(urlencode "$REALM")" >/dev/null; then
    info "Realm exists: ${REALM}"
  else
    info "Creating realm: ${REALM}"
    api "$MASTER_TOKEN" POST admin/realms \
      "$(jq -cn --arg realm "$REALM" '{realm:$realm,enabled:true}')" \
      >/dev/null
  fi
}

ensure_client() {
  local token="$1"
  local client_id="$2"
  local desired="$3"
  local uuid current

  if uuid="$(client_uuid "$token" "$client_id" 2>/dev/null)"; then
    info "Reconciling client: ${client_id}"
    current="$(api "$token" GET \
      "admin/realms/$(urlencode "$REALM")/clients/${uuid}")"
    api "$token" PUT \
      "admin/realms/$(urlencode "$REALM")/clients/${uuid}" \
      "$(jq --argjson desired "$desired"         'del(.protocolMappers) | . * $desired' <<<"$current")" \
      >/dev/null
  else
    info "Creating client: ${client_id}"
    api "$token" POST \
      "admin/realms/$(urlencode "$REALM")/clients" "$desired" >/dev/null
    uuid="$(client_uuid "$token" "$client_id")" ||
      die "Created ${client_id}, but could not retrieve its internal ID."
  fi

  printf '%s\n' "$uuid"
}

write_secret_if_needed() {
  local token="$1"
  local uuid="$2"
  local output="$3"
  local rotate="$4"
  local secret temporary

  if [[ -f "$output" && "$rotate" != "true" ]]; then
    [[ "$(stat -c '%a' "$output")" == "600" ]] ||
      die "Existing secret file must have mode 0600: ${output}"
    info "Retaining existing protected secret record: ${output}"
    return 0
  fi

  secret="$(
    api "$token" POST \
      "admin/realms/$(urlencode "$REALM")/clients/${uuid}/client-secret" |
      jq -er '.value'
  )" || die "Could not obtain client secret."

  umask 077
  mkdir -p "$(dirname "$output")"
  chmod 700 "$(dirname "$output")"
  temporary="$(mktemp "${output}.tmp.XXXXXX")"
  printf '%s\n' "$secret" > "$temporary"
  chmod 600 "$temporary"
  mv -f "$temporary" "$output"
  unset secret
  info "Saved protected secret record: ${output}"
}

ensure_realm_manager_roles() {
  local uuid="$1"
  local service_account management_client mapping role

  service_account="$(
    api "$MASTER_TOKEN" GET \
      "admin/realms/$(urlencode "$REALM")/clients/${uuid}/service-account-user" |
      jq -er '.id'
  )"

  management_client="$(
    api "$MASTER_TOKEN" GET \
      "admin/realms/$(urlencode "$REALM")/clients?clientId=realm-management" |
      jq -er '.[] | select(.clientId == "realm-management") | .id'
  )"

  mapping="$(
    api "$MASTER_TOKEN" GET \
      "admin/realms/$(urlencode "$REALM")/users/${service_account}/role-mappings/clients/${management_client}"
  )"

  for role in view-realm manage-users query-users view-users manage-clients query-clients; do
    if jq -e --arg role "$role" \
      '.[] | select(.name == $role)' <<<"$mapping" >/dev/null; then
      continue
    fi

    info "Assigning realm-manager role: ${role}"
    api "$MASTER_TOKEN" POST \
      "admin/realms/$(urlencode "$REALM")/users/${service_account}/role-mappings/clients/${management_client}" \
      "$(
        api "$MASTER_TOKEN" GET \
          "admin/realms/$(urlencode "$REALM")/clients/${management_client}/roles/$(urlencode "$role")" |
          jq -c '[.]'
      )" >/dev/null
  done
}

obtain_manager_token() {
  local secret response
  secret="$(<"$REALM_MANAGER_SECRET_OUTPUT")"

  response="$(
    curl_request \
      --request POST \
      "${SERVER_URL}/realms/$(urlencode "$REALM")/protocol/openid-connect/token" \
      --header 'Content-Type: application/x-www-form-urlencoded' \
      --data 'grant_type=client_credentials' \
      --data-urlencode "client_id=${REALM_MANAGER_CLIENT_ID}" \
      --data-urlencode "client_secret=${secret}"
  )" || die "realm-manager client-credentials authentication failed."

  MANAGER_TOKEN="$(jq -er '.access_token' <<<"$response")" ||
    die "realm-manager token response did not contain an access token."
  unset secret
}

ensure_groups_mapper() {
  local client_uuid="$1"
  local mappers mapper_uuid desired

  desired="$(
    jq -cn '{
      name:"groups",
      protocol:"openid-connect",
      protocolMapper:"oidc-group-membership-mapper",
      config:{
        "claim.name":"groups",
        "full.path":"false",
        "id.token.claim":"true",
        "access.token.claim":"true",
        "userinfo.token.claim":"true"
      }
    }'
  )"

  mappers="$(
    api "$MANAGER_TOKEN" GET \
      "admin/realms/$(urlencode "$REALM")/clients/${client_uuid}/protocol-mappers/models"
  )"

  mapper_uuid="$(
    jq -r '.[] | select(
      .name == "groups" and
      .protocolMapper == "oidc-group-membership-mapper"
    ) | .id' <<<"$mappers" | head -n 1
  )"

  # Keycloak 26 can return HTTP 500 for protocol-mapper PUT requests.
  # This bootstrapper owns only this named mapper, so replace it instead.
  if [[ -n "$mapper_uuid" && "$mapper_uuid" != "null" ]]; then
    info "Replacing managed groups protocol mapper."
    api "$MANAGER_TOKEN" DELETE \
      "admin/realms/$(urlencode "$REALM")/clients/${client_uuid}/protocol-mappers/models/${mapper_uuid}" \
      >/dev/null
  fi

  api "$MANAGER_TOKEN" POST \
    "admin/realms/$(urlencode "$REALM")/clients/${client_uuid}/protocol-mappers/models" \
    "$desired" >/dev/null
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --server-url) SERVER_URL="${2:?missing URL}"; shift 2 ;;
      --ca-cert) CA_CERT="${2:?missing certificate path}"; shift 2 ;;
      --realm) REALM="${2:?missing realm}"; shift 2 ;;
      --admin-realm) ADMIN_REALM="${2:?missing realm}"; shift 2 ;;
      --admin-user) ADMIN_USER="${2:?missing user}"; shift 2 ;;
      --realm-manager-client-id) REALM_MANAGER_CLIENT_ID="${2:?missing ID}"; shift 2 ;;
      --realm-manager-secret-output) REALM_MANAGER_SECRET_OUTPUT="${2:?missing path}"; shift 2 ;;
      --jupyterhub-client-id) JUPYTERHUB_CLIENT_ID="${2:?missing ID}"; shift 2 ;;
      --jupyterhub-secret-output) JUPYTERHUB_SECRET_OUTPUT="${2:?missing path}"; shift 2 ;;
      --jupyterhub-redirect-uri) JUPYTERHUB_REDIRECT_URI="${2:?missing URI}"; shift 2 ;;
      --jupyterhub-web-origin) JUPYTERHUB_WEB_ORIGIN="${2:?missing origin}"; shift 2 ;;
      --rotate-realm-manager-secret) ROTATE_REALM_MANAGER_SECRET="true"; shift ;;
      --rotate-jupyterhub-secret) ROTATE_JUPYTERHUB_SECRET="true"; shift ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown argument: $1" ;;
    esac
  done

  require_command curl
  require_command jq
  require_command stat
  validate_inputs
  verify_discovery
  read_admin_password
  obtain_master_token
  ensure_realm

  realm_manager_definition="$(
    jq -cn --arg id "$REALM_MANAGER_CLIENT_ID" '{
      clientId:$id,
      name:"DIGITAfrica realm manager",
      enabled:true,
      protocol:"openid-connect",
      publicClient:false,
      standardFlowEnabled:false,
      directAccessGrantsEnabled:false,
      serviceAccountsEnabled:true,
      bearerOnly:false,
      redirectUris:[],
      webOrigins:[]
    }'
  )"

  realm_manager_uuid="$(
    ensure_client "$MASTER_TOKEN" "$REALM_MANAGER_CLIENT_ID" \
      "$realm_manager_definition"
  )"

  ensure_realm_manager_roles "$realm_manager_uuid"

  write_secret_if_needed \
    "$MASTER_TOKEN" "$realm_manager_uuid" \
    "$REALM_MANAGER_SECRET_OUTPUT" "$ROTATE_REALM_MANAGER_SECRET"

  obtain_manager_token

  jupyterhub_definition="$(
    jq -cn \
      --arg id "$JUPYTERHUB_CLIENT_ID" \
      --arg redirect "$JUPYTERHUB_REDIRECT_URI" \
      --arg origin "$JUPYTERHUB_WEB_ORIGIN" '{
        clientId:$id,
        name:"DIGITAfrica JupyterHub",
        enabled:true,
        protocol:"openid-connect",
        publicClient:false,
        standardFlowEnabled:true,
        directAccessGrantsEnabled:false,
        serviceAccountsEnabled:false,
        bearerOnly:false,
        redirectUris:[$redirect],
        webOrigins:[$origin]
      }'
  )"

  jupyterhub_uuid="$(
    ensure_client "$MANAGER_TOKEN" "$JUPYTERHUB_CLIENT_ID" \
      "$jupyterhub_definition"
  )"

  ensure_groups_mapper "$jupyterhub_uuid"

  write_secret_if_needed \
    "$MANAGER_TOKEN" "$jupyterhub_uuid" \
    "$JUPYTERHUB_SECRET_OUTPUT" "$ROTATE_JUPYTERHUB_SECRET"

  info "Keycloak realm and JupyterHub OIDC client bootstrap completed."
}

main "$@"
