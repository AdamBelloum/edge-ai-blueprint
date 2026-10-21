#!/usr/bin/env bash
# Sourced OpenFaaS controller. Pre-live actions have no deployment side effects.

CLOUD_MODULE5_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_MODULE5_ROOT="$(cd -- "$CLOUD_MODULE5_DIR/../../../.." && pwd)"
CLOUD_MODULE5_ASSETS="$CLOUD_MODULE5_ROOT/workshop_assets/cloud-computing-soa/module5-openfaas"

cloud_module5_status() {
  printf '%s\n' \
    'Cloud Computing SOA — Module 5: OpenFaaS' \
    'State: pre-live authoring; not ready for participant delivery.' \
    'Live build, push, deploy, monitoring and isolation remain unvalidated.' \
    'No infrastructure or active workshop state was inspected or modified.'
}

cloud_module5_check() {
  local checker="$CLOUD_MODULE5_ASSETS/tests/check-prelive.py"
  if [[ ! -r "$checker" ]]; then
    printf 'ERROR: Pre-live checker is not yet staged: %s\n' "$checker" >&2
    return 1
  fi
  command -v python3 >/dev/null 2>&1 || {
    printf 'ERROR: python3 is required for local checks.\n' >&2
    return 2
  }
  python3 "$checker"
}

cloud_module5_publish() {
  printf '%s\n' \
    'BLOCKED: OpenFaaS publication is unavailable before live validation.' \
    'Resolve edition approval, builder/registry access and reference-lab gates first.' \
    'No workshop selection, reconciliation or deployment was performed.' >&2
  return 2
}

# Test-cohort preparation only; does not change active workshop state.
cloud_module5_prepare_rehearsal() {
  local helper
  for helper in cloud_module1_require_complete_participant_cohort \
                ensure_workshop_activation_allowed confirm; do
    declare -F "$helper" >/dev/null || {
      printf 'ERROR: Rehearsal preparation requires the organiser workflow (%s).\n' "$helper" >&2
      return 2
    }
  done

  cloud_module5_check || return $?
  cloud_module1_require_complete_participant_cohort || return $?
  ensure_workshop_activation_allowed cloud-computing-soa || return $?

  printf '%s\n' \
    'Private test-cohort rehearsal of unvalidated OpenFaaS drafts.' \
    'This stages notebook assets and upgrades JupyterHub configuration.' \
    'Active workshop state is unchanged; no OpenFaaS runtime is installed.' \
    'Live notebook paths remain disabled by default, not network-sandboxed.' \
    'Real workshop publication remains blocked pending clarification and validation.'

  if ! confirm "Prepare OpenFaaS draft assets for the private test cohort"; then
    printf 'No rehearsal preparation was performed.\n'
    return 0
  fi

  bash "$CLOUD_MODULE5_ROOT/scripts/workshops/reconcile-workshop-applications.sh" \
    --enable-openfaas-offline-rehearsal || return $?

  printf '%s\n' \
    'Offline rehearsal assets reconciled; Module 5 is not yet active.' \
    'Participant delivery and browser behaviour remain to be tested.'
}

