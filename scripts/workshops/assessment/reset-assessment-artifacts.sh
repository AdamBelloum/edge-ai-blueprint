#!/usr/bin/env bash
# Warn about collected assessment submissions left after a workshop reset and,
# only on explicit confirmation, remove them.
# Scope: <workshop>/<module>/assessment/submissions/*.ipynb (regular files).
# Never touches exams, questions, solutions, ConfigMaps, volumes or workers.
# Exit: 0 clean/removed, 1 error, 2 submissions remain (declined/no terminal).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
assets="${ASSESSMENT_ASSETS_DIR:-$(cd "$here/../../.." && pwd -P)/workshop_assets}"
[[ -d $assets ]] || { echo "ERROR: $assets not found; submissions not checked." >&2; exit 1; }

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
find -P "$assets" -mindepth 5 -maxdepth 5 -type f -name '*.ipynb' \
     -path '*/assessment/submissions/*' -print0 | sort -z >"$tmp" \
  || { echo "ERROR: search failed; submissions not checked." >&2; exit 1; }
mapfile -d '' -t files <"$tmp"

if ((${#files[@]} == 0)); then
  echo "No collected submissions under $assets/*/*/assessment/submissions/."
  echo "(Only this organiser location was checked, not workers or custom paths.)"
  exit 0
fi

echo
echo "WARNING: collected assessment submissions remain after the reset:"
for f in "${files[@]}"; do
  printf '  %s  (%s bytes)\n' "${f#"$assets"/}" "$(stat -c %s -- "$f")"
done
echo "Exams, questions and solutions are NOT touched."
echo

[[ -t 0 ]] || { echo "Interactive terminal required to confirm. Nothing was removed."; exit 2; }
read -r -p "Remove these ${#files[@]} file(s)? They cannot be recovered. [y/N]: " ans
[[ $ans == [yY] ]] || { echo "Nothing was removed."; exit 2; }

removed=0; failed=0
for f in "${files[@]}"; do
  if [[ -f $f && ! -L $f ]] && rm -f -- "$f"; then
    removed=$((removed + 1))
  else
    echo "Could not remove: ${f#"$assets"/}" >&2
    failed=$((failed + 1))
  fi
done
echo "Removed $removed file(s); $failed failed."
((failed == 0)) || exit 1
