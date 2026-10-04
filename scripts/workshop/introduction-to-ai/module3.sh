#!/usr/bin/env bash
# Verify repository-reconciled Introduction to AI Module 3 workshop material.
#
# The application reconciliation workflow deploys all three ConfigMaps. This
# helper verifies their availability. Participant exposure is controlled only
# through workshop state:
#   - Module 3 activation exposes guided beginner and advanced TODO material;
#   - the organiser separately releases solutions after the workshop.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSHOP_CONTEXT="$SCRIPT_DIR/../lib/workshop-context.sh"
ORGANIZER_RUNTIME="$SCRIPT_DIR/../lib/organizer-runtime.sh"
COHORT_WORKFLOW="$SCRIPT_DIR/../identity/cohort-workshop.sh"
COMMON_HELPER="$SCRIPT_DIR/../../lib/common.sh"

CONFIGMAP_BEGINNER="digitafrica-notebooks-introduction-to-ai-module3-beginner"
CONFIGMAP_ADVANCED="digitafrica-notebooks-introduction-to-ai-module3-advanced"
CONFIGMAP_SOLUTIONS="digitafrica-notebooks-introduction-to-ai-module3-solutions"

NOTEBOOK_BEGINNER="01_from_features_to_neural_networks_beginner.ipynb"
NOTEBOOK_ADVANCED="01_from_features_to_neural_networks_advanced.ipynb"
NOTEBOOK_SOLUTIONS="01_from_features_to_neural_networks_solutions.ipynb"

usage() {
  cat <<'USAGE'
Usage:
  module3.sh status
  module3.sh check --mode beginner|advanced
  module3.sh activate [--mode beginner|advanced] [identity options]
  module3.sh release-solutions [--yes]

Actions:
  status             Show each Module 3 ConfigMap and current workshop state.
  check              Verify activation readiness for the selected teaching track.
  activate           Verify the cohort and selected track, then activate Module 3
                     for subsequently spawned participant servers. If --mode is
                     omitted, select a track interactively or set
                     INTRODUCTION_TO_AI_MODE=beginner|advanced.
  release-solutions  One-way release of advanced-track reference solutions for
                     subsequently spawned participant servers only.

Identity options for activate:
  --server-url URL
  --realm NAME
  --admin-user USER
  --admin-realm NAME
  --admin-client-id ID --admin-client-secret-file FILE

Run organiser-main.sh reconcile-applications after adding or changing Module 3
material. Application reconciliation deploys all three tracks but does not
expose reference solutions to participants.
USAGE
}

ACTION=""
TRACK=""
ASSUME_YES=false

SERVER_URL="${KEYCLOAK_SERVER_URL:-}"
REALM="${KEYCLOAK_REALM:-digitafrica}"
ADMIN_REALM="${KEYCLOAK_ADMIN_REALM:-}"
ADMIN_USER="${KEYCLOAK_ADMIN_USER:-}"
ADMIN_CLIENT_ID="${KEYCLOAK_ADMIN_CLIENT_ID:-}"
ADMIN_CLIENT_SECRET_FILE="${KEYCLOAK_ADMIN_CLIENT_SECRET_FILE:-}"

while (($#)); do
  case "$1" in
    status|check|activate|release-solutions)
      [[ -z "$ACTION" ]] || {
        printf 'Specify one action only.\n' >&2
        usage >&2
        exit 2
      }
      ACTION="$1"
      shift
      ;;
    --mode)
      [[ "$ACTION" == "check" || "$ACTION" == "activate" ]] || {
        printf '%s\n' '--mode is valid only after check or activate.' >&2
        usage >&2
        exit 2
      }
      [[ -z "$TRACK" ]] || {
        printf 'Specify one Module 3 mode only.\n' >&2
        usage >&2
        exit 2
      }
      [[ $# -ge 2 ]] || {
        printf '%s\n' '--mode requires beginner or advanced.' >&2
        usage >&2
        exit 2
      }
      TRACK="$2"
      shift 2
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

case "$TRACK" in
  ""|beginner|advanced) ;;
  *)
    printf '%s\n' '--mode requires beginner or advanced.' >&2
    usage >&2
    exit 2
    ;;
