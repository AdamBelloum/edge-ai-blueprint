#!/usr/bin/env bash
#
# Cloud Computing SOA organiser workflow.
#
# Sourced by the Cloud Computing SOA controller after organizer-main.sh has
# loaded shared context, common helpers, and organizer-runtime.sh.

CLOUD_COMPUTING_SOA_MODULE1_NAME="Cloud Computing SOA — Module 1: REST API"
CLOUD_COMPUTING_SOA_COHORT_WORKFLOW="${CLOUD_COMPUTING_SOA_COHORT_WORKFLOW:-$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd
)/identity/cohort-workshop.sh}"

cloud_module1_require_complete_participant_cohort() {
  if [[ ! -x "$CLOUD_COMPUTING_SOA_COHORT_WORKFLOW" ]]; then
    printf 'Missing executable participant cohort workflow: %s\n' \
      "$CLOUD_COMPUTING_SOA_COHORT_WORKFLOW" >&2
    return 1
  fi

  "$CLOUD_COMPUTING_SOA_COHORT_WORKFLOW" require-complete
}

cloud_module1_select_mode() {
  local choice

  if [[ -n "${CLOUD_COMPUTING_SOA_MODE:-}" ]]; then
    case "$CLOUD_COMPUTING_SOA_MODE" in
      beginner|advanced)
        printf '%s\n' "$CLOUD_COMPUTING_SOA_MODE"
        return 0
        ;;
      *)
        printf '%s\n' \
          'CLOUD_COMPUTING_SOA_MODE must be either beginner or advanced.' >&2
        return 2
        ;;
    esac
  fi

  [[ -t 0 ]] || {
    printf '%s\n' \
      'Cloud Module 1 activation requires an interactive terminal or CLOUD_COMPUTING_SOA_MODE=beginner|advanced.' >&2
    return 2
  }

  while true; do
    printf '\n%s\n\n' "$CLOUD_COMPUTING_SOA_MODULE1_NAME" >&2
    printf '%s\n' \
      '  1) Beginner — guided Flask REST API implementation' \
      '  2) Advanced — TODO-based Flask REST API implementation' >&2
    printf 'Selection: ' >&2
    read -r choice

    case "$choice" in
      1) printf '%s\n' beginner; return 0 ;;
      2) printf '%s\n' advanced; return 0 ;;
      *) printf 'Choose 1 or 2.\n' >&2 ;;
    esac
  done
}

cloud_module1_remote_status_script() {
  printf 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  cat <<'REMOTE_STATUS'
set -euo pipefail

check_track() {
  local track="$1" configmap="$2"
  local asset_key asset checksum manifest_input=""

  shift 2

  if ! k3s kubectl -n "$namespace" get configmap "$configmap" >/dev/null 2>&1; then
    printf 'cloud_module1_%s_configmap_status=absent\n' "$track"
    return
  fi

  for asset_key in "$@"; do
    asset="$(
      k3s kubectl -n "$namespace" get configmap "$configmap" \
        -o jsonpath="{.data.${asset_key//./\\.}}"
    )"

    if [[ -z "$asset" ]]; then
      printf 'cloud_module1_%s_configmap_status=placeholder\n' "$track"
      printf 'cloud_module1_%s_missing_asset=%s\n' "$track" "$asset_key"
      return
    fi

    checksum="$(printf '%s' "$asset" | sha256sum | awk '{print $1}')"
    manifest_input+="${asset_key}:${checksum}"$'\n'
  done

  printf 'cloud_module1_%s_configmap_status=deployed\n' "$track"
  printf '%s' "$manifest_input" | sha256sum | \
    awk "{print \"cloud_module1_${track}_configmap_sha256=\" \$1}"
}

state_value() {
  local key="$1"

  k3s kubectl -n "$namespace" get configmap digitafrica-workshop-state \
    -o jsonpath="{.data.${key}}" 2>/dev/null || true
}

check_track beginner \
  digitafrica-notebooks-cloud-computing-soa-module1-beginner \
  app.py \
  upstream-participants-guide.md

