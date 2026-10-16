#!/usr/bin/env bash
# Publish and verify Introduction to AI Module 1 workshop material.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSHOP_CONTEXT="$SCRIPT_DIR/../lib/workshop-context.sh"
ORGANIZER_RUNTIME="$SCRIPT_DIR/../lib/organizer-runtime.sh"
COHORT_WORKFLOW="$SCRIPT_DIR/../identity/cohort-workshop.sh"
COMMON_HELPER="$SCRIPT_DIR/../../lib/common.sh"

CONFIGMAP_NAME="digitafrica-introduction-to-ai-module1"
NOTEBOOK_NAME="01_symbolic_ai_tutorial.ipynb"
REMOTE_STAGE_PATH="/tmp/digitafrica-introduction-to-ai-module1.ipynb"

usage() {
  cat <<'USAGE'
Usage:
  module1.sh publish [--yes]
  module1.sh publish-and-activate [--yes] [identity options]
  module1.sh status
  module1.sh check

Actions:
  publish               Validate and publish the reviewed Module 1 notebook.
  publish-and-activate  Verify the participant cohort, publish Module 1, and
                        activate it for subsequently spawned participant servers.
  status                Show whether the Module 1 ConfigMap contains the notebook.
  check                 Verify that Module 1 is ready for first-spawn notebook seeding.

Identity options for publish-and-activate:
  --server-url URL
  --realm NAME
  --admin-user USER
  --admin-realm NAME
  --admin-client-id ID --admin-client-secret-file FILE

The source file and immutable source Git revision must be defined in the active
workshop-release.env as INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE and
INTRODUCTION_TO_AI_MODULE1_SOURCE_REF.

Publishing affects subsequently spawned participant servers only. It never
changes an existing participant notebook, participant identity, FL workspace,
data partition, or Flower server.
USAGE
}

ACTION=""
ASSUME_YES=false

SERVER_URL="${KEYCLOAK_SERVER_URL:-}"
REALM="${KEYCLOAK_REALM:-digitafrica}"
ADMIN_REALM="${KEYCLOAK_ADMIN_REALM:-}"
ADMIN_USER="${KEYCLOAK_ADMIN_USER:-}"
ADMIN_CLIENT_ID="${KEYCLOAK_ADMIN_CLIENT_ID:-}"
ADMIN_CLIENT_SECRET_FILE="${KEYCLOAK_ADMIN_CLIENT_SECRET_FILE:-}"

while (($#)); do
  case "$1" in
    publish|publish-and-activate|status|check)
      [[ -z "$ACTION" ]] || {
        printf 'Specify one action only.\n' >&2
        usage >&2
        exit 2
      }
      ACTION="$1"
      shift
      ;;
    --yes)
      ASSUME_YES=true
      shift
      ;;
    --server-url)
      SERVER_URL="${2:-}"
      shift 2
      ;;
    --realm)
      REALM="${2:-}"
      shift 2
      ;;
    --admin-user)
      ADMIN_USER="${2:-}"
      shift 2
      ;;
    --admin-realm)
      ADMIN_REALM="${2:-}"
      shift 2
      ;;
    --admin-client-id)
      ADMIN_CLIENT_ID="${2:-}"
      shift 2
      ;;
    --admin-client-secret-file)
      ADMIN_CLIENT_SECRET_FILE="${2:-}"
      shift 2
      ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option or action: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "$ACTION" ]] || {
  usage >&2
  exit 2
}

if "$ASSUME_YES" &&
  [[ "$ACTION" != "publish" && "$ACTION" != "publish-and-activate" ]]; then
  printf '%s\n' '--yes is valid only with publish or publish-and-activate.' >&2
  exit 2
fi

if [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]] &&
  [[ -n "$ADMIN_CLIENT_ID" && -n "$ADMIN_CLIENT_SECRET_FILE" ]]; then
  :
elif [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]]; then
  printf '%s\n' \
    'Both --admin-client-id and --admin-client-secret-file are required.' >&2
  exit 2
fi

