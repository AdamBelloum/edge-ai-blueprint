#!/usr/bin/env bash
# Publish and verify Introduction to AI Module 2 workshop material.
# Three tracks are published together: beginner, advanced, and solutions.
#
# To add Module 3: copy this file, replace every occurrence of
#   module2 → module3
#   MODULE2 → MODULE3
#   02_    → 03_
# and register the new helper in organizer-main.sh (see MODULE2_HELPER).

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

REMOTE_STAGE_DIR="/tmp/digitafrica-introduction-to-ai-module2"

usage() {
  cat <<'USAGE'
Usage:
  module2.sh publish [--yes]
  module2.sh status
  module2.sh check

Actions:
  publish     Validate and publish all three Module 2 tracks
              (beginner, advanced, solutions) to their ConfigMaps and set
              module2_published=true in digitafrica-workshop-state.
  status      Show whether each Module 2 ConfigMap contains its notebook.
  check       Verify that all three tracks are ready for participant spawns.

The source files and immutable source Git revisions must be defined in the
active workshop-release.env:
  INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_FILE / _SOURCE_REF
  INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_FILE / _SOURCE_REF
  INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_FILE / _SOURCE_REF

Publishing affects subsequently spawned participant servers only. It never
changes an existing participant notebook, participant identity, FL workspace,
data partition, or Flower server.
USAGE
}

ACTION=""
ASSUME_YES=false

while (($#)); do
  case "$1" in
    publish|status|check)
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

if "$ASSUME_YES" && [[ "$ACTION" != "publish" ]]; then
  printf '%s\n' '--yes is valid only with publish.' >&2
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

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

validate_notebook_file() {
  local track="$1" source_file="$2" expected_name="$3"

  [[ -f "$source_file" ]] ||
    die "Module 2 $track source notebook is not readable: $source_file"

  [[ "$(basename -- "$source_file")" == "$expected_name" ]] ||
    die "Module 2 $track source file must be named $expected_name"

  require_command python3
  python3 - "$source_file" <<'PYTHON_VALIDATE'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    notebook = json.loads(path.read_text(encoding="utf-8"))
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"Module 2 source is not valid UTF-8 notebook JSON: {exc}")

if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
    raise SystemExit("Module 2 source is not a valid Jupyter notebook structure.")
PYTHON_VALIDATE
}

require_module2_sources() {
  : "${INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_FILE:?Workshop release record must define INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_FILE.}"
  : "${INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_REF:?Workshop release record must define INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_REF.}"
  : "${INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_FILE:?Workshop release record must define INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_FILE.}"
  : "${INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_REF:?Workshop release record must define INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_REF.}"
  : "${INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_FILE:?Workshop release record must define INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_FILE.}"
  : "${INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_REF:?Workshop release record must define INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_REF.}"

  for ref_var in \
    INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_REF \
    INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_REF \
    INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_REF; do
    [[ "${!ref_var}" =~ ^[0-9A-Fa-f]{7,64}$ ]] ||
      die "$ref_var must be an immutable source Git commit SHA."
  done

  validate_notebook_file beginner \
    "$INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_FILE" "$NOTEBOOK_BEGINNER"
  validate_notebook_file advanced \
    "$INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_FILE" "$NOTEBOOK_ADVANCED"
  validate_notebook_file solutions \
    "$INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_FILE" "$NOTEBOOK_SOLUTIONS"
}

# ---------------------------------------------------------------------------
# Remote status script
# ---------------------------------------------------------------------------

remote_status_script() {
  printf 'namespace=%q\n' "$DIGITAFRICA_NAMESPACE"
  cat <<'REMOTE_STATUS'
set -euo pipefail

check_track() {
  local track="$1" configmap="$2" notebook_key="$3"

  if ! k3s kubectl -n "$namespace" get configmap "$configmap" >/dev/null 2>&1; then
    printf 'module2_%s_configmap_status=absent\n' "$track"
    return
  fi

  notebook="$(
    k3s kubectl -n "$namespace" get configmap "$configmap" \
      -o jsonpath="{.data.${notebook_key}}"
  )"

  if [[ -z "$notebook" ]]; then
    printf 'module2_%s_configmap_status=placeholder\n' "$track"
    return
  fi

  printf 'module2_%s_configmap_status=published\n' "$track"
  printf '%s' "$notebook" | sha256sum | awk "{print \"module2_${track}_configmap_sha256=\" \$1}"
}

check_track beginner \
  digitafrica-notebooks-introduction-to-ai-module2-beginner \
  "02_foundations_of_ml_beginner.ipynb"

check_track advanced \
  digitafrica-notebooks-introduction-to-ai-module2-advanced \
  "02_foundations_of_ml_advanced.ipynb"

check_track solutions \
  digitafrica-notebooks-introduction-to-ai-module2-solutions \
  "02_foundations_of_ml_solutions.ipynb"

module2_flag="$(
  k3s kubectl -n "$namespace" \
    get configmap digitafrica-workshop-state \
    -o jsonpath='{.data.module2_published}' 2>/dev/null || true
)"
printf 'module2_state_flag=%s\n' "${module2_flag:-unset}"
REMOTE_STATUS
}

show_status() {
  print_heading "Introduction to AI — Module 2 publication status"
  run_deployment_remote "$(remote_status_script)"
  cat <<'STATUS_MESSAGE'

A published notebook is copied only when a participant next spawns a JupyterHub
server and does not already have the file under:
  ~/Introduction-to-AI/Module-2/
STATUS_MESSAGE
}

# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

publish_module2() {
  local beginner_sha256 advanced_sha256 solutions_sha256
  local copy_arguments remote_script

  require_module2_sources
  require_command sha256sum
  require_ansible_environment

  beginner_sha256="$(sha256sum "$INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_FILE" | awk '{print $1}')"
  advanced_sha256="$(sha256sum "$INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_FILE" | awk '{print $1}')"
  solutions_sha256="$(sha256sum "$INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_FILE" | awk '{print $1}')"

  print_heading "Publish Introduction to AI — Module 2 (all tracks)"
  printf 'Beginner  notebook : %s\n' "$INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_FILE"
  printf 'Beginner  commit   : %s\n' "$INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_REF"
  printf 'Beginner  SHA-256  : %s\n' "$beginner_sha256"
  printf 'Advanced  notebook : %s\n' "$INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_FILE"
  printf 'Advanced  commit   : %s\n' "$INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_REF"
  printf 'Advanced  SHA-256  : %s\n' "$advanced_sha256"
  printf 'Solutions notebook : %s\n' "$INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_FILE"
  printf 'Solutions commit   : %s\n' "$INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_REF"
  printf 'Solutions SHA-256  : %s\n' "$solutions_sha256"
  printf '%s\n' \
    'This updates material for subsequently spawned participant servers only.' \
    'Existing participant notebooks are preserved.'

  if ! "$ASSUME_YES" && ! confirm 'Publish all three Module 2 tracks'; then
    log 'No Module 2 publication was performed.'
    return 0
  fi

  # Stage all three notebooks onto the central node.
  for track_args in \
    "beginner:$INTRODUCTION_TO_AI_MODULE2_BEGINNER_SOURCE_FILE:$NOTEBOOK_BEGINNER" \
    "advanced:$INTRODUCTION_TO_AI_MODULE2_ADVANCED_SOURCE_FILE:$NOTEBOOK_ADVANCED" \
    "solutions:$INTRODUCTION_TO_AI_MODULE2_SOLUTIONS_SOURCE_FILE:$NOTEBOOK_SOLUTIONS"; do

    IFS=: read -r _track src_file nb_name <<<"$track_args"
    copy_arguments="src='$src_file' dest='${REMOTE_STAGE_DIR}/${nb_name}' owner=root group=root mode=0600"
    ANSIBLE_STDOUT_CALLBACK=default ansible \
      -i "$DIGITAFRICA_INVENTORY" \
      "$DIGITAFRICA_DEPLOYMENT_GROUP" \
      -b \
      -m ansible.builtin.file \
      -a "path='$REMOTE_STAGE_DIR' state=directory owner=root group=root mode=0700"
    ANSIBLE_STDOUT_CALLBACK=default ansible \
      -i "$DIGITAFRICA_INVENTORY" \
      "$DIGITAFRICA_DEPLOYMENT_GROUP" \
      -b \
      -m ansible.builtin.copy \
      -a "$copy_arguments"
  done

  printf -v remote_script 'namespace=%q\nstage_dir=%q\n' \
    "$DIGITAFRICA_NAMESPACE" "$REMOTE_STAGE_DIR"
  remote_script+="$(cat <<'REMOTE_PUBLISH'
set -euo pipefail
trap 'rm -rf "$stage_dir"' EXIT

publish_track() {
  local configmap="$1" notebook_key="$2" notebook_file="$3"
  test -s "$notebook_file"
  k3s kubectl -n "$namespace" \
    create configmap "$configmap" \
    --from-file="${notebook_key}=${notebook_file}" \
    --dry-run=client -o yaml | \
    k3s kubectl apply -f -
  printf 'Published: %s\n' "$configmap"
}

publish_track \
  digitafrica-notebooks-introduction-to-ai-module2-beginner \
  02_foundations_of_ml_beginner.ipynb \
  "${stage_dir}/02_foundations_of_ml_beginner.ipynb"

publish_track \
  digitafrica-notebooks-introduction-to-ai-module2-advanced \
  02_foundations_of_ml_advanced.ipynb \
  "${stage_dir}/02_foundations_of_ml_advanced.ipynb"

publish_track \
  digitafrica-notebooks-introduction-to-ai-module2-solutions \
  02_foundations_of_ml_solutions.ipynb \
  "${stage_dir}/02_foundations_of_ml_solutions.ipynb"

k3s kubectl -n "$namespace" \
  patch configmap digitafrica-workshop-state \
  --type merge \
  -p '{"data":{"module2_published":"true"}}'

printf '%s\n' 'Module 2 state flag set: module2_published=true'
printf '%s\n' 'Module 2 all tracks published successfully.'
REMOTE_PUBLISH
)"

  run_deployment_remote "$remote_script"
  show_status
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "$ACTION" in
  publish) publish_module2 ;;
  status)  show_status ;;
  check)
    status_output="$(show_status)"
    printf '%s\n' "$status_output"
    printf '%s\n' \
      'Readiness condition: all three tracks must be published before Module 2' \
      'is assigned to participants.'

    all_published=true
    for track in beginner advanced solutions; do
      if ! grep -Fq "module2_${track}_configmap_status=published" <<<"$status_output"; then
        printf 'NOT published: %s track\n' "$track" >&2
        all_published=false
      fi
    done

    if [[ "$all_published" != true ]]; then
      printf '%s\n' \
        'Module 2 is not fully published; do not assign Module 2 to participants.' >&2
      exit 1
    fi
    ;;
esac

