#!/usr/bin/env bash
set -euo pipefail
script_dir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
inference_config="${ACT044_INFERENCE_CONFIG:-$script_dir/act044_inference.env}"
if [[ ! -f "$inference_config" ]]; then
  echo "추론 설정 파일이 없습니다: $inference_config" >&2
  exit 2
fi
source "$inference_config"
export ACT044_RUN_DIR="${ACT044_RUN_DIR:-$HOME/omx_sim_runs/retraining_044_20261026}"
export ACT044_DURATION="${ACT044_DURATION:-10}" ACT044_ACTION_STEPS="${ACT044_ACTION_STEPS:-5}"
export ACT044_TEMPORAL_ENSEMBLE="${ACT044_TEMPORAL_ENSEMBLE:-false}"
export ACT044_TEMPORAL_ENSEMBLE_COEFF="${ACT044_TEMPORAL_ENSEMBLE_COEFF:-0.01}"
export ACT044_INIT_POSE="${ACT044_INIT_POSE:-true}"
export ACT044_INIT_POSE_FILE="${ACT044_INIT_POSE_FILE:-$script_dir/act044_init_pose.json}"
export ACT044_INIT_POSE_DURATION="${ACT044_INIT_POSE_DURATION:-3}"
export ACT044_MAX_RELATIVE_TARGET="${ACT044_MAX_RELATIVE_TARGET:-3}"
export ACT044_DEVICE="${ACT044_DEVICE:-cuda}" ACT044_DISPLAY="${ACT044_DISPLAY:-false}"
export ROBOT_PORT="${ROBOT_PORT:-}"
export ROBOT_ID="${ROBOT_ID:-omx_follower_arm}"
export FRONT_CAM="${FRONT_CAM:-}" WRIST_CAM="${WRIST_CAM:-}"
export FRONT_CAM_FPS="${FRONT_CAM_FPS:-22}" WRIST_CAM_FPS="${WRIST_CAM_FPS:-30}"
export FRONT_CAM_FOURCC="${FRONT_CAM_FOURCC:-}" WRIST_CAM_FOURCC="${WRIST_CAM_FOURCC:-}"
export TASK="${TASK:-상자를 집어서 흰 수신대에 놓는다.}"
export PYTHONPATH="$HOME/il_ws/src/lerobot/src"
exec "$HOME/venv/il/bin/python" "$script_dir/act044_launch.py" "$@"