esac

if [[ "$ACTION" == "check" && -z "$TRACK" ]]; then
  printf '%s\n' 'check requires --mode beginner or --mode advanced.' >&2
  usage >&2
  exit 2
fi

if "$ASSUME_YES" && [[ "$ACTION" != "release-solutions" ]]; then
  printf '%s\n' '--yes is valid only with release-solutions.' >&2
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

select_module3_mode() {
  local choice

  if [[ -n "$TRACK" ]]; then
    printf '%s
' "$TRACK"
    return 0
  fi

  if [[ -n "${INTRODUCTION_TO_AI_MODE:-}" ]]; then
    case "$INTRODUCTION_TO_AI_MODE" in
      beginner|advanced)
        printf '%s
' "$INTRODUCTION_TO_AI_MODE"
        return 0
        ;;
      *)
        printf '%s
'           'INTRODUCTION_TO_AI_MODE must be either beginner or advanced.' >&2
        return 2
        ;;
    esac
  fi

  [[ -t 0 ]] || {
    printf '%s
'       'Module 3 activation requires an interactive terminal or --mode beginner|advanced.' >&2
    return 2
  }

  while true; do
    printf '
Introduction to AI — Module 3 track

' >&2
    printf '  1) Beginner — guided hands-on notebook
' >&2
    printf '  2) Advanced — TODO-based notebook
' >&2
    printf 'Selection: ' >&2
    read -r choice

    case "$choice" in
      1) printf '%s
' beginner; return 0 ;;
      2) printf '%s
' advanced; return 0 ;;
      *) printf 'Choose 1 or 2.
' >&2 ;;
    esac
  done
}

set_module3_workshop_state() {
  local mode="$1"

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}"   patch configmap digitafrica-workshop-state   --type merge   -p '{"data":{"workshop_type":"introduction-to-ai","introduction_to_ai_module":"module3","mode":"${mode}","solutions_released":"false"}}'
REMOTE
)"
  printf '%s
'     "Introduction to AI module3 (${mode}) is now active for subsequently spawned participant servers."
}

remote_status_script() {
  printf 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  cat <<'REMOTE_STATUS'
set -euo pipefail

check_track() {
  local track="$1" configmap="$2"
  local asset_key asset checksum manifest_input=""

  shift 2

  if ! k3s kubectl -n "$namespace" get configmap "$configmap" >/dev/null 2>&1; then
    printf 'module3_%s_configmap_status=absent\n' "$track"
    return
  fi

  for asset_key in "$@"; do
    asset="$(
      k3s kubectl -n "$namespace" get configmap "$configmap" \
        -o jsonpath="{.data.${asset_key//./\\.}}"
    )"

    if [[ -z "$asset" ]]; then
      printf 'module3_%s_configmap_status=placeholder\n' "$track"
      printf 'module3_%s_missing_asset=%s\n' "$track" "$asset_key"
      return
    fi

    checksum="$(printf '%s' "$asset" | sha256sum | awk '{print $1}')"
    manifest_input+="${asset_key}:${checksum}"$'\n'
  done

  printf 'module3_%s_configmap_status=deployed\n' "$track"
  printf '%s' "$manifest_input" | sha256sum | \
    awk "{print \"module3_${track}_configmap_sha256=\" \$1}"
}

state_value() {
  local key="$1"

  k3s kubectl -n "$namespace" get configmap digitafrica-workshop-state \
    -o jsonpath="{.data.${key}}" 2>/dev/null || true
}

check_track beginner \
  digitafrica-notebooks-introduction-to-ai-module3-beginner \
  00_START_HERE.md \
  01_from_features_to_neural_networks_beginner.ipynb \
  02_training_generalisation_and_architectures_beginner.ipynb

