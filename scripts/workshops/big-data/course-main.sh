#!/usr/bin/env bash
# Big Data organiser course workflow, sourced through controllers/big_data.sh.
# Publication delivers participant assets; it does not start or validate Spark.

BIG_DATA_COURSE_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd
)"
BIG_DATA_SPARK_MODULE_MAIN="$BIG_DATA_COURSE_DIR/spark/module-main.sh"

if [[ ! -r "$BIG_DATA_SPARK_MODULE_MAIN" ]]; then
  printf 'Missing Spark module workflow: %s\n' \
    "$BIG_DATA_SPARK_MODULE_MAIN" >&2
  return 1
fi

# shellcheck source=spark/module-main.sh
source "$BIG_DATA_SPARK_MODULE_MAIN"

run_big_data_menu() {
  local choice
  while true; do
    workshop_ui_heading "Workshops / Big Data"
    workshop_ui_section "SELECT A WORKSHOP LEVEL"
    workshop_ui_option 1 "Spark Beginner: publication available; execution not validated"
    workshop_ui_option 2 "Spark Advanced: TODO - not implemented"
    printf '\n'
    workshop_ui_option 0 "Back to workshops"
    workshop_ui_prompt
    read -r choice || return 0
    case "$choice" in
      1) run_big_data_spark_menu ;;
      2)
        printf '%s\n' 'TODO: Spark advanced workshop is not implemented. No changes made.'
        ;;
      0) return 0 ;;
      *) printf 'Choose 0, 1, or 2.\n' >&2 ;;
    esac
  done
}