check_track advanced \
  digitafrica-notebooks-cloud-computing-soa-module1-advanced \
  app.py \
  upstream-participants-guide.md

check_track solutions \
  digitafrica-notebooks-cloud-computing-soa-module1-solutions \
  app.py

check_track tests \
  digitafrica-notebooks-cloud-computing-soa-module1-tests \
  read_from.csv \
  test_api.py

printf 'workshop_type=%s\n' "$(state_value workshop_type)"
printf 'workshop_mode=%s\n' "$(state_value mode)"
printf 'solutions_released=%s\n' "$(state_value solutions_released)"
REMOTE_STATUS
}

cloud_module1_show_status() {
  print_heading "$CLOUD_COMPUTING_SOA_MODULE1_NAME deployment status"
  run_deployment_remote "$(cloud_module1_remote_status_script)"
  cat <<'STATUS_MESSAGE'

Application reconciliation deploys beginner, advanced, protected-solution, and
shared-test ConfigMaps. Activation copies only the selected teaching track and
shared tests when a participant next spawns a JupyterHub server.

Reference solution app.py is copied only after an explicit organiser release,
and only for the active advanced track.
STATUS_MESSAGE
}

cloud_module1_check_activation_readiness() {
  local track="$1"
  local status_output

  status_output="$(cloud_module1_show_status)"
  printf '%s\n' "$status_output"

  if ! grep -Fq "cloud_module1_${track}_configmap_status=deployed" <<<"$status_output" ||
    ! grep -Fq "cloud_module1_tests_configmap_status=deployed" <<<"$status_output"; then
    printf '%s\n' \
      "Cloud Module 1 ${track} activation is not ready." \
      'Run reconcile-applications before assigning Cloud Module 1 to participants.' >&2
    return 1
  fi

  printf '%s\n' \
    "Cloud Module 1 ${track} activation readiness passed." \
    'Shared tests are available; solutions remain protected until explicit release.'
}

cloud_module1_set_workshop_state() {
  local mode="$1"

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"cloud-computing-soa","workshop_module":"module1","mode":"${mode}","solutions_released":"false"}}'
REMOTE
)"
  printf '%s\n' \
    "Cloud Module 1 (${mode}) is now active for subsequently spawned participant servers."
}

cloud_module1_activate_selected_mode() {
  local mode="$1"

  cloud_module1_require_complete_participant_cohort || return $?
  ensure_workshop_activation_allowed cloud-computing-soa || return $?
  cloud_module1_check_activation_readiness "$mode" || return $?
  cloud_module1_set_workshop_state "$mode"
}

cloud_module1_activate() {
  local mode

  mode="$(cloud_module1_select_mode)" || return $?
  cloud_module1_activate_selected_mode "$mode"
}

cloud_module1_release_solutions() {
  print_heading "Release $CLOUD_COMPUTING_SOA_MODULE1_NAME solutions"
  printf '%s\n' \
    'This is a one-way organiser action for subsequently spawned participant servers.' \
    'Existing participant servers and files are not modified.' \
    'It is available only while Cloud Module 1 advanced mode is active.'

  if ! "${ASSUME_YES:-false}" &&
    ! confirm "Release Cloud Module 1 reference solution after the workshop"; then
    log 'No Cloud Module 1 solution release was performed.'
    return 0
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail

workshop_type="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}')"
mode="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

workshop_module="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_module}')"

if [ "\$workshop_type" != "cloud-computing-soa" ] || [ "\$workshop_module" != "module1" ] || [ "\$mode" != "advanced" ]; then
  printf '%s\n' \
    'Cloud Module 1 solutions can be released only while advanced mode is active.' \
    "Current state: workshop_type=\${workshop_type:-unset}, mode=\${mode:-unset}" >&2
  exit 1
fi

solution_app="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-notebooks-cloud-computing-soa-module1-solutions \
  -o jsonpath='{.data.app\.py}')"
if [ -z "\$solution_app" ]; then
  printf '%s\n' \
    'Cloud Module 1 solutions ConfigMap does not contain app.py.' \
    'Run reconcile-applications before releasing solutions.' >&2
  exit 1
fi

k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"solutions_released":"true"}}'