[[ -r "$WORKSHOP_CONTEXT" ]] || {
  printf 'Missing workshop context helper: %s\n' "$WORKSHOP_CONTEXT" >&2
  exit 2
}
# shellcheck source=../lib/workshop-context.sh
source "$WORKSHOP_CONTEXT"
load_workshop_context

[[ -r "$COMMON_HELPER" ]] || {
  printf 'Missing shared helper: %s\n' "$COMMON_HELPER" >&2
  exit 2
}
# shellcheck source=../../lib/common.sh
source "$COMMON_HELPER"

[[ -r "$ORGANIZER_RUNTIME" ]] || {
  printf 'Missing organiser runtime helper: %s
' "$ORGANIZER_RUNTIME" >&2
  exit 2
}
# shellcheck source=../lib/organizer-runtime.sh
source "$ORGANIZER_RUNTIME"

[[ -x "$COHORT_WORKFLOW" ]] || {
  printf 'Missing executable cohort workflow: %s
' "$COHORT_WORKFLOW" >&2
  exit 2
}

build_cohort_arguments() {
  COHORT_ARGUMENTS=()

  [[ -n "$SERVER_URL" ]] &&
    COHORT_ARGUMENTS+=(--server-url "$SERVER_URL")
  [[ -n "$REALM" ]] &&
    COHORT_ARGUMENTS+=(--realm "$REALM")
  [[ -n "$ADMIN_REALM" ]] &&
    COHORT_ARGUMENTS+=(--admin-realm "$ADMIN_REALM")

  if [[ -n "$ADMIN_CLIENT_ID$ADMIN_CLIENT_SECRET_FILE" ]]; then
    COHORT_ARGUMENTS+=(
      --admin-client-id "$ADMIN_CLIENT_ID"
      --admin-client-secret-file "$ADMIN_CLIENT_SECRET_FILE"
    )
  elif [[ -n "$ADMIN_USER" ]]; then
    COHORT_ARGUMENTS+=(--admin-user "$ADMIN_USER")
  fi
}

require_complete_participant_cohort() {
  build_cohort_arguments
  "$COHORT_WORKFLOW" "${COHORT_ARGUMENTS[@]}" require-complete
}

set_module1_workshop_state() {
  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}"   patch configmap digitafrica-workshop-state   --type merge   -p '{"data":{"workshop_type":"introduction-to-ai","workshop_module":"module1","mode":"beginner","solutions_released":"false"}}'
REMOTE
)"
  printf '%s
'     'Introduction to AI module1 (beginner) is now active for subsequently spawned participant servers.'
}

require_module1_source() {
  : "${INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE:?Workshop release record must define INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE.}"
  : "${INTRODUCTION_TO_AI_MODULE1_SOURCE_REF:?Workshop release record must define INTRODUCTION_TO_AI_MODULE1_SOURCE_REF.}"

  [[ -f "$INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE" ]] ||
    die "Module 1 source notebook is not readable: $INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE"

  [[ "$(basename -- "$INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE")" == "$NOTEBOOK_NAME" ]] ||
    die "Module 1 source file must be named $NOTEBOOK_NAME"

  [[ "$INTRODUCTION_TO_AI_MODULE1_SOURCE_REF" =~ ^[0-9A-Fa-f]{7,64}$ ]] ||
    die 'INTRODUCTION_TO_AI_MODULE1_SOURCE_REF must be an immutable source Git commit SHA.'

  require_command python3
  python3 - "$INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE" <<'PYTHON_VALIDATE'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    notebook = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"Module 1 source is not valid UTF-8 notebook JSON: {exc}")

if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
    raise SystemExit("Module 1 source is not a valid Jupyter notebook structure.")
PYTHON_VALIDATE
}

