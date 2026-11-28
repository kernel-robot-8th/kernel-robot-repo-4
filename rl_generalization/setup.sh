#!/usr/bin/env bash
set -euo pipefail
rl_project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${RL_PYTHON:-python3}" "$rl_project_dir/tools/bootstrap.py" "$@"
