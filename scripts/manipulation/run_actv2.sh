#!/usr/bin/env bash
set -euo pipefail
script_dir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
exec "$script_dir/run_act044.sh" "$@" --run-dir "$HOME/omx_sim_runs/retraining_044_v2_15k_20261027"
