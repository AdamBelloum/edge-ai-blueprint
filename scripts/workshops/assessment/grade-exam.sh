#!/usr/bin/env bash
# Organiser tool: grade the collected submissions of one exam (deterministic, private reports).
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: grade-exam.sh

Interactively select a workshop/module exam, then grade the collected
submissions in
  workshop_assets/<workshop>/<module-dir>/assessment/submissions/
against the answer model in
  workshop_assets/<workshop>/<module-dir>/assessment/<name>_answer_model
(exactly one file matching *_answer_model must exist; *.bak-* files are ignored).

Private reports (summary.csv and per-participant reports) are written to a NEW
directory outside the repository and outside the submissions folder:
  ${DIGITAFRICA_ASSESSMENT_REPORTS_DIR:-$HOME/assessment-reports}/<workshop>_<module-dir>_<UTC>/
The reports contain participant names and e-mail addresses. Never commit them.

Inputs are only read. Run "Collect submissions" first.
Exit status: 0 clean, 1 failed, 2 usage or missing prerequisite.
USAGE
}

if [[ $# -eq 1 && ( "$1" == --help || "$1" == -h ) ]]; then
  usage
  exit 0
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
grader="$SCRIPT_DIR/grade_exam.py"

[[ -t 0 ]] || {
  printf 'ERROR: An interactive terminal is required. Nothing was graded.\n' >&2
  exit 2
}
for command in python3 find; do
  command -v "$command" >/dev/null 2>&1 || {
    printf 'ERROR: Required command not found: %s\n' "$command" >&2
    exit 2
  }
done
for file in "$manager" "$grader"; do
  [[ -r "$file" ]] || {
    printf 'ERROR: Missing or unreadable: %s\n' "$file" >&2
    exit 2
  }
done
cd -- "$repository_root"

umask 077
work="$(mktemp -d "${TMPDIR:-/tmp}/digitafrica-grade.XXXXXXXX")"
work_re='/digitafrica-grade\.[A-Za-z0-9]{8}$'
cleanup_work() {
  if [[ -d "$work" && ! -L "$work" && "$work" =~ $work_re ]]; then
    rm -rf -- "$work"
  fi
}
trap cleanup_work EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

result_file="$work/exam-path"
: > "$result_file"

select_rc=0
bash "$manager" select-exam "$result_file" || select_rc=$?
if (( select_rc != 0 )); then
  printf 'No exam selected (exit code %s). Nothing was graded.\n' "$select_rc" >&2
  exit 1
fi
exam_path="$(<"$result_file")"

exam_re='^([a-z0-9-]+)/([A-Za-z0-9][A-Za-z0-9._-]*)/assessment/([A-Za-z0-9][A-Za-z0-9._-]*)_exam\.ipynb$'
[[ "$exam_path" =~ ^/[A-Za-z0-9._/-]+$ ]] || {
  printf 'ERROR: Exam path has unsupported characters. Nothing was graded.\n' >&2
  exit 1
}
[[ "$exam_path" == "$assets_root"/* ]] || {
  printf 'ERROR: Exam is not under %s. Nothing was graded.\n' "$assets_root" >&2
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

assessment_dir="$assets_root/$workshop/$module_dir/assessment"
harvest="$assessment_dir/submissions"

[[ -d "$harvest" && ! -L "$harvest" ]] || {
  printf 'ERROR: No submissions folder: %s\nRun "Collect submissions" first. Nothing was graded.\n' \
    "$harvest" >&2
  exit 1
}
mapfile -t submissions < <(find "$harvest" -maxdepth 1 -type f -name '*.ipynb' -print)
if (( ${#submissions[@]} == 0 )); then
  printf 'ERROR: No collected notebooks in %s. Nothing was graded.\n' "$harvest" >&2
  exit 1
fi

mapfile -t models < <(find "$assessment_dir" -maxdepth 1 -type f -name '*_answer_model' -print)
if (( ${#models[@]} != 1 )); then
  printf 'ERROR: Expected exactly one *_answer_model file in %s; found %s.\n' \
    "$assessment_dir" "${#models[@]}" >&2
  (( ${#models[@]} > 0 )) && printf '  %s\n' "${models[@]}" >&2
  printf 'Nothing was graded.\n' >&2
  exit 1
fi
model="${models[0]}"

reports_root="${DIGITAFRICA_ASSESSMENT_REPORTS_DIR:-$HOME/assessment-reports}"
[[ "$reports_root" == /* ]] || {
  printf 'ERROR: DIGITAFRICA_ASSESSMENT_REPORTS_DIR must be an absolute path.\n' >&2
  exit 2
}
case "$reports_root/" in
  "$repository_root"/*|"$harvest"/*)
    printf 'ERROR: The reports directory must be outside the repository and the submissions folder.\n' >&2
    exit 2
    ;;
esac
mkdir -p -m 0700 -- "$reports_root"
out_dir="$reports_root/${workshop}_${module_dir}_$(date -u +%Y%m%dT%H%M%SZ)"

printf '%s\n' \
  "Workshop:     $workshop" \
  "Module:       $module_dir" \
  "Answer model: ${model#"$repository_root"/}" \
  "Submissions:  ${harvest#"$repository_root"/} (${#submissions[@]} notebook(s))" \
  "Reports:      $out_dir" \
  'Inputs are only read. Reports contain participant e-mail addresses: keep them private.'

grade_rc=0
PYTHONDONTWRITEBYTECODE=1 python3 "$grader" \
  --model "$model" --harvest "$harvest" --out "$out_dir" || grade_rc=$?

if (( grade_rc != 0 )); then
  printf 'ERROR: Grading failed (exit code %s). See messages above.\n' "$grade_rc" >&2
  exit 1
fi
if [[ -f "$out_dir/summary.csv" ]]; then
  printf 'Grading complete.\nSummary for the badge step: %s\n' "$out_dir/summary.csv"
else
  printf 'ERROR: Grading reported success but %s/summary.csv is missing.\n' "$out_dir" >&2
  exit 1
fi