printf '%s\n' 'Cloud Module 1 solutions released for subsequently spawned participant servers.'
REMOTE
)" || return $?

  cloud_module1_show_status
}

CLOUD_COMPUTING_SOA_MODULE2_NAME="Cloud Computing SOA — Module 2: Microservices and JWT Authentication"
CLOUD_COMPUTING_SOA_COHORT_WORKFLOW="${CLOUD_COMPUTING_SOA_COHORT_WORKFLOW:-$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd
)/identity/cohort-workshop.sh}"

# Delegate cohort validation to the shared identity workflow.
# This check does not create participant accounts.
cloud_module2_require_complete_participant_cohort() {
  if [[ ! -x "$CLOUD_COMPUTING_SOA_COHORT_WORKFLOW" ]]; then
    printf 'Missing executable participant cohort workflow: %s\n' \
      "$CLOUD_COMPUTING_SOA_COHORT_WORKFLOW" >&2
    return 1
  fi

  "$CLOUD_COMPUTING_SOA_COHORT_WORKFLOW" require-complete
}

# Return beginner or advanced on stdout; prompts and errors use stderr.
# CLOUD_COMPUTING_SOA_MODE supports non-interactive mode selection.
cloud_module2_select_mode() {
  local choice

  if [[ -n "${CLOUD_COMPUTING_SOA_MODE:-}" ]]; then
    case "$CLOUD_COMPUTING_SOA_MODE" in
      beginner|advanced)
        printf '%s\n' "$CLOUD_COMPUTING_SOA_MODE"
        return 0
        ;;
      *)
        printf '%s\n' \
          'CLOUD_COMPUTING_SOA_MODE must be either beginner or advanced.' >&2
        return 2
        ;;
    esac
  fi

  [[ -t 0 ]] || {
    printf '%s\n' \
      'Cloud Module 2 activation requires an interactive terminal or CLOUD_COMPUTING_SOA_MODE=beginner|advanced.' >&2
    return 2
  }

  while true; do
    printf '\n%s\n\n' "$CLOUD_COMPUTING_SOA_MODULE2_NAME" >&2
    printf '%s\n' \
      '  1) Beginner — guided Flask REST API implementation' \
      '  2) Advanced — TODO-based Flask REST API implementation' >&2
    printf 'Selection: ' >&2
    read -r choice

    case "$choice" in
      1) printf '%s\n' beginner; return 0 ;;
      2) printf '%s\n' advanced; return 0 ;;
      *) printf 'Choose 1 or 2.\n' >&2 ;;
    esac
  done
}

# Generate a remote inspection script; execution is handled by the caller.
# Check listed ConfigMap assets for non-empty content and report checksums.
# These checks do not test service behaviour or compare against local source.
# SOURCE.md is not currently included in the Module 2 asset mappings.
cloud_module2_remote_status_script() {
  printf 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  cat <<'REMOTE_STATUS'
set -euo pipefail

check_track() {
  local track="$1" configmap="$2"
  local asset_key asset checksum manifest_input=""

  shift 2

  if ! k3s kubectl -n "$namespace" get configmap "$configmap" >/dev/null 2>&1; then
    printf 'cloud_module2_%s_configmap_status=absent\n' "$track"
    return
  fi

  for asset_key in "$@"; do
    asset="$(
      k3s kubectl -n "$namespace" get configmap "$configmap" \
        -o jsonpath="{.data.${asset_key//./\\.}}"
    )"

    if [[ -z "$asset" ]]; then
      printf 'cloud_module2_%s_configmap_status=placeholder\n' "$track"
      printf 'cloud_module2_%s_missing_asset=%s\n' "$track" "$asset_key"
      return
    fi

    checksum="$(printf '%s' "$asset" | sha256sum | awk '{print $1}')"
    manifest_input+="${asset_key}:${checksum}"$'\n'
  done

  printf 'cloud_module2_%s_configmap_status=deployed\n' "$track"
  printf '%s' "$manifest_input" | sha256sum | \
    awk "{print \"cloud_module2_${track}_configmap_sha256=\" \$1}"
}

