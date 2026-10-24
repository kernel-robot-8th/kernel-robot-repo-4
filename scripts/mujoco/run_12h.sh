#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${OMX_SIM_PYTHON:-$HOME/venv/omx_mujoco/bin/python}"
run_dir="${OMX_SIM_RUN:-$HOME/omx_sim_runs/validation_20261025}"
mkdir -p "$run_dir"
export PYTHONPATH="$repo_dir/src/cobot_mujoco${PYTHONPATH:+:$PYTHONPATH}"
export MUJOCO_GL=egl
export OMP_NUM_THREADS=4
cd "$repo_dir"
nohup setsid "$python_bin" -m cobot_mujoco.cli run \
  --cache "$HOME/omx_sim_data/cache_v1" \
  --assets "$HOME/omx_sim_assets/robotis" \
  --run "$run_dir" \
  --report-dir "$repo_dir/docs/mujoco_validation" \
  --hours 12 --push-report \
  > "$run_dir/supervisor.log" 2>&1 < /dev/null &
echo "Supervisor launched: PID $!; status: $run_dir/status.json"
