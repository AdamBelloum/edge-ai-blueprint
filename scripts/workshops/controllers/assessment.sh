#!/usr/bin/env bash
#
# Organiser controller: workshop-independent Assessment menu.
#
# Sourced by scripts/workshops/organizer-main.sh. This controller only renders
# the submenu and delegates to scripts/workshops/assessment/assessment-manager.sh.
# Workshop-specific handling belongs in the manager, not here.
#
# Status:
#   1) Create exam   - implemented via the manager (build_exam.py)
#   2) Publish exam  - implemented (typed review gates, single-host ConfigMap publish)
#   3) Collect submissions - implemented via collect-submissions.sh (read-only fetch)
#   4) Grade exam    - TODO
#   5) Create badge  - TODO

ASSESSMENT_CONTROLLER_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
ASSESSMENT_MANAGER="${ASSESSMENT_CONTROLLER_DIR}/../assessment/assessment-manager.sh"

assessment_controller_run_manager() {
  local action="$1"
  shift

  if [[ ! -r "$ASSESSMENT_MANAGER" ]]; then
    printf 'Assessment manager not found or unreadable: %s\n' \
      "$ASSESSMENT_MANAGER" >&2
    return 1
  fi

  bash "$ASSESSMENT_MANAGER" "$action" "$@"
}

# Run a manager action; report failure without ending the organiser session.
assessment_controller_invoke() {
  local label="$1" action="$2" rc=0

  assessment_controller_run_manager "$action" || rc=$?
  if (( rc != 0 )); then
    printf '%s did not complete (exit code %s).\n' "$label" "$rc" >&2
  fi
  return 0
}

# Publish one reviewed exam notebook for subsequently started participant servers.
# Gates: interactive terminal, safe path/name/size, exactly one inventory host, a
# publishable active workshop, then typed REVIEWED and PUBLISH confirmations.
# The notebook is staged by Ansible copy into a per-run root-only directory (never
# in command arguments), checksum-verified on the host and applied as the
# digitafrica-assessment-exam ConfigMap.
# Exit codes of ..._run: 0 published, 1 error or refusal, 2 cancelled.

# True when the deployment group resolves to exactly one inventory host.
# Resolve the deployment group to exactly one inventory host and print its
# name. The name is re-verified so later calls can target that host directly.
assessment_controller_resolve_host() {
  local listing count host recheck

  listing="$(
    ansible -i "$DIGITAFRICA_INVENTORY" "$DIGITAFRICA_DEPLOYMENT_GROUP" \
      --list-hosts 2>/dev/null
  )" || return 1
  count="$(printf '%s\n' "$listing" | sed -n 's/^ *hosts (\([0-9][0-9]*\)):.*/\1/p')"
  [[ "$count" == "1" ]] || return 1
  host="$(printf '%s\n' "$listing" | sed -n '2p' | tr -d '[:space:]')"
  [[ "$host" =~ ^[A-Za-z0-9_.-]+$ ]] || return 1
  recheck="$(
    ansible -i "$DIGITAFRICA_INVENTORY" "$host" --list-hosts 2>/dev/null
  )" || return 1
  [[ "$(printf '%s\n' "$recheck" | sed -n 's/^ *hosts (\([0-9][0-9]*\)):.*/\1/p')" == "1" ]] || return 1
  [[ "$(printf '%s\n' "$recheck" | sed -n '2p' | tr -d '[:space:]')" == "$host" ]] || return 1
  printf '%s\n' "$host"
}

# Publication is allowed only for an active workshop with no reset in progress.
assessment_controller_state_publishable() {
  local type="$1" module="$2" cleanup="${3:-legacy}"

  case "$type" in
    introduction-to-ai|federated-learning|cloud-computing-soa|big-data|hpc) ;;
    *) return 1 ;;
  esac
  [[ "$module" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || return 1
  [[ "$module" != "none" ]] || return 1
  case "${cleanup:-legacy}" in
    legacy|complete) ;;
    *) return 1 ;;
  esac
}

# Remove only the exact per-run staging file and directory on the host.
# Print the tested stage guard (a separate file) so it can be passed to the host.
assessment_controller_guard_source() {
  local guard_file="${DIGITAFRICA_REPO_ROOT}/scripts/workshops/assessment/stage_guard.py"

  [[ -f "$guard_file" && ! -L "$guard_file" ]] || return 1
  cat -- "$guard_file"
}

