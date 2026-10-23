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
      beginner|intermediate|advanced)
        printf '%s\n' "$CLOUD_COMPUTING_SOA_MODE"
        return 0
        ;;
      *)
        printf '%s\n' \
          'CLOUD_COMPUTING_SOA_MODE must be beginner, intermediate or advanced.' >&2
        return 2
        ;;
    esac
  fi

  [[ -t 0 ]] || {
    printf '%s\n' \
      'Cloud Module 1 activation requires an interactive terminal or CLOUD_COMPUTING_SOA_MODE=beginner|intermediate|advanced.' >&2
    return 2
  }

  while true; do
    printf '\n%s\n\n' "$CLOUD_COMPUTING_SOA_MODULE1_NAME" >&2
    printf '%s\n' \
      '  1) Beginner — guided Flask REST API implementation' \
      '  2) Intermediate — TODO-based Flask REST API implementation' \
      '  3) Advanced — REST API from the specification, no skeleton' >&2
    printf 'Selection: ' >&2
    read -r choice

    case "$choice" in
      1) printf '%s\n' beginner; return 0 ;;
      2) printf '%s\n' intermediate; return 0 ;;
      3) printf '%s\n' advanced; return 0 ;;
      *) printf 'Choose 1, 2 or 3.\n' >&2 ;;
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

check_track intermediate \
  digitafrica-notebooks-cloud-computing-soa-module1-intermediate \
  app.py \
  upstream-participants-guide.md

check_track advanced \
  digitafrica-notebooks-cloud-computing-soa-module1-advanced \
  README.md \
  app.py

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

Application reconciliation deploys beginner, intermediate, advanced,
protected-solution, and shared-test ConfigMaps. Activation copies only the
selected teaching track and shared tests when a participant next spawns a
JupyterHub server.

Reference solution app.py is copied only after an explicit organiser release,
and only for the active intermediate or advanced track.
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
    'It is available only while the Cloud Module 1 intermediate or advanced track is active.'

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
workshop_module="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_module}')"
mode="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

if [ "\$workshop_type" != "cloud-computing-soa" ] ||
  [ "\$workshop_module" != "module1" ] ||
  { [ "\$mode" != "intermediate" ] && [ "\$mode" != "advanced" ]; }; then
  printf '%s\n' \
    'Cloud Module 1 solutions can be released only while its intermediate or advanced track is active.' \
    "Current state: workshop_type=\${workshop_type:-unset}, workshop_module=\${workshop_module:-unset}, mode=\${mode:-unset}" >&2
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
)"

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

# Return beginner, intermediate or advanced on stdout; prompts and errors use stderr.
# CLOUD_COMPUTING_SOA_MODE supports non-interactive mode selection.
cloud_module2_select_mode() {
  local choice

  if [[ -n "${CLOUD_COMPUTING_SOA_MODE:-}" ]]; then
    case "$CLOUD_COMPUTING_SOA_MODE" in
      beginner|intermediate|advanced)
        printf '%s\n' "$CLOUD_COMPUTING_SOA_MODE"
        return 0
        ;;
      *)
        printf '%s\n' \
          'CLOUD_COMPUTING_SOA_MODE must be beginner, intermediate or advanced.' >&2
        return 2
        ;;
    esac
  fi

  [[ -t 0 ]] || {
    printf '%s\n' \
      'Cloud Module 2 activation requires an interactive terminal or CLOUD_COMPUTING_SOA_MODE=beginner|intermediate|advanced.' >&2
    return 2
  }

  while true; do
    printf '\n%s\n\n' "$CLOUD_COMPUTING_SOA_MODULE2_NAME" >&2
    printf '%s\n' \
      '  1) Beginner — complete, explained microservices' \
      '  2) Intermediate — TODO-based microservices' \
      '  3) Advanced — microservices from the specification, no skeleton' >&2
    printf 'Selection: ' >&2
    read -r choice

    case "$choice" in
      1) printf '%s\n' beginner; return 0 ;;
      2) printf '%s\n' intermediate; return 0 ;;
      3) printf '%s\n' advanced; return 0 ;;
      *) printf 'Choose 1, 2 or 3.\n' >&2 ;;
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

check_track intermediate \
  digitafrica-notebooks-cloud-computing-soa-module2-intermediate \
  module2_readme_md \
  module2_requirements_lock \
  module2_gitignore \
  setup_local_keys_sh \
  auth_service_auth_py \
  shortener_service_shortener_py \
  upstream_participants_guide_md

