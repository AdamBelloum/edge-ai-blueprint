#!/usr/bin/env bash
# Password-session functions for direct workshop reset.
# Caller supplies account arguments and owns trap installation.
ADMIN_PASSWORD_SESSION_FILE=""
ADMIN_PASSWORD_SESSION_FILE_OWNED=false
ADMIN_PASSWORD_SESSION_VERIFIED=false

clear_admin_password_session() {
  if [[ "$ADMIN_PASSWORD_SESSION_FILE_OWNED" == true ]] &&
    [[ -n "$ADMIN_PASSWORD_SESSION_FILE" ]]; then
    rm -f -- "$ADMIN_PASSWORD_SESSION_FILE"
    unset KEYCLOAK_ADMIN_PASSWORD_FILE
  fi
  ADMIN_PASSWORD_SESSION_FILE=""
  ADMIN_PASSWORD_SESSION_FILE_OWNED=false
  ADMIN_PASSWORD_SESSION_VERIFIED=false
}

create_admin_password_session() {
  local password

  ADMIN_PASSWORD_SESSION_FILE="$(
    mktemp "${TMPDIR:-/tmp}/digitafrica-keycloak-admin.XXXXXX"
  )" || fail 'Could not create a protected temporary Keycloak password file.'
  ADMIN_PASSWORD_SESSION_FILE_OWNED=true
  chmod 600 "$ADMIN_PASSWORD_SESSION_FILE" ||
    fail 'Could not protect the temporary Keycloak password file.'

  if ! IFS= read -r -s \
    -p "Keycloak administrator password for ${ADMIN_USER} in realm ${ADMIN_REALM:-master}: " \
    password </dev/tty; then
    printf '\n' >&2
    clear_admin_password_session
    fail 'Could not read the Keycloak administrator password.'
  fi
  printf '\n' >&2

  if [[ -z "$password" ]]; then
    clear_admin_password_session
    return 10
  fi

  printf '%s\n' "$password" >"$ADMIN_PASSWORD_SESSION_FILE"
  unset password
  export KEYCLOAK_ADMIN_PASSWORD_FILE="$ADMIN_PASSWORD_SESSION_FILE"
}

ensure_admin_password_session() {
  local attempt status

  [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]] && return 0
  [[ "$ADMIN_PASSWORD_SESSION_VERIFIED" == true ]] && return 0

  if [[ -n "${KEYCLOAK_ADMIN_PASSWORD_FILE:-}" ]] &&
    [[ "$ADMIN_PASSWORD_SESSION_FILE_OWNED" != true ]]; then
    if "$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" --status >/dev/null; then
      ADMIN_PASSWORD_SESSION_VERIFIED=true
      return 0
    else
      status=$?
    fi
    [[ "$status" -eq 10 ]] &&
      fail 'The supplied KEYCLOAK_ADMIN_PASSWORD_FILE was rejected by Keycloak.'
    fail 'Could not validate the supplied Keycloak administrator password file.'
  fi

  for attempt in 1 2 3; do
    if create_admin_password_session; then
      if "$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" --status >/dev/null; then
        ADMIN_PASSWORD_SESSION_VERIFIED=true
        return 0
      else
        status=$?
      fi
    else
      status=$?
    fi

    [[ "$status" -eq 10 ]] ||
      fail 'Could not validate the Keycloak administrator password.'

    clear_admin_password_session
    if (( attempt < 3 )); then
      printf '[WARN] Keycloak authentication failed (%d/3 attempts used). Check the password and try again.\n' \
        "$attempt" >&2
    fi
  done

  fail 'Keycloak authentication failed after 3 attempts; the participant-account operation was not performed.'
}

run_account_helper() {
  local status

  ensure_admin_password_session
  if "$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" "$@"; then
    return 0
  else
    status=$?
  fi
  if [[ "$status" -ne 10 ]] ||
    [[ "$ADMIN_PASSWORD_SESSION_FILE_OWNED" != true ]]; then
    return "$status"
  fi

  printf '[WARN] The cached Keycloak administrator password was rejected; please enter it again.\n' >&2
  clear_admin_password_session
  ensure_admin_password_session
  "$ACCOUNT_HELPER" "${ACCOUNT_ARGS[@]}" "$@"
}
