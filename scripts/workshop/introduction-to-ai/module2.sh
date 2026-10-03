#!/usr/bin/env bash
# Verify repository-reconciled Introduction to AI Module 2 workshop material.
#
# The application reconciliation workflow deploys all three ConfigMaps. This
# helper verifies their availability. Participant exposure is controlled only
# through workshop state:
#   - Module 2 activation exposes guided beginner and advanced TODO material;
#   - the organiser separately releases solutions after the workshop.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSHOP_CONTEXT="$SCRIPT_DIR/../lib/workshop-context.sh"
COMMON_HELPER="$SCRIPT_DIR/../../lib/common.sh"

CONFIGMAP_BEGINNER="digitafrica-notebooks-introduction-to-ai-module2-beginner"
CONFIGMAP_ADVANCED="digitafrica-notebooks-introduction-to-ai-module2-advanced"
CONFIGMAP_SOLUTIONS="digitafrica-notebooks-introduction-to-ai-module2-solutions"

NOTEBOOK_BEGINNER="02_foundations_of_ml_beginner.ipynb"
NOTEBOOK_ADVANCED="02_foundations_of_ml_advanced.ipynb"
NOTEBOOK_SOLUTIONS="02_foundations_of_ml_solutions.ipynb"

usage() {
  cat <<'USAGE'
Usage:
  module2.sh status
  module2.sh check --mode beginner|advanced

Actions:
  status  Show whether each internally deployed Module 2 ConfigMap contains
          its expected notebook and show current workshop state.
  check   Verify activation readiness for the selected teaching track.
          Solutions are verified separately by the explicit organiser
          solution-release action.

Run organiser-main.sh reconcile-applications after adding or changing Module 2
material. Application reconciliation deploys all three tracks but does not
expose reference solutions to participants.
USAGE
}

ACTION=""
TRACK=""

while (($#)); do
  case "$1" in
    status|check)
      [[ -z "$ACTION" ]] || {
        printf 'Specify one action only.\n' >&2
        usage >&2
        exit 2
      }
      ACTION="$1"
      shift
      ;;
    --mode)
      [[ "$ACTION" == "check" ]] || {
        printf '%s\n' '--mode is valid only after the check action.' >&2
        usage >&2
        exit 2
      }
      [[ -z "$TRACK" ]] || {
        printf 'Specify one Module 2 mode only.\n' >&2
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

if [[ "$ACTION" == "check" ]]; then
  case "$TRACK" in
    beginner|advanced) ;;
    *)
      printf '%s\n' 'check requires --mode beginner or --mode advanced.' >&2
      usage >&2
      exit 2
      ;;
  esac
elif [[ -n "$TRACK" ]]; then
  printf '%s\n' '--mode is valid only with the check action.' >&2
  usage >&2
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

remote_status_script() {
  printf 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  cat <<'REMOTE_STATUS'
set -euo pipefail

check_track() {
  local track="$1" configmap="$2" notebook_key="$3"
  local notebook

  if ! k3s kubectl -n "$namespace" get configmap "$configmap" >/dev/null 2>&1; then
    printf 'module2_%s_configmap_status=absent\n' "$track"
    return
  fi

  notebook="$(
    k3s kubectl -n "$namespace" get configmap "$configmap" \
      -o jsonpath="{.data.${notebook_key//./\\.}}"
  )"

  if [[ -z "$notebook" ]]; then
    printf 'module2_%s_configmap_status=placeholder\n' "$track"
    return
  fi

  printf 'module2_%s_configmap_status=deployed\n' "$track"
  printf '%s' "$notebook" | sha256sum | awk "{print \"module2_${track}_configmap_sha256=\" \$1}"
}

state_value() {
  local key="$1"

  k3s kubectl -n "$namespace" get configmap digitafrica-workshop-state \
    -o jsonpath="{.data.${key}}" 2>/dev/null || true
}

check_track beginner \
  digitafrica-notebooks-introduction-to-ai-module2-beginner \
  02_foundations_of_ml_beginner.ipynb

check_track advanced \
  digitafrica-notebooks-introduction-to-ai-module2-advanced \
  02_foundations_of_ml_advanced.ipynb

check_track solutions \
  digitafrica-notebooks-introduction-to-ai-module2-solutions \
  02_foundations_of_ml_solutions.ipynb

printf 'workshop_type=%s\n' "$(state_value workshop_type)"
printf 'introduction_to_ai_module=%s\n' "$(state_value introduction_to_ai_module)"
printf 'workshop_mode=%s\n' "$(state_value mode)"
printf 'solutions_released=%s\n' "$(state_value solutions_released)"
REMOTE_STATUS
}

show_status() {
  print_heading "Introduction to AI — Module 2 deployment status"
  run_deployment_remote "$(remote_status_script)"
  cat <<'STATUS_MESSAGE'

Application reconciliation deploys all three tracks as protected ConfigMaps.

Activating Module 2 copies only the organiser-selected Beginner or Advanced
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

  if ! grep -Fq "module2_${track}_configmap_status=deployed" <<<"$status_output"; then
    printf 'NOT deployed: Module 2 %s teaching track\n' "$track" >&2
    printf '%s\n' \
      "Module 2 ${track} activation is not ready." \
      'Run reconcile-applications before assigning Module 2 to participants.' >&2
    exit 1
  fi

  printf '%s\n' \
    "Module 2 ${track} activation readiness passed." \
    'Solutions remain protected until the organiser releases them explicitly.'
}

case "$ACTION" in
  status) show_status ;;
  check)  check_activation_readiness "$TRACK" ;;
esac