state_value() {
  local key="$1"

  k3s kubectl -n "$namespace" get configmap digitafrica-workshop-state \
    -o jsonpath="{.data.${key}}" 2>/dev/null || true
}

check_track beginner \
  digitafrica-notebooks-cloud-computing-soa-module2-beginner \
  module2_readme_md \
  module2_requirements_lock \
  module2_gitignore \
  setup_local_keys_sh \
  auth_service_auth_py \
  shortener_service_shortener_py \
  upstream_participants_guide_md

check_track advanced \
  digitafrica-notebooks-cloud-computing-soa-module2-advanced \
  module2_readme_md \
  module2_requirements_lock \
  module2_gitignore \
  setup_local_keys_sh \
  auth_service_auth_py \
  shortener_service_shortener_py \
  upstream_participants_guide_md

check_track solutions \
  digitafrica-notebooks-cloud-computing-soa-module2-solutions \
  module2_readme_md \
  module2_requirements_lock \
  module2_gitignore \
  setup_local_keys_sh \
  auth_service_auth_py \
  shortener_service_shortener_py

check_track tests \
  digitafrica-notebooks-cloud-computing-soa-module2-tests \
  read_from_csv \
  test_microservices_py \
  test_ownership_isolation_py

printf 'workshop_type=%s\n' "$(state_value workshop_type)"
printf 'workshop_mode=%s\n' "$(state_value mode)"
printf 'solutions_released=%s\n' "$(state_value solutions_released)"
REMOTE_STATUS
}

# Inspect deployed assets and shared workshop state without changing them.
# The status text below still names app.py; Module 2 uses two service files.
cloud_module2_show_status() {
  print_heading "$CLOUD_COMPUTING_SOA_MODULE2_NAME deployment status"
  run_deployment_remote "$(cloud_module2_remote_status_script)"
  cat <<'STATUS_MESSAGE'

Application reconciliation deploys beginner, advanced, protected-solution, and
shared-test ConfigMaps. Activation copies only the selected teaching track and
shared tests when a participant next spawns a JupyterHub server.

Reference solution app.py is copied only after an explicit organiser release,
and only for the active advanced track.
STATUS_MESSAGE
}

# Require the selected teaching ConfigMap and shared tests to be populated.
# This is asset readiness, not a running-service or participant-access test.
cloud_module2_check_activation_readiness() {
  local track="$1"
  local status_output

  status_output="$(cloud_module2_show_status)"
  printf '%s\n' "$status_output"

  if ! grep -Fq "cloud_module2_${track}_configmap_status=deployed" <<<"$status_output" ||
    ! grep -Fq "cloud_module2_tests_configmap_status=deployed" <<<"$status_output"; then
    printf '%s\n' \
      "Cloud Module 2 ${track} activation is not ready." \
      'Run reconcile-applications before assigning Cloud Module 2 to participants.' >&2
    return 1
  fi

  printf '%s\n' \
    "Cloud Module 2 ${track} activation readiness passed." \
    'Shared tests are available; solutions remain protected until explicit release.'
}

# Select Module 2 and its teaching mode, clearing the solution-release flag.
# The spawn-time seeder consumes this state; this function copies no files
# and does not restart existing participant servers.
cloud_module2_set_workshop_state() {
  local mode="$1"

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"cloud-computing-soa","workshop_module":"module2","mode":"${mode}","solutions_released":"false"}}'
REMOTE
)"
  printf '%s\n' \
    "Cloud Module 2 (${mode}) is now active for subsequently spawned participant servers."
}

# Validate the cohort, shared activation safeguards, and asset readiness
# before changing workshop state. Return immediately on a failed check.
cloud_module2_activate_selected_mode() {
  local mode="$1"

  cloud_module2_require_complete_participant_cohort || return $?
  ensure_workshop_activation_allowed cloud-computing-soa || return $?
  cloud_module2_check_activation_readiness "$mode" || return $?
  cloud_module2_set_workshop_state "$mode"
}