check_track advanced \
  digitafrica-notebooks-cloud-computing-soa-module2-advanced \
  module2_requirements_lock \
  advanced_readme_md \
  auth_service_auth_py \
  shortener_service_shortener_py

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
cloud_module2_show_status() {
  print_heading "$CLOUD_COMPUTING_SOA_MODULE2_NAME deployment status"
  run_deployment_remote "$(cloud_module2_remote_status_script)"
  cat <<'STATUS_MESSAGE'

Application reconciliation deploys beginner, intermediate, advanced,
protected-solution, and shared-test ConfigMaps. Activation copies only the
selected teaching track and shared tests when a participant next spawns a
JupyterHub server.

The reference services are copied only after an explicit organiser release,
and only for the active intermediate or advanced track.
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
# The remote check requires Module 2 with its intermediate or advanced track.
cloud_module2_release_solutions() {
  print_heading "Release $CLOUD_COMPUTING_SOA_MODULE2_NAME solutions"
  printf '%s\n' \
    'This is a one-way organiser action for subsequently spawned participant servers.' \
    'Existing participant servers and files are not modified.' \
    'It is available only while the Cloud Module 2 intermediate or advanced track is active.'

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
workshop_module="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.workshop_module}')"
mode="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  get configmap digitafrica-workshop-state \
  -o jsonpath='{.data.mode}')"

if [ "\$workshop_type" != "cloud-computing-soa" ] ||
  [ "\$workshop_module" != "module2" ] ||
  { [ "\$mode" != "intermediate" ] && [ "\$mode" != "advanced" ]; }; then
  printf '%s\n' \
    'Cloud Module 2 solutions can be released only while its intermediate or advanced track is active.' \
    "Current state: workshop_type=\${workshop_type:-unset}, workshop_module=\${workshop_module:-unset}, mode=\${mode:-unset}" >&2
  exit 1
fi

for key in auth_service_auth_py shortener_service_shortener_py; do
  solution_app="\$(k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
    get configmap digitafrica-notebooks-cloud-computing-soa-module2-solutions \
    -o jsonpath="{.data.\$key}")"
  if [ -z "\$solution_app" ]; then
    printf '%s\n' \
      "Cloud Module 2 solutions ConfigMap does not contain \$key." \
      'Run reconcile-applications before releasing solutions.' >&2
    exit 1
  fi
done

k3s kubectl -n "${DIGITAFRICA_NAMESPACE}" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"solutions_released":"true"}}'

printf '%s\n' 'Cloud Module 2 solutions released for subsequently spawned participant servers.'
REMOTE
)"

  cloud_module2_show_status
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
    *) printf 'Unknown Cloud Computing SOA module: %s\n' "$module" >&2; return 2 ;;
  esac

  while true; do
    workshop_ui_heading "$title"
    workshop_ui_section "VERIFY"
    workshop_ui_option 1 "Check activation readiness"
    workshop_ui_section "ACTIVATE"
    workshop_ui_option 2 "Beginner track"
    workshop_ui_option 3 "Intermediate TODO track"
    workshop_ui_option 4 "Advanced track - from the specification"
    workshop_ui_section "AFTER THE WORKSHOP"
    workshop_ui_option 5 "Release reference solution - intermediate or advanced track"
    workshop_ui_section "INSPECT"
    workshop_ui_option 6 "Show deployment status"
    printf '\n'
    workshop_ui_option 0 "Back to Cloud Computing SOA"
    workshop_ui_prompt
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
        "${prefix}_activate_selected_mode" intermediate ||
          printf 'Module %s intermediate activation did not complete.\n' "$module" >&2
        ;;
      4)
        "${prefix}_activate_selected_mode" advanced ||
          printf 'Module %s advanced activation did not complete.\n' "$module" >&2
        ;;
      5)
        "${prefix}_release_solutions" ||
          printf 'Module %s solution release did not complete.\n' "$module" >&2
        ;;
      6)
        "${prefix}_show_status" ||
          printf 'Module %s deployment status could not be retrieved.\n' "$module" >&2
        ;;
      0) return 0 ;;
      *) printf 'Choose a value from 0 through 6.\n' >&2 ;;
    esac
  done
}

run_cloud_computing_soa_menu() {
  local choice

  while true; do
    workshop_ui_heading "Workshops / Cloud Computing SOA"
    workshop_ui_section "SELECT A MODULE"
    workshop_ui_option 1 "Module 1 - REST API"
    workshop_ui_option 2 "Module 2 - Microservices and JWT Authentication"
    workshop_ui_option 3 "Module 3 - Containerization and Orchestration"
    workshop_ui_note "Teaching-file delivery; exercise runtime NOT VALIDATED."
    workshop_ui_option 5 "Module 5 - OpenFaaS"
    workshop_ui_note "Offline rehearsal only; live readiness NOT VALIDATED."
    printf '\n'
    workshop_ui_option 0 "Back to workshops"
    workshop_ui_prompt
    read -r choice || return 0

    case "$choice" in
      1|2) run_cloud_computing_soa_module_menu "$choice" ;;
      3) run_cloud_module3_menu ;;
      5) run_cloud_module5_menu ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, or 5.\n' >&2 ;;
    esac
  done
}

# Delegate OpenFaaS actions to its module-specific controller.
CLOUD_COMPUTING_SOA_MODULE5_HELPER="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)/openfaas/module-main.sh"

if [[ ! -r "$CLOUD_COMPUTING_SOA_MODULE5_HELPER" ]]; then
  printf 'Missing OpenFaaS module controller: %s\n' \
    "$CLOUD_COMPUTING_SOA_MODULE5_HELPER" >&2
  return 1
fi
# shellcheck source=openfaas/module-main.sh
source "$CLOUD_COMPUTING_SOA_MODULE5_HELPER"

# Delegate Module 3 local preparation to its module-specific controller.
CLOUD_COMPUTING_SOA_MODULE3_HELPER="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)/module3-main.sh"

if [[ ! -r "$CLOUD_COMPUTING_SOA_MODULE3_HELPER" ]]; then
  printf 'Missing Module 3 controller: %s\n' \
    "$CLOUD_COMPUTING_SOA_MODULE3_HELPER" >&2
  return 1
fi
# shellcheck source=module3-main.sh
source "$CLOUD_COMPUTING_SOA_MODULE3_HELPER"
