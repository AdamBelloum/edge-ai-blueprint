#!/usr/bin/env bash
# Run inside the Jupyter runtime, never on the HPC head node.
set -euo pipefail

fail() {
  printf '[hpc-runtime] ERROR: %s\n' "$*" >&2
  exit 1
}

specification="${1:?Usage: prepare-hpc-environment.sh /path/to/environment.yml}"
test -f "$specification" || fail "Environment definition is missing."
test "$(uname -s)" = Linux || fail "Linux is required."
test "$(uname -m)" = x86_64 || fail "This toolchain requires x86_64."
test -n "${HOME:-}" || fail "HOME is not configured."
test -d "$HOME" && test -w "$HOME" || fail "HOME must exist and be writable."

conda_executable="$(command -v conda || true)"
if [ -z "$conda_executable" ] && [ -x /opt/conda/bin/conda ]; then
  conda_executable=/opt/conda/bin/conda
fi
test -n "$conda_executable" || fail "Conda is required in the notebook image."

runtime_root="$HOME/.local/share/digitafrica/runtime/hpc"
prefix="$runtime_root/environment"
marker="$runtime_root/environment.sha256"
expected="$(sha256sum "$specification" | cut -d ' ' -f1)"

mkdir -p "$runtime_root"

if [ -e "$prefix" ]; then
  test -f "$marker" || fail "Existing environment has no completion marker; administrator recovery is required."
  test "$(cat "$marker")" = "$expected" ||
    fail "Environment definition changed; explicit environment migration is required."
else
  printf '[hpc-runtime] Creating the persistent HPC toolchain.\n'
  "$conda_executable" env create \
    --yes \
    --prefix "$prefix" \
    --file "$specification"
fi

# Activate only in this process. Notebook activation is configured separately.
eval "$("$conda_executable" shell.bash hook)"
conda activate "$prefix"

test -n "${CC:-}" || fail "Conda did not configure the C compiler."
command -v "$CC" >/dev/null || fail "Configured C compiler is unavailable."
command -v mpicc >/dev/null || fail "MPI compiler wrapper is unavailable."
command -v mpirun >/dev/null || fail "MPI launcher is unavailable."
command -v make >/dev/null || fail "Make is unavailable."

printf '%s\n' "$expected" > "$marker"
printf '[hpc-runtime] Toolchain available at %s\n' "$prefix"
