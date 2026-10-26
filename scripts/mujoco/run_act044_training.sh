#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python_bin="$HOME/venv/il/bin/python"
run_dir="${OMX_ACT044_RUN:-$HOME/omx_sim_runs/retraining_044_20261026}"
mkdir -p "$run_dir"
export PYTHONPATH="$repo_dir/src/cobot_mujoco${PYTHONPATH:+:$PYTHONPATH}"
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
cd "$repo_dir"
nohup setsid "$python_bin" -m cobot_mujoco.act044_runner \
  --run "$run_dir" --source "$HOME/omx_sim_data/omx_1024_test_jihyeok_success" \
  >> "$run_dir/supervisor.log" 2>&1 < /dev/null &
echo "LeRobot 0.4.4 ACT 학습·검증 감독기 시작: PID $! / $run_dir/status.json"
