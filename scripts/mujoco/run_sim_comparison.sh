#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${OMX_SIM_PYTHON:-$HOME/venv/omx_mujoco/bin/python}"
training_run="${OMX_RETRAIN_RUN:-$HOME/omx_sim_runs/retraining_20261025}"
export PYTHONPATH="$repo_dir/src/cobot_mujoco${PYTHONPATH:+:$PYTHONPATH}"
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MUJOCO_GL=egl
cd "$repo_dir"
nohup setsid "$python_bin" -m cobot_mujoco.sim_comparison \
  --training "$training_run" --assets "$HOME/omx_sim_assets/robotis" \
  --cache "$HOME/omx_sim_data/cache_v1" \
  >> "$training_run/mujoco_comparison.log" 2>&1 < /dev/null &
echo "MuJoCo 비교 시작: PID $! / $training_run/mujoco_comparison/status.json"
