#!/usr/bin/env bash
# Run one of the models in this bundle by number (Yuzriha00/shoebox_D, lerobot 0.4.4, GPU).
# 번호로 모델을 골라 실행합니다.
#
# Usage: ./infer.sh            # 모델 목록 보기
#        ./infer.sh <번호> [extra lerobot-record args...]
#   예: ./infer.sh 1                    # 1000 step 모델
#       ./infer.sh 5 --dataset.episode_time_s=120
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# 번호 | 폴더 | 설명   (1000 step마다 저장)
MODELS=()
add() {  # add <step>
  MODELS+=("act_shoebox_d_${1}step|shoebox_D, $1 step")
}
add 1000   #  1
add 2000   #  2
add 3000   #  3
add 4000   #  4
add 5000   #  5

list() {
  for i in "${!MODELS[@]}"; do
    [[ -d "$HERE/checkpoints/${MODELS[$i]%%|*}/pretrained_model" ]] || continue
    printf "%3d  %-30s %s\n" $((i + 1)) "${MODELS[$i]%%|*}" "${MODELS[$i]#*|}"
  done
}

n="${1:-}"
if [[ ! "$n" =~ ^[0-9]+$ ]] || (( n < 1 || n > ${#MODELS[@]} )) || [[ ! -d "$HERE/checkpoints/${MODELS[$((n - 1))]%%|*}/pretrained_model" ]]; then
  echo "Usage: ./infer.sh <번호> [extra lerobot-record args...]"
  list
  exit 1
fi
shift
name="${MODELS[$((n - 1))]%%|*}"
model="$HERE/checkpoints/$name/pretrained_model"

export OMX_RECORD="$HERE/omx_run.py"
ROBOT_TYPE=omx_follower
extra=(--policy.device="${POLICY_DEVICE:-cuda}" --dataset.episode_time_s=90)

if [[ -f "$model/depth_info.json" ]]; then
  ROBOT_TYPE=omx_follower_grip_depth
  extra+=(--robot.depth_info="$model/depth_info.json" --robot.depth_device="${DEPTH_DEVICE:-cuda}")
fi

(
  cd "$HERE"
  lerobot-record \
    --policy-config-path "$model/config.json" \
    --robot-type "$ROBOT_TYPE" \
    --output-dir "." \
    --fps 30 \
    "${extra[@]}" \
    "$@"
)
