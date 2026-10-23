#!/usr/bin/env bash
# Activate the persistent toolchain only inside the notebook container.
set -euo pipefail

fail() {
  printf '[hpc-launch] ERROR: %s\n' "$*" >&2
  exit 1
}

test "$#" -gt 0 || fail "Notebook command is required."
notebook="$(command -v "$1" || true)"
test -n "$notebook" && test -x "$notebook" ||
  fail "Notebook executable is unavailable."
shift

test -n "${HOME:-}" || fail "HOME is not configured."
runtime_root="$HOME/.local/share/digitafrica/runtime/hpc"
prefix="$runtime_root/environment"
marker="$runtime_root/environment.sha256"
specification=/runtime/hpc/environment.yml

test -d "$prefix" && test -f "$marker" ||
  fail "HPC environment preparation is incomplete."
test -f "$specification" || fail "Environment definition is missing."
expected="$(sha256sum "$specification" | cut -d ' ' -f1)"
test "$(cat "$marker")" = "$expected" ||
  fail "HPC environment does not match the published definition."

conda_executable="$(command -v conda || true)"
if [ -z "$conda_executable" ] && [ -x /opt/conda/bin/conda ]; then
  conda_executable=/opt/conda/bin/conda
fi
test -n "$conda_executable" || fail "Conda is unavailable."

eval "$("$conda_executable" shell.bash hook)"
conda activate "$prefix"

test -n "${CC:-}" || fail "C compiler activation failed."
command -v "$CC" >/dev/null || fail "Configured C compiler is unavailable."
command -v mpicc >/dev/null || fail "MPI compiler wrapper is unavailable."
command -v mpirun >/dev/null || fail "MPI launcher is unavailable."

# Keep the notebook image's executable and forward every argument unchanged.
exec "$notebook" "$@"
