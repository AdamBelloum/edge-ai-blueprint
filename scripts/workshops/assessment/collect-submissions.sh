#!/usr/bin/env bash
# Organiser tool: collect the latest harvested exam notebook of every participant (per group).
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: collect-submissions.sh

Interactively select a workshop/module exam, then collect the latest harvested
notebook of every participant (per group) from the worker VMs into:
  workshop_assets/<workshop>/<module-dir>/assessment/submissions/
  <group>_<workshop>_<module-dir>_<person>_<YYYYMMDD>.ipynb   (date is UTC)
<person> is the name slug from the participant's personal exam copy. Exams
without personal copies (older exams) are collected per group, without <person>.

Participant data on the workers is only read: it is never changed or deleted.
A temporary root-owned scratch copy (/var/tmp/assessment-collect.*) is made on
each worker and removed afterwards (best effort: after a failure or interruption
it may remain for an administrator to remove). Symlinks in participant-controlled
paths are refused, but races are not fully excluded. Copies are verified by
SHA-256 and as notebooks; identical earlier collections are reported as
"already collected"; different content under the same name gets _HHMM (UTC).
Entries that fail verification are reported and not collected.

Default is fail-closed: if any worker fails, is unreachable or reports a
problem, nothing is finalized (the latest submission could be on that worker).
  --allow-partial   finalize what was fetched anyway; results may NOT be the
                    latest submission of every participant, and the run exits 1.

Exit status: 0 clean, 1 failed or incomplete, 2 usage or missing prerequisite.