# Select a teaching mode, then delegate to the guarded activation sequence.
cloud_module2_activate() {
  local mode

  mode="$(cloud_module2_select_mode)" || return $?
  cloud_module2_activate_selected_mode "$mode"
}

# After confirmation, set the shared release flag for subsequent spawns.
# The seeder copies reference services into a separate solutions directory.
# Known guard gap: this action checks workshop type and advanced mode,
# but not workshop_module. Verify Module 2 is active before invoking it.
# The asset check below verifies only the reference authentication file.
cloud_module2_release_solutions() {
  print_heading "Release $CLOUD_COMPUTING_SOA_MODULE2_NAME solutions"
  printf '%s\n' \
    'This is a one-way organiser action for subsequently spawned participant servers.' \
    'Existing participant servers and files are not modified.' \
    'It is available only while Cloud Module 2 advanced mode is active.'

  if ! "${ASSUME_YES:-false}" &&
    ! confirm "Release Cloud Module 2 reference solution after the workshop"; then
    log 'No Cloud Module 2 solution release was performed.'
    return 0
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail

workshop_type="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}')"
mode="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

workshop_module="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_module}')"

if [ "\$workshop_type" != "cloud-computing-soa" ] || [ "\$workshop_module" != "module2" ] || [ "\$mode" != "advanced" ]; then
  printf '%s\n' \
    'Cloud Module 2 solutions can be released only while advanced mode is active.' \
    "Current state: workshop_type=\${workshop_type:-unset}, mode=\${mode:-unset}" >&2
  exit 1
fi

solution_app="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-notebooks-cloud-computing-soa-module2-solutions \
  -o jsonpath='{.data.auth_service_auth_py}')"
if [ -z "\$solution_app" ]; then
  printf '%s\n' \
    'Cloud Module 2 solutions ConfigMap does not contain auth_service_auth_py.' \
    'Run reconcile-applications before releasing solutions.' >&2
  exit 1
fi

k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"solutions_released":"true"}}'

printf '%s\n' 'Cloud Module 2 solutions released for subsequently spawned participant servers.'
REMOTE
)" || return $?

  cloud_module2_show_status
}

CLOUD_COMPUTING_SOA_MODULE3_NAME="Cloud Computing SOA — Module 3: Containerization and Orchestration"

cloud_module3_select_mode() {
  local choice

  if [[ -n "${CLOUD_COMPUTING_SOA_MODE:-}" ]]; then
    case "$CLOUD_COMPUTING_SOA_MODE" in
      beginner|advanced)
        printf '%s\n' "$CLOUD_COMPUTING_SOA_MODE"
        return 0
        ;;
      *)
        printf '%s\n' \
          'CLOUD_COMPUTING_SOA_MODE must be either beginner or advanced.' >&2
        return 2
        ;;
    esac
  fi

  [[ -t 0 ]] || {
    printf '%s\n' \
      'Cloud Module 3 mode selection requires an interactive terminal or CLOUD_COMPUTING_SOA_MODE=beginner|advanced.' >&2
    return 2
  }

  while true; do
    printf '\n%s\n\n' "$CLOUD_COMPUTING_SOA_MODULE3_NAME" >&2
    printf '%s\n' \
      '  1) Beginner — guided containerization and orchestration implementation' \
      '  2) Advanced — TODO-based containerization and orchestration implementation' >&2
    printf 'Selection: ' >&2
    read -r choice

    case "$choice" in
      1) printf '%s\n' beginner; return 0 ;;
      2) printf '%s\n' advanced; return 0 ;;
      *) printf 'Choose 1 or 2.\n' >&2 ;;
    esac
  done
}

# Module 3 local menu adapters; no deployment operations.
CLOUD_COMPUTING_SOA_MODULE3_LOCAL_HELPER="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)/module3-local.sh"

cloud_module3_local_check_menu() {
  local mode
  mode="$(cloud_module3_select_mode)" || return $?
  [[ -x "$CLOUD_COMPUTING_SOA_MODULE3_LOCAL_HELPER" ]] || {
    printf '%s\n' 'Missing executable Module 3 local helper.' >&2
    return 1
  }
  "$CLOUD_COMPUTING_SOA_MODULE3_LOCAL_HELPER" check "$mode"
}

