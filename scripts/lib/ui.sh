#!/usr/bin/env bash
# Presentation only. Safe to source; no deployment access or input handling.
# Redirect an entire function call to >&2 when presenting a stderr prompt.

_digitafrica_ui_text() {
  local kind="$1" text="$2"
  local style="" reset="" colors=""

  if [[ -t 1 && -z "${NO_COLOR+x}" &&
        -n "${TERM:-}" && "${TERM:-}" != dumb ]] &&
     command -v tput >/dev/null 2>&1; then
    colors="$(tput colors 2>/dev/null)" || colors=""
    if [[ "$colors" =~ ^[0-9]+$ ]] && ((colors >= 8)); then
      reset="$(tput sgr0 2>/dev/null)" || reset=""
      case "$kind" in
        title|section) style="$(tput bold 2>/dev/null)" || style="" ;;
        option) style="$(tput setaf 6 2>/dev/null)" || style="" ;;
        warning) style="$(tput setaf 3 2>/dev/null)" || style="" ;;
      esac
    fi
  fi

  printf '%s%s%s' "$style" "$text" "$reset"
}

digitafrica_ui_heading() {
  printf '\n'
  _digitafrica_ui_text title "$1"
  printf '\n----------------------------------------\n'
}

digitafrica_ui_section() {
  printf '\n  '
  _digitafrica_ui_text section "$1"
  printf '\n'
}

digitafrica_ui_option() {
  printf '  '
  _digitafrica_ui_text option "$(printf '%2s)' "$1")"
  printf ' %s\n' "$2"
}

digitafrica_ui_note() {
  printf '     %s\n' "$1"
}

digitafrica_ui_warning() {
  printf '\n  '
  _digitafrica_ui_text warning "WARNING: $1"
  printf '\n'
}

digitafrica_ui_prompt() {
  printf '\nSelect an option: '
}