Limits: a person is identified only by the name slug in the harvest file name;
two people who enter the same name are told apart only by the -2, -3 suffix
chosen when the copy was created. The exam is identified only by its file name
(the harvest stem). The
workers cannot prove which publication a notebook belongs to, and files in
participant homes are participant-writable and not authoritative.
USAGE
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
fi
allow_partial=0
if [[ $# -eq 1 && "$1" == --allow-partial ]]; then
  allow_partial=1
elif [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
context="$SCRIPT_DIR/../lib/workshop-context.sh"
[[ -r "$context" ]] || {
  printf 'ERROR: Missing workshop context helper.\n' >&2
  exit 2
}
# shellcheck source=../lib/workshop-context.sh
source "$context"
load_workshop_context

repository_root="$WORKSHOP_CONTEXT_REPOSITORY_ROOT"
assets_root="$repository_root/workshop_assets"
manager="$SCRIPT_DIR/assessment-manager.sh"
playbook="$repository_root/playbooks/collect-assessment-submissions.yml"
finalizer="$SCRIPT_DIR/finalize_collected.py"

[[ -t 0 ]] || {
  printf 'ERROR: An interactive terminal is required. Nothing was collected.\n' >&2
  exit 2
}
for command in python3 ansible-playbook find; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'ERROR: Required command not found: %s\n' "$command" >&2
    exit 2
  }
done
for file in "$manager" "$playbook" "$finalizer"; do
  [[ -r "$file" ]] || {
    printf 'ERROR: Missing or unreadable: %s\n' "$file" >&2
    exit 2
  }
done
cd -- "$repository_root"

umask 077
work="$(mktemp -d "${TMPDIR:-/tmp}/digitafrica-collect.XXXXXXXX")"
work_re='/digitafrica-collect\.[A-Za-z0-9]{8}$'
cleanup_work() {
  if [[ -d "$work" && ! -L "$work" && "$work" =~ $work_re ]]; then
    rm -rf -- "$work"
  fi
}
trap cleanup_work EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

stage="$work/stage"
result_file="$work/exam-path"
mkdir -m 0700 -- "$stage"
: > "$result_file"
[[ "$stage" =~ ^/[A-Za-z0-9/_.-]+$ ]] || {
  printf 'ERROR: Staging path has unsupported characters (check TMPDIR): %s\n' "$stage" >&2
  exit 2
}

select_rc=0
bash "$manager" select-exam "$result_file" || select_rc=$?
if (( select_rc != 0 )); then
  printf 'No exam selected (exit code %s). Nothing was collected.\n' "$select_rc" >&2
  exit 1
fi
exam_path="$(<"$result_file")"

exam_re='^([a-z0-9-]+)/([A-Za-z0-9][A-Za-z0-9._-]*)/assessment/([A-Za-z0-9][A-Za-z0-9._-]*)_exam\.ipynb$'
[[ "$exam_path" =~ ^/[A-Za-z0-9._/-]+$ ]] || {
  printf 'ERROR: Exam path has unsupported characters. Nothing was collected.\n' >&2
  exit 1
}
[[ "$exam_path" == "$assets_root"/* ]] || {
  printf 'ERROR: Exam is not under %s. Nothing was collected.\n' "$assets_root" >&2
  exit 1
}
relative="${exam_path#"$assets_root"/}"
[[ "$relative" =~ $exam_re ]] || {
  printf 'ERROR: Unexpected exam location (want <workshop>/<module-dir>/assessment/<name>_exam.ipynb): %s\n' \
    "$relative" >&2
  exit 1
}
workshop="${BASH_REMATCH[1]}"
module_dir="${BASH_REMATCH[2]}"
exam_stem="${BASH_REMATCH[3]}_exam"
exam_file="${exam_stem}.ipynb"
[[ -f "$exam_path" && ! -L "$exam_path" ]] || {
  printf 'ERROR: Selected exam is not a regular file: %s\n' "$exam_path" >&2
  exit 1
}

mapfile -t same_name < <(find "$assets_root" -type f -name "$exam_file" -print)
if (( ${#same_name[@]} != 1 )); then
  printf 'ERROR: The exam file name must be unique across workshop assets; found %s:\n' \
    "${#same_name[@]}" >&2
  printf '  %s\n' "${same_name[@]}" >&2
  printf 'Harvested notebooks are identified by file name only. Nothing was collected.\n' >&2
  exit 1
fi

dest="$assets_root/$workshop/$module_dir/assessment/submissions"
printf '%s\n' \
  "Workshop:     $workshop" \
  "Module:       $module_dir" \
  "Exam file:    $exam_file" \
  "Inventory:    $DIGITAFRICA_INVENTORY" \
  "Worker group: $DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" \
  "Destination:  $dest" \
  'Workers:      participant data is only read; a temporary root scratch copy is made and removed.' \
  'Dates in file names are UTC (harvest timestamps).'

playbook_rc=0
ansible-playbook -i "$DIGITAFRICA_INVENTORY" "$playbook" \
  -e "assessment_worker_group=$DIGITAFRICA_DEPLOYMENT_WORKER_GROUP" \
  -e "assessment_staging_dir=$stage" \
  -e "assessment_exam_stem=$exam_stem" || playbook_rc=$?

if (( playbook_rc != 0 && allow_partial == 0 )); then
  printf 'INCOMPLETE: a worker failed or reported problems (ansible exit code %s).\n' "$playbook_rc" >&2
  printf 'Nothing was finalized: the latest submission may be on the failed worker.\n' >&2
  printf 'Fix the problem and re-run, or use --allow-partial to keep verified copies.\n' >&2
  exit 1
fi

final_rc=0
PYTHONDONTWRITEBYTECODE=1 python3 "$finalizer" \
  --staging "$stage" --dest "$dest" \
  --workshop "$workshop" --module-dir "$module_dir" || final_rc=$?

status=0
if (( playbook_rc != 0 )); then
  printf 'PARTIAL (--allow-partial): a worker failed or reported problems (ansible exit code %s).\n' "$playbook_rc" >&2
  printf 'WARNING: collected files may NOT be the latest submission of every participant.\n' >&2
  status=1
fi
case "$final_rc" in
  0) ;;
  3) printf 'INCOMPLETE: some entries were not collected (see PROBLEM lines above).\n' >&2; status=1 ;;
  *) printf 'ERROR: verification and placement failed (exit code %s).\n' "$final_rc" >&2; status=1 ;;
esac
if (( status == 0 )); then
  printf 'Collection complete.\n'
else
  printf 'Only entries reported above as "collected" or "already collected" were placed; check the Summary line.\n' >&2
fi
exit "$status"
