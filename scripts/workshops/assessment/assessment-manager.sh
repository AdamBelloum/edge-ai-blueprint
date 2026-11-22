#!/usr/bin/env bash
# Workshop assessment manager: generate and publish assessment notebooks.
#
# Usage:
#   assessment-manager.sh list     <workshop> <module>
#   assessment-manager.sh generate <workshop> <module>
#   assessment-manager.sh generate-menu                   (interactive; select module, then generate)
#   assessment-manager.sh publish  <workshop> <module>   (not implemented yet)
#   assessment-manager.sh publish-menu                    (interactive; discovery only)
#
# Example: assessment-manager.sh generate cloud-computing-soa module1
# Assessment folder: workshop_assets/<workshop>/<module>-*/assessment/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_PROJECT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
BUILDER_SCRIPT="${SCRIPT_DIR}/build_exam.py"
ASSETS_ROOT="${ROOT_PROJECT}/workshop_assets"
EXAMS_DIR="${ASSETS_ROOT}/assessment/exams"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SELECTED=""

log()  { printf '%s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
err()  { printf '[ERROR] %s\n' "$*" >&2; }

# Resolve workshop_assets/<workshop>/<module>[-*]/assessment (must be unique).
resolve_assessment_dir() {
  local workshop="$1" module="$2" ws_dir module_dir
  local -a matches=()

  [[ "${workshop}" =~ ^[a-z0-9-]+$ ]] || { err "Invalid workshop name: ${workshop}"; return 1; }
  [[ "${module}" =~ ^[a-z0-9]+$ ]]    || { err "Invalid module name: ${module}"; return 1; }

  ws_dir="${ASSETS_ROOT}/${workshop}"
  [[ -d "${ws_dir}" ]] || { err "Workshop assets not found: ${ws_dir}"; return 1; }

  shopt -s nullglob
  matches=( "${ws_dir}/${module}-"*/ )
  shopt -u nullglob
  if [[ -d "${ws_dir}/${module}" ]]; then
    matches+=( "${ws_dir}/${module}/" )
  fi

  if (( ${#matches[@]} == 0 )); then
    err "No module directory matching '${module}' under ${ws_dir}"
    return 1
  elif (( ${#matches[@]} > 1 )); then
    err "Ambiguous module '${module}' under ${ws_dir}: ${matches[*]}"
    return 1
  fi

  module_dir="${matches[0]%/}"
  printf '%s\n' "${module_dir}/assessment"
}

# Numbered menu. Sets SELECTED; returns 1 on cancel.
select_item() {
  local prompt="$1"; shift
  local -a items=("$@")
  local choice i

  for i in "${!items[@]}"; do
    if [[ "${SELECT_SHOW_FULL:-0}" == 1 ]]; then
      printf '  %d) %s\n' "$((i + 1))" "${items[$i]}"
    else
      printf '  %d) %s\n' "$((i + 1))" "$(basename "${items[$i]}")"
    fi
  done
  printf '  0) Cancel\n'

  while true; do
    read -rp "${prompt} [0-${#items[@]}]: " choice || return 1
    if [[ "${choice}" =~ ^[0-9]+$ ]] && (( 10#${choice} == 0 )); then
      return 1
    elif [[ "${choice}" =~ ^[0-9]+$ ]] && (( 10#${choice} >= 1 && 10#${choice} <= ${#items[@]} )); then
      SELECTED="${items[$((10#${choice} - 1))]}"
      return 0
    fi
    echo "Invalid selection. Enter a number between 0 and ${#items[@]}."
  done
}

confirm() {
  local answer
  read -rp "$1 [y/N]: " answer || return 1
  [[ "${answer}" =~ ^[Yy]([Ee][Ss])?$ ]]
}

question_files() {
  find "$1" -maxdepth 1 -type f \( -name '*.yaml' -o -name '*.yml' \) | sort
}

notebook_files() {
  find "$1" -maxdepth 1 -type f -name '*.ipynb' | sort
}

builder_supports_limit() {
  local help_text
  help_text="$("${PYTHON_BIN}" "${BUILDER_SCRIPT}" --help 2>&1 || true)"
  [[ "${help_text}" == *"--num-questions"* ]]
}

cmd_list() {
  local adir f
  adir="$(resolve_assessment_dir "$1" "$2")" || return 1
  log "Assessment directory: ${adir}"
  [[ -d "${adir}" ]] || { warn "Directory does not exist."; return 0; }

  log "Question files (inputs for generate):"
  while IFS= read -r f; do log "  - $(basename "${f}")"; done < <(question_files "${adir}")
  log "Notebooks (candidates only; NOT verified answer-free; an original may contain answers):"
  while IFS= read -r f; do log "  - $(basename "${f}")"; done < <(notebook_files "${adir}")
  log "Other files (never published): answer models, notes, etc."
  while IFS= read -r f; do
    case "${f}" in *.yaml|*.yml|*.ipynb) ;; *) log "  - $(basename "${f}")" ;; esac
  done < <(find "${adir}" -maxdepth 1 -type f | sort)
}

cmd_generate() {
  local adir qfile stem out num_questions
  local -a qfiles=() build_args=()

  adir="$(resolve_assessment_dir "$1" "$2")" || return 1
  [[ -f "${BUILDER_SCRIPT}" ]] || { err "Generator not found: ${BUILDER_SCRIPT}"; return 1; }
  [[ -d "${adir}" ]] || { warn "Assessment directory not found: ${adir}"; return 0; }

  mapfile -t qfiles < <(question_files "${adir}")
  if (( ${#qfiles[@]} == 0 )); then
    warn "No question files (*.yaml, *.yml) in ${adir}. Nothing to generate."
    return 0
  fi

  log "Question files for '$1' / '$2':"
  select_item "Select question file" "${qfiles[@]}" || { log "Generation cancelled."; return 0; }
  qfile="${SELECTED}"
  stem="$(basename "${qfile%.*}")"
  out="${EXAMS_DIR}/${stem}_exam.ipynb"

  while true; do
    read -rp "Number of questions to include (blank = all): " num_questions || return 1
    [[ -z "${num_questions}" || "${num_questions}" =~ ^[1-9][0-9]*$ ]] && break
    echo "Enter a positive integer, or leave blank."
  done

  build_args=("${qfile}" --output "${out}")
  if [[ -n "${num_questions}" ]]; then
    if builder_supports_limit; then
      build_args+=(--num-questions "${num_questions}")
    else
      err "build_exam.py does not support --num-questions yet; refusing to ignore your input."
      return 1
    fi
  fi

  log "Validating $(basename "${qfile}") ..."
  "${PYTHON_BIN}" "${BUILDER_SCRIPT}" "${qfile}" --validate-only

  if [[ -e "${out}" ]] && ! confirm "Overwrite existing $(basename "${out}")"; then
    log "Generation cancelled."
    return 0
  fi

  mkdir -p "${EXAMS_DIR}" || { err "Cannot create ${EXAMS_DIR}"; return 1; }
  "${PYTHON_BIN}" "${BUILDER_SCRIPT}" "${build_args[@]}"
  log "Generated: ${out}"
  log "Next: review ${out} manually. It is NOT verified answer-free beyond the generator's own checks."
  log "Publishing is not implemented yet."
}

# Discover workshop_assets/<workshop>/<module>/assessment directories and let the
# organiser select one. Sets TARGET_WORKSHOP, TARGET_MODULE_DIR and TARGET_MODULE.
# Returns 0 when selected, 1 when cancelled or none found, 2 on error.
# Lists directory names only; never reads file contents.
select_assessment_target() {
  local d rel
  local -a dirs=() labels=()

  TARGET_WORKSHOP=""
  TARGET_MODULE_DIR=""
  TARGET_MODULE=""

  [[ -t 0 ]] || { err "An interactive terminal is required."; return 2; }
  [[ -d "${ASSETS_ROOT}" ]] || { err "Workshop assets not found: ${ASSETS_ROOT}"; return 2; }

  shopt -s nullglob
  dirs=( "${ASSETS_ROOT}"/*/*/assessment )
  shopt -u nullglob

  for d in ${dirs[@]+"${dirs[@]}"}; do
    [[ -d "${d}" ]] || continue
    rel="${d#"${ASSETS_ROOT}/"}"
    labels+=( "${rel%/assessment}" )
  done

  if (( ${#labels[@]} == 0 )); then
    warn "No assessment directories found under ${ASSETS_ROOT}/<workshop>/<module>/assessment."
    return 1
  fi

  log "Assessment directories (workshop/module):"
  SELECT_SHOW_FULL=1 select_item "Select workshop/module" "${labels[@]}" \
    || { log "Cancelled."; return 1; }

  TARGET_WORKSHOP="${SELECTED%%/*}"
  TARGET_MODULE_DIR="${SELECTED#*/}"
  TARGET_MODULE="${TARGET_MODULE_DIR%%-*}"
  return 0
}

# Interactive: select a module, then run the existing generate workflow
# (question file, number of questions, build_exam.py).
cmd_generate_menu() {
  local rc=0
  select_assessment_target || rc=$?
  if (( rc == 1 )); then return 0; fi
  if (( rc != 0 )); then return "${rc}"; fi

  log ""
  log "Selected: ${TARGET_WORKSHOP} / ${TARGET_MODULE_DIR}"
  cmd_generate "${TARGET_WORKSHOP}" "${TARGET_MODULE}"
}

# Interactive discovery only. Prints a file-name summary for the selected module.
# It never reads, prints, copies or publishes file contents.
# Publication is NOT implemented.
cmd_publish_menu() {
  local rc=0
  select_assessment_target || rc=$?
  if (( rc == 1 )); then return 0; fi
  if (( rc != 0 )); then return "${rc}"; fi

  log ""
  log "Selected: ${TARGET_WORKSHOP} / ${TARGET_MODULE_DIR}"
  cmd_list "${TARGET_WORKSHOP}" "${TARGET_MODULE}" || return 1

  log ""
  warn "Publishing is NOT implemented. Nothing was copied, published or modified."
  warn "Notebook candidates are NOT verified answer-free; organiser review is required before any future publication."
  return 0
}

# Select one generated exam for publication. Writes the absolute path of the
# chosen notebook to <result-file> (created by the caller). Lists names only;
# never reads notebook contents and never contacts the cluster.
cmd_select_exam() {
  local result_file="$1"
  local -a exams=()

  [[ -f "${result_file}" && ! -L "${result_file}" && -w "${result_file}" ]] || {
    err "Result file must be an existing, writable, regular file: ${result_file}"
    return 2
  }
  [[ -d "${EXAMS_DIR}" ]] || {
    err "No exams directory: ${EXAMS_DIR}. Create an exam first."
    return 1
  }

  mapfile -t exams < <(find "${EXAMS_DIR}" -maxdepth 1 -type f -name '*_exam.ipynb' | sort)
  if (( ${#exams[@]} == 0 )); then
    err "No *_exam.ipynb files in ${EXAMS_DIR}. Create an exam first."
    return 1
  fi

  if (( ${#exams[@]} == 1 )); then
    SELECTED="${exams[0]}"
    log "Exam found: $(basename "${SELECTED}")"
  else
    [[ -t 0 ]] || { err "Several exams exist; an interactive terminal is required to select one."; return 2; }
    log "Several exams found in ${EXAMS_DIR}:"
    select_item "Select the exam to publish" "${exams[@]}" || { log "Selection cancelled."; return 1; }
  fi

  printf '%s\n' "${SELECTED}" > "${result_file}"
}

usage() {
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    publish-menu|generate-menu)
      [[ $# -eq 1 ]] || { usage >&2; return 2; }
      ;;
    select-exam)
      [[ $# -eq 2 ]] || { usage >&2; return 2; }
      ;;
    list|generate|publish)
      [[ $# -eq 3 ]] || { usage >&2; return 2; }
      ;;
    *) usage >&2; return 2 ;;
  esac

  case "${cmd}" in
    list)     cmd_list "$2" "$3" ;;
    generate) cmd_generate "$2" "$3" ;;
    generate-menu) cmd_generate_menu ;;
    publish-menu) cmd_publish_menu ;;
    select-exam) cmd_select_exam "$2" ;;
    publish)  err "publish is not implemented yet."; return 2 ;;
  esac
}

main "$@"