cloud_module3_local_export_menu() {
  local mode="$1" destination confirmation
  local -a extra=()
  [[ -x "$CLOUD_COMPUTING_SOA_MODULE3_LOCAL_HELPER" ]] || {
    printf '%s\n' 'Missing executable Module 3 local helper.' >&2
    return 1
  }
  if [[ "$mode" == solutions ]]; then
    printf '%s\n' 'Reference solutions are for organiser-controlled release.'
    printf 'Type RELEASE to authorise solution export (anything else cancels): '
    IFS= read -r confirmation || return 1
    if [[ "$confirmation" != RELEASE ]]; then
      printf '%s\n' 'Solution export cancelled.'
      return 0
    fi
    extra=(--confirm-solutions)
  fi
  printf 'New .tar.gz destination (existing parent directory; blank cancels): '
  IFS= read -r destination || return 1
  if [[ -z "$destination" ]]; then
    printf '%s\n' 'Export cancelled.'
    return 0
  fi
  "$CLOUD_COMPUTING_SOA_MODULE3_LOCAL_HELPER" export \
    "$mode" "$destination" "${extra[@]}"
}

cloud_module3_local_information() {
  printf '%s\n' \
    'Module 3 is a standalone containerization/orchestration practical.' \
    'Local checks validate mapped files and Python/Bash syntax only.' \
    'Exports include one track plus shared tests, not generated keys.' \
    'Beginner and advanced entry guides are included; detailed practical guidance and runtime validation remain pending.' \
    'These menu actions do not change workshop state or participant servers.' \
    'The organiser menu still loads platform context; direct local actions bypass it:' \
    '  bash scripts/workshops/organizer-main.sh cloud-module3-local-check beginner' \
    '  bash scripts/workshops/organizer-main.sh cloud-module3-local-export beginner /tmp/module3-beginner.tar.gz'
}

# Platform delivery checks; standalone local helpers remain available.
cloud_module3_remote_status_script() {
  local map_file
  map_file="${CLOUD_COMPUTING_SOA_MODULE3_LOCAL_HELPER%/*}/../../../workshop_assets/cloud_computing_soa/module3_containerization_orchestration/asset-map.tsv"
  [[ -f "$map_file" ]] || {
    printf 'Missing Module 3 asset map: %s\n' "$map_file" >&2
    return 1
  }

  printf 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  printf 'expected_map=%q\n' "$(cat "$map_file")"
  cat <<'REMOTE_STATUS'
set -euo pipefail
python3 - "$namespace" "$expected_map" <<'PY_STATUS'
import csv
import io
import json
import subprocess
import sys

namespace, expected_map = sys.argv[1:]
rows = list(csv.reader(io.StringIO(expected_map), delimiter="\t"))

for track in ("beginner", "advanced", "solutions", "tests"):
    name = f"digitafrica-notebooks-cloud-computing-soa-module3-{track}"
    result = subprocess.run(
        ["k3s", "kubectl", "-n", namespace,
         "get", "configmap", name, "-o", "json"],
        capture_output=True, text=True,
    )
    prefix = f"cloud_module3_{track}"
    if result.returncode:
        print(f"{prefix}_configmap_status=unavailable")
        print(result.stderr.strip(), file=sys.stderr)
        continue

    data = json.loads(result.stdout).get("data", {})
    required = [row[1] for row in rows if row[0] == track]
    missing = [key for key in required if key not in data]
    actual_map = data.get("asset_map_tsv", "").rstrip("\r\n")
    map_matches = actual_map == expected_map.rstrip("\r\n")
    ready = bool(required) and not missing and map_matches

    print(f"{prefix}_configmap_status={'deployed' if ready else 'incomplete'}")
    print(f"{prefix}_mapped_asset_count={len(required)}")
    if missing:
        print(f"{prefix}_missing_keys={','.join(missing)}")
    if not map_matches:
        print(f"{prefix}_asset_map_status=mismatch")

result = subprocess.run(
    ["k3s", "kubectl", "-n", namespace,
     "get", "configmap", "digitafrica-workshop-state", "-o", "json"],
    capture_output=True, text=True,
)
if result.returncode:
    print(result.stderr.strip(), file=sys.stderr)
    sys.exit(result.returncode)
state = json.loads(result.stdout).get("data", {})
for key in ("workshop_type", "workshop_module", "mode", "solutions_released"):
    print(f"{key}={state.get(key, 'unset')}")
PY_STATUS
REMOTE_STATUS
}