remote_status_script() {
  printf 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  cat <<'REMOTE_STATUS'
set -euo pipefail

if ! k3s kubectl -n "$namespace" get configmap \
  digitafrica-introduction-to-ai-module1 >/dev/null 2>&1; then
  printf '%s\n' 'module1_configmap_status=absent'
  exit 0
fi

notebook="$(
  k3s kubectl -n "$namespace" get configmap \
    digitafrica-introduction-to-ai-module1 \
    -o jsonpath='{.data.01_symbolic_ai_tutorial\.ipynb}'
)"

if [[ -z "$notebook" ]]; then
  printf '%s\n' 'module1_configmap_status=placeholder'
  exit 0
fi

printf '%s\n' 'module1_configmap_status=published'
printf '%s' "$notebook" | sha256sum | awk '{print "module1_configmap_sha256=" $1}'
REMOTE_STATUS
}

show_status() {
  print_heading "Introduction to AI — Module 1 publication status"
  run_deployment_remote "$(remote_status_script)"
  cat <<'STATUS_MESSAGE'

A published notebook is copied only when a participant next spawns a JupyterHub
server and does not already have:
~/Introduction-to-AI/Module-1/01_symbolic_ai_tutorial.ipynb
STATUS_MESSAGE
}

publish_module1() {
  local source_sha256
  local copy_arguments
  local remote_script

  require_module1_source
  require_command sha256sum
  require_ansible_environment

  source_sha256="$(
    sha256sum "$INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE" | awk '{print $1}'
  )"

  print_heading "Publish Introduction to AI — Module 1"
  printf 'Source notebook : %s\n' "$INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE"
  printf 'Source commit   : %s\n' "$INTRODUCTION_TO_AI_MODULE1_SOURCE_REF"
  printf 'SHA-256         : %s\n' "$source_sha256"
  printf 'ConfigMap       : %s\n' "$CONFIGMAP_NAME"
  printf '%s\n' \
    'This updates material for subsequently spawned participant servers only.' \
    'Existing participant notebooks are preserved.'

  if ! "${ASSUME_YES:-false}" && ! confirm 'Publish this reviewed Module 1 notebook'; then
    log 'No Module 1 publication was performed.'
    return 0
  fi

  copy_arguments="src='$INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE' dest='$REMOTE_STAGE_PATH' owner=root group=root mode=0600"
  ANSIBLE_STDOUT_CALLBACK=default ansible \
    -i "$DIGITAFRICA_INVENTORY" \
    "$DIGITAFRICA_DEPLOYMENT_GROUP" \
    -b \
    -m ansible.builtin.copy \
    -a "$copy_arguments"

  printf -v remote_script 'namespace=%q\nsource_file=%q\n' \
    "$DIGITAFRICA_NAMESPACE" "$REMOTE_STAGE_PATH"
  remote_script+="$(cat <<'REMOTE_PUBLISH'
set -euo pipefail
trap 'rm -f "$source_file"' EXIT

test -s "$source_file"

k3s kubectl -n "$namespace" \
  create configmap digitafrica-introduction-to-ai-module1 \
  --from-file=01_symbolic_ai_tutorial.ipynb="$source_file" \
  --dry-run=client -o yaml | \
  k3s kubectl apply -f -

printf '%s\n' 'Module 1 notebook published successfully.'
REMOTE_PUBLISH
)"

  run_deployment_remote "$remote_script"
  show_status
}

publish_and_activate_module1() {
  require_complete_participant_cohort
  ensure_workshop_activation_allowed introduction-to-ai
  publish_module1
  set_module1_workshop_state
}

case "$ACTION" in
  publish) publish_module1 ;;
  publish-and-activate) publish_and_activate_module1 ;;
  status) show_status ;;
  check)
    status_output="$(show_status)"
    printf '%s\n' "$status_output"
    printf '%s\n' \
      'Readiness condition: status must be published before Module 1 is assigned to participants.' \
      'The administrator must have deployed the JupyterHub Module 1 seed-volume change.'

    if ! grep -Fqx 'module1_configmap_status=published' <<<"$status_output"; then
      printf '%s\n' \
        'Module 1 is not published; do not run or assign Module 1 to participants.' >&2
      exit 1
    fi
    ;;
esac
