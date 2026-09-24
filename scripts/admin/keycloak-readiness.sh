#!/usr/bin/env bash
# Wait for trusted public Keycloak OpenID Connect discovery readiness.
# This script is read-only and never handles credentials or secrets.

set -Eeuo pipefail

SERVER_URL=""
REALM="master"
CA_CERT=""
TIMEOUT_SECONDS="600"
INTERVAL_SECONDS="5"

info() { printf '[INFO] %s\n' "$*" >&2; }
die() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage:
  scripts/admin/keycloak-readiness.sh --server-url HTTPS_URL [OPTIONS]

Options:
  --realm NAME             Realm used for discovery; default: master.
  --ca-cert FILE           Additional trusted CA certificate.
  --timeout-seconds N      Maximum wait time; default: 600.
  --interval-seconds N     Retry interval; default: 5.
  -h, --help               Show this help.
USAGE
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --server-url) SERVER_URL="${2:?missing URL}"; shift 2 ;;
      --realm) REALM="${2:?missing realm}"; shift 2 ;;
      --ca-cert) CA_CERT="${2:?missing certificate path}"; shift 2 ;;
      --timeout-seconds) TIMEOUT_SECONDS="${2:?missing timeout}"; shift 2 ;;
      --interval-seconds) INTERVAL_SECONDS="${2:?missing interval}"; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown argument: $1" ;;
    esac
  done

  [[ "$SERVER_URL" =~ ^https://[^[:space:]]+$ ]] ||
    die "--server-url must be a trusted HTTPS URL."
  [[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] ||
    die "--timeout-seconds must be a positive integer."
  [[ "$INTERVAL_SECONDS" =~ ^[1-9][0-9]*$ ]] ||
    die "--interval-seconds must be a positive integer."
  [[ -z "$CA_CERT" || -r "$CA_CERT" ]] ||
    die "CA certificate is not readable: ${CA_CERT}"

  command -v curl >/dev/null 2>&1 ||
    die "Required command not found: curl."
  command -v jq >/dev/null 2>&1 ||
    die "Required command not found: jq."

  SERVER_URL="${SERVER_URL%/}"
  endpoint="${SERVER_URL}/realms/${REALM}/.well-known/openid-configuration"
  deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))

  info "Waiting for trusted Keycloak discovery: ${endpoint}"

  while (( $(date +%s) < deadline )); do
    curl_args=(--fail --silent --show-error --connect-timeout 10 --max-time 20)
    [[ -n "$CA_CERT" ]] && curl_args+=(--cacert "$CA_CERT")

    if discovery="$(curl "${curl_args[@]}" "$endpoint" 2>/dev/null)" &&
       jq -e --arg issuer "${SERVER_URL}/realms/${REALM}" \
         '.issuer == $issuer and (.authorization_endpoint | type == "string") and (.token_endpoint | type == "string")' \
         <<<"$discovery" >/dev/null; then
      info "Trusted Keycloak discovery is ready."
      exit 0
    fi

    sleep "$INTERVAL_SECONDS"
  done

  die "Timed out after ${TIMEOUT_SECONDS}s waiting for trusted Keycloak discovery."
}

main "$@"