cloud_module3_show_status() {
  local remote_script
  remote_script="$(cloud_module3_remote_status_script)" || return $?
  run_deployment_remote "$remote_script"
}

cloud_module3_check_activation_readiness() {
  local mode="$1" status_output

  case "$mode" in
    beginner|advanced) ;;
    *) printf 'Module 3 requires beginner or advanced mode.\n' >&2; return 2 ;;
  esac

  status_output="$(cloud_module3_show_status)" || return $?
  printf '%s\n' "$status_output"

  if ! grep -Fxq "cloud_module3_${mode}_configmap_status=deployed" <<<"$status_output" ||
     ! grep -Fxq "cloud_module3_tests_configmap_status=deployed" <<<"$status_output"; then
    printf '%s\n' \
      'Module 3 activation is not ready.' \
      'Reconcile applications before activating Module 3.' >&2
    return 1
  fi

  printf '%s\n' \
    "Module 3 ${mode} file-delivery readiness passed." \
    'Containers and services are not validated by this check.'
}

cloud_module3_activate_selected_mode() {
  local mode="$1"

  case "$mode" in
    beginner|advanced) ;;
    *) printf 'Module 3 requires beginner or advanced mode.\n' >&2; return 2 ;;
  esac

  cloud_module2_require_complete_participant_cohort || return $?
  ensure_workshop_activation_allowed cloud-computing-soa || return $?
  cloud_module3_check_activation_readiness "$mode" || return $?

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"cloud-computing-soa","workshop_module":"module3","mode":"${mode}","solutions_released":"false"}}'
REMOTE
)" || return $?

  printf '%s\n' \
    "Cloud Module 3 (${mode}) is active for subsequently spawned participant servers." \
    'Existing servers and participant files are not modified.'
}

cloud_module3_activate() {
  local mode
  mode="$(cloud_module3_select_mode)" || return $?
  cloud_module3_activate_selected_mode "$mode"
}

cloud_module3_release_solutions() {
  local status_output

  print_heading "Release $CLOUD_COMPUTING_SOA_MODULE3_NAME solutions"
  printf '%s\n' \
    'Solutions will be copied only on subsequent participant server spawns.' \
    'Existing servers are not modified; previously delivered solutions are not revoked.' \
    'Release requires Cloud Module 3 advanced mode to be active.'

  if ! "${ASSUME_YES:-false}" &&
     ! confirm "Release Cloud Module 3 reference solutions after the workshop"; then
    printf '%s\n' 'No Module 3 solution release was performed.'
    return 0
  fi

  status_output="$(cloud_module3_show_status)" || return $?
  printf '%s\n' "$status_output"
  if ! grep -Fxq 'cloud_module3_solutions_configmap_status=deployed' <<<"$status_output"; then
    printf '%s\n' \
      'Module 3 solution assets are not ready.' \
      'Reconcile applications before releasing solutions.' >&2
    return 1
  fi

  run_deployment_remote "$(cat <<REMOTE
set -euo pipefail
namespace="${DIGITAFRICA_NAMESPACE}"

workshop_type="\$(k3s kubectl -n "\$namespace" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_type}')"
workshop_module="\$(k3s kubectl -n "\$namespace" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_module}')"
mode="\$(k3s kubectl -n "\$namespace" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

if [ "\$workshop_type" != "cloud-computing-soa" ] ||
   [ "\$workshop_module" != "module3" ] ||
   [ "\$mode" != "advanced" ]; then
  printf '%s\n' \
    'Module 3 solutions can be released only while Cloud Module 3 advanced mode is active.' >&2
  exit 1
fi

k3s kubectl -n "\$namespace" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"solutions_released":"true"}}'
REMOTE
)" || return $?

  cloud_module3_show_status
}