check_track advanced \
  digitafrica-notebooks-introduction-to-ai-module3-advanced \
  00_START_HERE.md \
  01_from_features_to_neural_networks_advanced.ipynb \
  02_training_generalisation_and_architectures_advanced.ipynb

check_track solutions \
  digitafrica-notebooks-introduction-to-ai-module3-solutions \
  00_START_HERE.md \
  01_from_features_to_neural_networks_solutions.ipynb \
  02_training_generalisation_and_architectures_solutions.ipynb

printf 'workshop_type=%s\n' "$(state_value workshop_type)"
printf 'introduction_to_ai_module=%s\n' "$(state_value introduction_to_ai_module)"
printf 'workshop_mode=%s\n' "$(state_value mode)"
printf 'solutions_released=%s\n' "$(state_value solutions_released)"
REMOTE_STATUS
}

show_status() {
  print_heading "Introduction to AI — Module 3 deployment status"
  run_deployment_remote "$(remote_status_script)"
  cat <<'STATUS_MESSAGE'

Application reconciliation deploys all three tracks as protected ConfigMaps.

Activating Module 3 copies only the organiser-selected Beginner or Advanced
TODO notebook when a participant next spawns a JupyterHub server and does not
already have the relevant file under:
  ~/Introduction-to-AI/Module-2/

Reference solutions are copied only after the organiser explicitly releases
them after the workshop.
STATUS_MESSAGE
}

check_activation_readiness() {
  local track="$1"
  local status_output

  status_output="$(show_status)"
  printf '%s\n' "$status_output"

  if ! grep -Fq "module3_${track}_configmap_status=deployed" <<<"$status_output"; then
    printf 'NOT deployed: Module 3 %s teaching track\n' "$track" >&2
    printf '%s\n' \
      "Module 3 ${track} activation is not ready." \
      'Run reconcile-applications before assigning Module 3 to participants.' >&2
    exit 1
  fi

  printf '%s\n' \
    "Module 3 ${track} activation readiness passed." \
    'Solutions remain protected until the organiser releases them explicitly.'
}

activate_module3() {
  local mode

  mode="$(select_module3_mode)"
  require_complete_participant_cohort
  ensure_workshop_activation_allowed introduction-to-ai
  check_activation_readiness "$mode"
  set_module3_workshop_state "$mode"
}

release_module3_solutions() {
  print_heading "Release Introduction to AI — Module 3 solutions"
  printf '%s\n' \
    'This is a one-way organiser action for subsequently spawned participant servers.' \
    'Existing participant servers and notebooks are not modified.' \
    'It is available only while Introduction to AI Module 3 advanced mode is active.'

  if ! "$ASSUME_YES" &&
    ! confirm "Release Module 3 reference solutions after the workshop"; then
    log 'No Module 3 solution release was performed.'
    return 0
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail

workshop_type="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}')"
module="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.introduction_to_ai_module}')"
mode="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

if [ "\$workshop_type" != "introduction-to-ai" ] || \
  [ "\$module" != "module3" ] || \
  [ "\$mode" != "advanced" ]; then
  printf '%s\n' \
    'Module 3 solutions can be released only while Introduction to AI Module 3 advanced mode is active.' \
    "Current state: workshop_type=\${workshop_type:-unset}, module=\${module:-unset}, mode=\${mode:-unset}" >&2
  exit 1
fi

solution_notebook="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-notebooks-introduction-to-ai-module3-solutions \
  -o jsonpath='{.data.02_foundations_of_ml_solutions\.ipynb}')"
if [ -z "\$solution_notebook" ]; then
  printf '%s\n' \
    'Module 3 solutions ConfigMap does not contain the expected notebook.' \
    'Run reconcile-applications before releasing solutions.' >&2
  exit 1
fi

k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"solutions_released":"true"}}'

printf '%s\n' 'Module 3 solutions released for subsequently spawned participant servers.'
REMOTE
)"

  show_status
}

case "$ACTION" in
  status) show_status ;;
  check) check_activation_readiness "$TRACK" ;;
  activate) activate_module3 ;;
  release-solutions) release_module3_solutions ;;
esac