# Verify deployed offline delivery, not live OpenFaaS readiness.
cloud_module5_check_rehearsal_readiness() {
  declare -F run_deployment_remote >/dev/null || {
    printf 'ERROR: Readiness checks require the organiser workflow.\n' >&2
    return 2
  }
  [[ -n "${DIGITAFRICA_NAMESPACE:-}" ]] || {
    printf 'ERROR: Deployment namespace is unset.\n' >&2
    return 2
  }

  local remote_script
  printf -v remote_script 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  remote_script+="$(cat <<'REMOTE'
set -euo pipefail
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

python3 - "$namespace" <<'CHECK'
import json
import subprocess
import sys

namespace = sys.argv[1]
name = "digitafrica-notebooks-cloud-computing-soa-module5-beginner"
mount_path = "/seed/cloud-computing-soa/module5"

def load(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        # Do not print Helm values or potentially sensitive command output.
        raise SystemExit("ERROR: Cannot retrieve deployed rehearsal configuration.")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise SystemExit("ERROR: Invalid deployed configuration response.")

def require(condition, message):
    if not condition:
        raise SystemExit("ERROR: " + message)

assets = load(["k3s", "kubectl", "-n", namespace,
               "get", "configmap", name, "-o", "json"])
data = assets.get("data", {})
keys = ["asset_%03d" % index for index in range(1, 21)]
require(all(data.get(key) for key in keys), "Module 5 assets are incomplete.")
try:
    lab = json.loads(data["asset_009"])
except ValueError:
    raise SystemExit("ERROR: Invalid offline lab template.")
require(lab.get("live_test_enabled") is False,
        "Module 5 template does not disable live execution.")

values = load(["helm", "-n", namespace, "get", "values", "jhub", "-o", "json"])
singleuser = values.get("singleuser", {})

def dictionaries(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from dictionaries(child)
    elif isinstance(value, list):
        for child in value:
            yield from dictionaries(child)

volumes = [
    item for item in dictionaries(singleuser)
    if item.get("configMap", {}).get("name") == name
]
require(len(volumes) == 1, "Module 5 seed volume is absent or ambiguous.")
volume = volumes[0]
items = volume["configMap"].get("items", [])
require(len(items) == 20 and {item.get("key") for item in items} == set(keys),
        "Module 5 seed projection is incomplete.")

containers = [
    item for item in singleuser.get("initContainers", [])
    if item.get("name") == "seed-notebooks"
]
require(len(containers) == 1, "Notebook seeder is absent or ambiguous.")
seed = containers[0]
require(any(
    item.get("name") == volume.get("name")
    and item.get("mountPath") == mount_path
    and item.get("readOnly") is True
    for item in seed.get("volumeMounts", [])
), "Module 5 read-only seed mount is disabled.")
require("cloud_module5_delivery_enabled=true" in "\n".join(seed.get("args", [])),
        "Deployed notebook seeder disables Module 5 delivery.")
print("Module 5 offline asset and Helm configuration checks passed.")
CHECK

deployments="$(k3s kubectl -n "$namespace" get deployment \
  -l app.kubernetes.io/instance=jhub -o name)"
[[ -n "$deployments" ]] || {
  printf 'ERROR: No JupyterHub release deployments found.\n' >&2
  exit 1
}
while IFS= read -r deployment; do
  k3s kubectl -n "$namespace" rollout status "$deployment" --timeout=120s
done <<<"$deployments"

printf '%s\n' 'Offline delivery readiness passed; live OpenFaaS remains unvalidated.'
REMOTE
)"
  run_deployment_remote "$remote_script"
}

# Explicit test-cohort activation; real workshop publication remains blocked.
cloud_module5_activate_rehearsal() {
  local helper remote_script
  for helper in cloud_module1_require_complete_participant_cohort \
                ensure_workshop_activation_allowed run_deployment_remote confirm; do
    declare -F "$helper" >/dev/null || {
      printf 'ERROR: Rehearsal activation requires the organiser workflow (%s).\n' "$helper" >&2
      return 2
    }
  done

  cloud_module1_require_complete_participant_cohort || return $?
  ensure_workshop_activation_allowed cloud-computing-soa || return $?
  cloud_module5_check_rehearsal_readiness || return $?

  printf '%s\n' \
    'WARNING: This changes the shared workshop state for the entire test cohort.' \
    'Module 5 beginner drafts will seed subsequently spawned participant servers.' \
    'Existing running servers are not updated; existing workspace edits are preserved.' \
    'Live execution is disabled in the supplied template, not network-sandboxed.' \
    'Reset the rehearsal cohort before the real workshop.' \
    'Real workshop publication and live OpenFaaS readiness remain unvalidated.'

  if ! confirm "Activate Module 5 offline rehearsal for the shared test cohort"; then
    printf 'No rehearsal activation was performed.\n'
    return 0
  fi

  # Recheck the shared switch safeguard after the confirmation prompt.
  ensure_workshop_activation_allowed cloud-computing-soa || return $?

  printf -v remote_script 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  remote_script+="$(cat <<'REMOTE'
set -euo pipefail
k3s kubectl -n "$namespace" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"workshop_type":"cloud-computing-soa","workshop_module":"module5","mode":"beginner","solutions_released":"false"}}'
REMOTE
)"
  run_deployment_remote "$remote_script" || return $?

  printf '%s\n' \
    'Module 5 offline rehearsal is active for subsequently spawned participant servers.' \
    'Stop and start the test accounts’ JupyterHub servers to seed the notebooks.' \
    'Live OpenFaaS readiness remains NOT VALIDATED.'
}

run_cloud_module5_menu() {
  local choice
  while true; do
    workshop_ui_heading "Cloud SOA / Module 5 - OpenFaaS"
    workshop_ui_warning "Offline rehearsal only; live readiness NOT VALIDATED."
    workshop_ui_section "CHECK AND INSPECT"
    workshop_ui_option 1 "Check local pre-live assets"
    workshop_ui_option 2 "Show authoring status"
    workshop_ui_section "OFFLINE REHEARSAL"
    workshop_ui_option 3 "Prepare assets - private test cohort"
    workshop_ui_option 4 "Activate rehearsal - shared test cohort"
    printf '\n'
    workshop_ui_option 0 "Back to Cloud Computing SOA"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) cloud_module5_check || printf 'Pre-live checks did not pass.\n' >&2 ;;
      2) cloud_module5_status ;;
      4) cloud_module5_activate_rehearsal || printf 'Rehearsal activation did not complete.\n' >&2 ;;
      3) cloud_module5_prepare_rehearsal || printf 'Rehearsal preparation did not complete.\n' >&2 ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, 2, 3, or 4.\n' >&2 ;;
    esac
  done
}
