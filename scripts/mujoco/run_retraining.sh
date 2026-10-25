#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="${OMX_SIM_PYTHON:-$HOME/venv/omx_mujoco/bin/python}"
run_dir="${OMX_RETRAIN_RUN:-$HOME/omx_sim_runs/retraining_20261025}"
mkdir -p "$run_dir"
export PYTHONPATH="$repo_dir/src/cobot_mujoco${PYTHONPATH:+:$PYTHONPATH}"
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export MUJOCO_GL=egl
cd "$repo_dir"
nohup setsid "$python_bin" -m cobot_mujoco.retraining_runner \
  --run "$run_dir" --source "$HOME/omx_sim_data/omx_1024_test_jihyeok_success" \
  --cache "$HOME/omx_sim_data/cache_v1" >> "$run_dir/supervisor.log" 2>&1 < /dev/null &
echo "재학습 감독 프로세스 시작: PID $! / 상태: $run_dir/status.json"