# Remove a staging directory only if its creation record (device:inode and
# host identity from this run) is supplied and verified on the host.
assessment_controller_cleanup_stage() {
  local host="$1" stage_name="$2" stage_rec="$3" stage_host_id="$4"
  local guard_source cleanup_script

  if [[ ! "$stage_name" =~ ^digitafrica-exam-[0-9a-f]{32}$ ||
        ! "$stage_rec" =~ ^[0-9]+:[0-9]+$ ||
        ! "$stage_host_id" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'No verified creation record for %s; no cleanup attempted. Inspect it manually.\n' \
      "$stage_name" >&2
    return 1
  fi
  guard_source="$(assessment_controller_guard_source)" || {
    printf 'Stage guard is unavailable; no cleanup attempted for %s.\n' "$stage_name" >&2
    return 1
  }
  printf -v cleanup_script 'guard_py=%q\nstage_name=%q\nstage_dev=%q\nstage_ino=%q\nstage_host=%q\n' \
    "$guard_source" "$stage_name" "${stage_rec%%:*}" "${stage_rec##*:}" "$stage_host_id"
  # shellcheck disable=SC2016
  cleanup_script+='set -eu
python3 -c "$guard_py" remove --name "$stage_name" --dev "$stage_dev" \
  --ino "$stage_ino" --host-id "$stage_host"
'
  if ! ( run_inventory_target_remote "$host" "$cleanup_script" ) >/dev/null; then
    printf 'WARNING: could not verify and remove /var/tmp/%s on %s. Inspect it manually.\n' \
      "$stage_name" "$host" >&2
    return 1
  fi
}

assessment_controller_publish_exam_run() {
  local result_file exam_path notebook_name size_bytes sha256 review typed rc=0
  local state_script state_output active_type active_module active_cleanup
  local stage_id stage_dir stage_script remote_script
  local pinned_host stage_name stage_output stage_rec stage_host_id stage_rc guard_source

  if [[ ! -t 0 ]]; then
    printf 'Publishing requires an interactive terminal. Nothing was published.\n' >&2
    return 1
  fi

  result_file="$(mktemp)" || {
    printf 'Cannot create a temporary result file. Nothing was published.\n' >&2
    return 1
  }
  assessment_controller_run_manager select-exam "$result_file" || rc=$?
  if (( rc != 0 )); then
    rm -f -- "$result_file"
    printf 'No exam selected (exit code %s). Nothing was published.\n' "$rc" >&2
    return 1
  fi
  exam_path="$(cat -- "$result_file")" || {
    rm -f -- "$result_file"
    return 1
  }
  rm -f -- "$result_file"

  if [[ ! "$exam_path" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
    printf 'Exam path has unsupported characters. Nothing was published.\n' >&2
    return 1
  fi
  if [[ ! -f "$exam_path" || -L "$exam_path" ]]; then
    printf 'Selected exam is not a regular file: %s\n' "$exam_path" >&2
    return 1
  fi
  notebook_name="${exam_path##*/}"
  if [[ ! "$notebook_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.ipynb$ ]]; then
    printf 'Unsafe notebook name. Nothing was published: %s\n' "$notebook_name" >&2
    return 1
  fi
  size_bytes="$(wc -c < "$exam_path")" || return 1
  size_bytes="${size_bytes//[[:space:]]/}"
  if [[ ! "$size_bytes" =~ ^[0-9]+$ ]] || (( size_bytes < 1 || size_bytes > 100000 )); then
    printf 'Exam size must be 1-100000 bytes (kubectl apply annotation limit).\n' >&2
    printf 'Nothing was published.\n' >&2
    return 1
  fi
  sha256="$(sha256sum -- "$exam_path")" || return 1
  sha256="${sha256%% *}"
  if [[ ! "$sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Could not compute a valid SHA-256. Nothing was published.\n' >&2
    return 1
  fi

  if ! ( require_ansible_environment && require_command base64 ); then
    printf 'Ansible environment check failed. Nothing was published.\n' >&2
    return 1
  fi
  if ! pinned_host="$(assessment_controller_resolve_host)"; then
    printf 'Group %s must resolve to exactly one host. Nothing was published.\n' \
      "$DIGITAFRICA_DEPLOYMENT_GROUP" >&2
    return 1
  fi

  printf -v state_script 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  state_script+="$(cat <<'REMOTE_STATE'
set -euo pipefail
k3s kubectl -n "$namespace" get configmap digitafrica-workshop-state -o json |
  python3 -c '
import json, sys
data = json.load(sys.stdin).get("data", {})
for key, label in (("workshop_type", "STATE_TYPE"),
                   ("workshop_module", "STATE_MODULE"),
                   ("cleanup_status", "STATE_CLEANUP")):
    value = str(data.get(key, "")).replace("\n", " ").replace("\r", " ")
    print("%s=%s" % (label, value))
'
REMOTE_STATE
)"
  state_output="$(run_inventory_target_remote "$pinned_host" "$state_script")" || {
    printf 'Could not read the active workshop state. Nothing was published.\n' >&2
    return 1
  }
  state_output="$(printf '%s\n' "$state_output" | tr -d '\r')"
  active_type="$(printf '%s\n' "$state_output" | sed -n 's/^STATE_TYPE=//p' | head -n 1)"
  active_module="$(printf '%s\n' "$state_output" | sed -n 's/^STATE_MODULE=//p' | head -n 1)"
  active_cleanup="$(printf '%s\n' "$state_output" | sed -n 's/^STATE_CLEANUP=//p' | head -n 1)"
  active_cleanup="${active_cleanup:-legacy}"
  if ! assessment_controller_state_publishable \
    "$active_type" "$active_module" "$active_cleanup"; then
    printf 'No publishable active workshop (type=%q module=%q cleanup=%q).\n' \
      "$active_type" "$active_module" "$active_cleanup" >&2
    printf 'Nothing was published.\n' >&2
    return 1
  fi

  local exam_type exam_module
  if [[ "$exam_path" =~ /workshop_assets/([^/]+)/([^/]+)/assessment/[^/]+$ ]]; then
    exam_type="${BASH_REMATCH[1]}"
    exam_module="${BASH_REMATCH[2]%%-*}"
  else
    printf 'Exam is not under workshop_assets/<workshop>/<module>/assessment/. Nothing was published.\n' >&2
    return 1
  fi
  if [[ "$exam_type" != "$active_type" || "$exam_module" != "$active_module" ]]; then
    printf '\nWARNING: this exam belongs to %s/%s, but the active workshop is %s/%s.\n' \
      "$exam_type" "$exam_module" "$active_type" "$active_module" >&2
    printf '%s\n' \
      'Participants will receive it in their home folder, but the data or services' \
      'it relies on may not be available in the active workshop.' \
      'Publishing replaces the exam currently offered to every participant.' >&2
    if [[ ! -t 0 ]]; then
      printf 'An interactive terminal is required to publish across workshops. Nothing was published.\n' >&2
      return 2
    fi
    local cross=""
    read -rp 'Type CROSS-PUBLISH to publish this exam anyway: ' cross || cross=""
    if [[ "$cross" != "CROSS-PUBLISH" ]]; then
      log 'Publication cancelled: cross-workshop publication not confirmed.'
      return 2
    fi
  fi

  print_heading "Publish exam to participants"
  printf 'Exam file : %s\nSize      : %s bytes\nSHA-256   : %s\n' \
    "$notebook_name" "$size_bytes" "$sha256"
  printf 'Workshop  : %s / %s\nHost      : %s (group %s)\n' \
    "$active_type" "$active_module" "$pinned_host" "$DIGITAFRICA_DEPLOYMENT_GROUP"
  printf '%s\n' \
    'Participants receive this notebook the next time their server starts.' \
    'Existing participant copies are not replaced or revoked.' \
    'ConfigMap contents are readable by cluster users with access to this namespace.' \
    'Publish only a notebook that contains no answers or expected results.'
  read -rp 'Type REVIEWED to confirm the notebook is answer-free: ' review || review=""
  if [[ "$review" != "REVIEWED" ]]; then
    log 'Publication cancelled: review not confirmed.'
    return 2
  fi
  read -rp "Type PUBLISH to publish to ${active_type}/${active_module}: " typed || typed=""
  if [[ "$typed" != "PUBLISH" ]]; then
    log 'Publication cancelled.'
    return 2
  fi

  stage_id="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  if [[ ! "$stage_id" =~ ^[0-9a-f]{32}$ ]]; then
    printf 'Could not generate a staging identifier. Nothing was published.\n' >&2
    return 1
  fi
  stage_name="digitafrica-exam-${stage_id}"
  stage_dir="/var/tmp/${stage_name}"
  guard_source="$(assessment_controller_guard_source)" || {
    printf 'Stage guard script is unavailable. Nothing was published.\n' >&2
    return 1
  }

  printf -v stage_script 'guard_py=%q\nstage_name=%q\n' "$guard_source" "$stage_name"
  # shellcheck disable=SC2016
  stage_script+='set -eu
python3 -c "$guard_py" create --name "$stage_name"
'
  stage_rc=0
  stage_output="$(run_inventory_target_remote "$pinned_host" "$stage_script")" || stage_rc=$?
  stage_output="$(printf '%s\n' "$stage_output" | tr -d '\r')"
  stage_rec="$(printf '%s\n' "$stage_output" | sed -n 's/^STAGE_ID=//p' | head -n 1)"
  stage_host_id="$(printf '%s\n' "$stage_output" | sed -n 's/^STAGE_HOST=//p' | head -n 1)"
  if [[ ! "$stage_rec" =~ ^[0-9]+:[0-9]+$ || ! "$stage_host_id" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Could not confirm creation of /var/tmp/%s on %s.\n' "$stage_name" "$pinned_host" >&2
    printf 'Nothing was published. No cleanup was attempted because no creation record was received.\n' >&2
    printf 'If the directory exists, inspect it and remove it only if you know this run created it.\n' >&2
    return 1
  fi
  if (( stage_rc != 0 )); then
    printf 'Staging reported an error after a creation record was received. Nothing was published.\n' >&2
    assessment_controller_cleanup_stage "$pinned_host" "$stage_name" "$stage_rec" "$stage_host_id" || true
    return 1
  fi
  if ! ANSIBLE_STDOUT_CALLBACK=default ansible \
    -i "$DIGITAFRICA_INVENTORY" "$pinned_host" -b \
    -m ansible.builtin.copy \
    -a "src=${exam_path} dest=${stage_dir}/exam.ipynb owner=root group=root mode=0600 force=no"
  then
    printf 'Could not stage the exam. Nothing was published.\n' >&2
    assessment_controller_cleanup_stage "$pinned_host" "$stage_name" "$stage_rec" "$stage_host_id" || true
    return 1
  fi

  printf -v remote_script 'namespace=%q\nstage_dir=%q\nexpected_sha=%q\n' \
    "$DIGITAFRICA_NAMESPACE" "$stage_dir" "$sha256"
  printf -v remote_script '%sguard_py=%q\nstage_name=%q\nstage_dev=%q\nstage_ino=%q\nstage_host=%q\n' \
    "$remote_script" "$guard_source" "$stage_name" "${stage_rec%%:*}" "${stage_rec##*:}" "$stage_host_id"
  printf -v remote_script '%snotebook_name=%q\nexpected_type=%q\nexpected_module=%q\n' \
    "$remote_script" "$notebook_name" "$active_type" "$active_module"
  remote_script+="$(cat <<'REMOTE_PUBLISH'
set -euo pipefail
source_file="${stage_dir}/exam.ipynb"
[ "$stage_dir" = "/var/tmp/${stage_name}" ] ||
  { echo 'Unexpected staging path; nothing published.' >&2; exit 1; }
guard() {
  python3 -c "$guard_py" "$1" --name "$stage_name" --dev "$stage_dev" \
    --ino "$stage_ino" --host-id "$stage_host"
}
cleanup_stage() {
  guard remove >/dev/null 2>&1 ||
    echo "WARNING: could not remove ${stage_dir}; inspect it manually." >&2
}
trap cleanup_stage EXIT
guard_output="$(guard check)" ||
  { echo 'Staging directory failed verification; nothing published.' >&2; exit 1; }
actual_sha="$(printf '%s\n' "$guard_output" | sed -n 's/^FILE_SHA256=//p')"
[ "$actual_sha" = "$expected_sha" ] ||
  { echo 'Checksum mismatch on host; nothing published.' >&2; exit 1; }

current="$(k3s kubectl -n "$namespace" get configmap digitafrica-workshop-state -o json |
  python3 -c '
import json, sys
data = json.load(sys.stdin).get("data", {})
print("|".join((data.get("workshop_type", ""),
                data.get("workshop_module", ""),
                data.get("cleanup_status", "") or "legacy")))
')"
IFS='|' read -r current_type current_module current_cleanup <<< "$current"
case "$current_cleanup" in
  legacy|complete) ;;
  *) echo 'Workshop reset in progress; nothing published.' >&2; exit 1 ;;
esac
[ "$current_type" = "$expected_type" ] && [ "$current_module" = "$expected_module" ] ||
  { echo 'Active workshop changed since review; nothing published.' >&2; exit 1; }

k3s kubectl -n "$namespace" create configmap digitafrica-assessment-exam \
  --from-file=exam.ipynb="$source_file" \
  --from-literal=notebook_name="$notebook_name" \
  --from-literal=workshop_type="$expected_type" \
  --from-literal=workshop_module="$expected_module" \
  --dry-run=client -o yaml | k3s kubectl apply -f -

echo "Exam ConfigMap applied for ${expected_type}/${expected_module}."
REMOTE_PUBLISH
)"

  if ! ( run_inventory_target_remote "$pinned_host" "$remote_script" ); then
    printf 'Remote publication failed or its outcome is unknown. Review the output above and check whether ConfigMap digitafrica-assessment-exam exists before retrying.\n' >&2
    assessment_controller_cleanup_stage "$pinned_host" "$stage_name" "$stage_rec" "$stage_host_id" || true
    return 1
  fi
  log 'Exam ConfigMap applied. Participants receive it when a server next starts,'
  log 'provided the JupyterHub configuration that mounts it has been deployed.'
  return 0
}

# Menu entry point: reports the outcome and always returns to the menu.
assessment_controller_publish_exam() {
  local rc=0

  assessment_controller_publish_exam_run || rc=$?
  case "$rc" in
    0) ;;
    2) printf 'Publication cancelled. Nothing was published.\n' ;;
    *) printf 'Publication did not complete (exit code %s). See messages above.\n' \
         "$rc" >&2 ;;
  esac
  return 0
}

# Collect the latest submitted notebook per group from the workers into
# workshop_assets/. The wrapper is interactive and loads its own context.
assessment_controller_collect_submissions() {
  local script="${ASSESSMENT_CONTROLLER_DIR}/../assessment/collect-submissions.sh"
  local rc=0

  if [[ ! -t 0 ]]; then
    printf 'Collecting submissions requires an interactive terminal.\n' >&2
    return 0
  fi
  if [[ ! -r "$script" ]]; then
    printf 'Collect script not found or unreadable: %s\n' "$script" >&2
    return 0
  fi
  bash "$script" || rc=$?
  if (( rc != 0 )); then
    printf 'Collect submissions did not complete (exit code %s). See messages above.\n' \
      "$rc" >&2
  fi
  return 0
}

run_assessment_menu() {
  local choice

  while true; do
    workshop_ui_heading "ASSESSMENT"
    workshop_ui_option 1 "Create exam    (build exam notebook from a question file)"
    workshop_ui_option 2 "Publish exam   (make a reviewed exam available to participants)"
    workshop_ui_option 3 "Collect submissions (fetch latest notebook per group)"
    workshop_ui_option 4 "Grade exam     (TODO)"
    workshop_ui_option 5 "Create badge   (TODO)"
    workshop_ui_option 0 "Back"
    workshop_ui_prompt

    if ! read -r choice; then
      printf '\n'
      return 0
    fi

    case "$choice" in
      1) assessment_controller_invoke "Create exam" generate-menu ;;
      2) assessment_controller_publish_exam ;;
      3) assessment_controller_collect_submissions ;;
      4) printf 'Grade exam is not implemented yet (TODO).\n' ;;
      5) printf 'Create badge is not implemented yet (TODO).\n' ;;
      0) return 0 ;;
      *) printf 'Invalid selection: %s\n' "$choice" >&2 ;;
    esac
  done
}
