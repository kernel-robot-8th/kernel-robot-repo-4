#!/usr/bin/env bash
set -euo pipefail
rl_project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
rl_version="$(cat "$rl_project_dir/CURRENT")"
rl_python="$rl_project_dir/.venvs/rl/bin/python"
if [[ ! -x "$rl_python" ]]; then
  echo 'Run bash setup.sh first.' >&2
  exit 1
fi
export PYTHONPATH="$rl_project_dir/versions/$rl_version/code${PYTHONPATH:+:$PYTHONPATH}"
export MPLCONFIGDIR="$rl_project_dir/.local/matplotlib"
mkdir -p "$MPLCONFIGDIR"
cd "$rl_project_dir/versions/$rl_version"
case "${1:-}" in
  train|evaluate|jitter)
    rl_module="$1"
    shift
    exec "$rl_python" -m "omx_rl.$rl_module" "$@"
    ;;
  test)
    export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
    shift
    exec "$rl_python" -m pytest -q tests "$@"
    ;;
  *) echo 'Usage: bash run.sh {train|evaluate|jitter|test} [arguments]' >&2; exit 2 ;;
esac
