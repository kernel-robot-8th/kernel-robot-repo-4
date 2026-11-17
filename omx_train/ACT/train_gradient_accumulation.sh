#!/usr/bin/env bash
# ACT training with gradient accumulation (lerobot 0.4.4).
#
#   train.sh와 같은 옵션(ARGS)으로 학습하되, 모델을 한 번 업데이트할 batch를 GRAD_ACCUM 조각으로 나눠
#   forward/backward 합니다. GPU 메모리가 모자라 batch를 키울 수 없을 때 씁니다.
#   학습 옵션 목록은 train.sh의 ARGS=( ... )를 그대로 읽어 오므로, 옵션 값은 train.sh에서 바꾸세요.
#
# Usage: [GRAD_ACCUM=2] [DATASET=...] [JOB_NAME=...] [EPISODES=...] ./train_gradient_accumulation.sh [GPU] [extra args...]
#   GRAD_ACCUM   : 업데이트 1번당 조각 수 (기본 2, 1이면 train.sh와 같음)
#   --batch_size : 업데이트 1번에 쓰는 전체 batch. GPU에는 batch_size / GRAD_ACCUM 씩 올라감
#   예) GRAD_ACCUM=2 ./train_gradient_accumulation.sh 0 --batch_size=32   # 메모리는 batch 16, 업데이트는 batch 32
#   --steps, --save_freq, --log_freq, lr 스케줄은 모두 "업데이트 횟수" 기준이라 train.sh와 같은 값을 쓰면 됩니다.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GPU="${1:-0}"; shift || true
DATASET="${DATASET:-omx_1024_test_jihyeok_success}"
GRAD_ACCUM="${GRAD_ACCUM:-2}"
JOB_NAME="${JOB_NAME:-act_${DATASET}_ga$GRAD_ACCUM}"
IMAGE="${IMAGE:-omx-act:0.4.4}"
DATA_DIR="$(realpath "${DATA_DIR:-$HERE/data}")"
OUT_DIR="${OUT_DIR:-$HERE/outputs}"
[[ -d "$DATA_DIR/$DATASET/meta" ]] || { echo "dataset not found: $DATA_DIR/$DATASET" >&2; exit 1; }

# train.sh의 ARGS=( ... ) 블록만 읽어 옴 (DATASET 등 위 변수가 그대로 들어감)
eval "$(sed -n '/^ARGS=(/,/^)/p' "$HERE/train.sh")"
(( ${#ARGS[@]} )) || { echo "ARGS not found in $HERE/train.sh" >&2; exit 1; }

[[ -n "${EPISODES:-}" ]] && ARGS+=(--dataset.episodes="$EPISODES")
mkdir -p "$HERE/.home" "$OUT_DIR/train"
OUT_DIR="$(realpath "$OUT_DIR")"

docker run --rm --name "omx-train-$JOB_NAME" \
  --gpus "\"device=$GPU\"" \
  --user "$(id -u):$(id -g)" \
  --shm-size 16g \
  -v "$HERE:/workspace" -v "$DATA_DIR:/data:ro" -v "$OUT_DIR:/outputs" \
  "$IMAGE" \
  python /workspace/train_gradient_accumulation.py --grad_accum_steps="$GRAD_ACCUM" "${ARGS[@]}" "$@"