# Select actions for one module while reusing its existing operational handlers.
run_cloud_computing_soa_module_menu() {
  local module="$1"
  local title prefix choice mode

  case "$module" in
    1)
      title="$CLOUD_COMPUTING_SOA_MODULE1_NAME"
      prefix=cloud_module1
      ;;
    2)
      title="$CLOUD_COMPUTING_SOA_MODULE2_NAME"
      prefix=cloud_module2
      ;;
    3)
      title="$CLOUD_COMPUTING_SOA_MODULE3_NAME"
      prefix=cloud_module3
      ;;
    *) printf 'Unknown Cloud Computing SOA module: %s\n' "$module" >&2; return 2 ;;
  esac

  while true; do
    printf '\n%s\n\n' "$title"
    printf '%s\n' \
      '  1) Check activation readiness' \
      '  2) Activate beginner track' \
      '  3) Activate advanced TODO track' \
      '  4) Release advanced reference solution' \
      '  5) Show deployment status'
    if [[ "$module" == 3 ]]; then
      printf '%s\n' \
        '  6) Validate local assets' \
        '  7) Export beginner bundle' \
        '  8) Export advanced TODO bundle' \
        '  9) Export reference solutions (confirmation required)' \
        ' 10) Local workflow information'
    fi
    printf '%s\n' '  0) Back to modules'
    printf '\nSelection: '
    read -r choice || return 0

    case "$choice" in
      1)
        if mode="$("${prefix}_select_mode")"; then
          "${prefix}_check_activation_readiness" "$mode" ||
            printf 'Module %s readiness check did not pass.\n' "$module" >&2
        else
          printf 'Module %s mode selection did not complete.\n' "$module" >&2
        fi
        ;;
      2)
        "${prefix}_activate_selected_mode" beginner ||
          printf 'Module %s beginner activation did not complete.\n' "$module" >&2
        ;;
      3)
        "${prefix}_activate_selected_mode" advanced ||
          printf 'Module %s advanced activation did not complete.\n' "$module" >&2
        ;;
      4)
        "${prefix}_release_solutions" ||
          printf 'Module %s solution release did not complete.\n' "$module" >&2
        ;;
      5)
        "${prefix}_show_status" ||
          printf 'Module %s deployment status could not be retrieved.\n' "$module" >&2
        ;;
      6|7|8|9|10)
        if [[ "$module" != 3 ]]; then
          printf 'Choose a value from 0 through 5.\n' >&2
          continue
        fi
        case "$choice" in
          6) cloud_module3_local_check_menu ||
               printf 'Module 3 local validation did not complete successfully.\n' >&2 ;;
          7) cloud_module3_local_export_menu beginner ||
               printf 'Module 3 beginner export failed.\n' >&2 ;;
          8) cloud_module3_local_export_menu advanced ||
               printf 'Module 3 advanced export failed.\n' >&2 ;;
          9) cloud_module3_local_export_menu solutions ||
               printf 'Module 3 solution export failed.\n' >&2 ;;
          10) cloud_module3_local_information ;;
        esac
        ;;
      0) return 0 ;;
      *)
        if [[ "$module" == 3 ]]; then
          printf 'Choose a value from 0 through 10.\n' >&2
        else
          printf 'Choose a value from 0 through 5.\n' >&2
        fi
        ;;
    esac
  done
}

run_cloud_computing_soa_menu() {
  local choice

  while true; do
    printf '\nCloud Computing SOA modules\n\n'
    printf '%s\n' \
      '  1) Module 1 — REST API' \
      '  2) Module 2 — Microservices and JWT Authentication' \
      '  3) Module 3 — Containerization and Orchestration' \
      '  0) Back to workshops'
    printf '\nSelection: '
    read -r choice || return 0

    case "$choice" in
      1|2|3) run_cloud_computing_soa_module_menu "$choice" ;;
      0) return 0 ;;
      *) printf 'Choose a value from 0 through 3.\n' >&2 ;;
    esac
  done
}
