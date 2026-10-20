#!/bin/sh
set -eu

case "${DIGITAFRICA_MODULE5_NODE_ENABLED:-false}" in
  true)
    runtime_bin="${DIGITAFRICA_MODULE5_NODE_BIN:?Module 5 binary path is required}"
    case "$runtime_bin" in
      /*) ;;
      *) echo "Module 5 binary path must be absolute." >&2; exit 1 ;;
    esac
    if [ ! -x "$runtime_bin/node" ] || [ ! -x "$runtime_bin/npm" ]; then
      echo "Module 5 Node.js runtime is missing or incomplete." >&2
      exit 1
    fi
    PATH="$runtime_bin${PATH:+:$PATH}"
    export PATH
    ;;
  false) ;;
  *)
    echo "Invalid Module 5 runtime selection." >&2
    exit 1
    ;;
esac

if [ "$#" -eq 0 ]; then
  echo "Notebook launch command is required." >&2
  exit 1
fi

exec "$@"
