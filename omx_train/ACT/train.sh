#!/usr/bin/env bash
# Train an ACT policy on a LeRobot dataset in Docker.
#
# Usage: [DATASET=box_merged] [JOB_NAME=act_<DATASET>] [EPISODES="[0,1,...]"] ./train.sh [GPU] [extra lerobot-train args...]
#   DATASET   folder name under DATA_DIR (default ./data)
#   EPISODES  episodes to train on (leave out the evaluation episodes); empty = all
#   e.g. DATASET=box_merged_grip ./train.sh 0 --steps=50000
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GPU="${1:-0}"; shift || true
DATASET="${DATASET:-box_merged}"
JOB_NAME="${JOB_NAME:-act_$DATASET}"
IMAGE="${IMAGE:-omx-act:0.6.1}"
DATA_DIR="$(realpath "${DATA_DIR:-$HERE/data}")"
OUT_DIR="${OUT_DIR:-$HERE/outputs}"

[[ -d "$DATA_DIR/$DATASET/meta" ]] || { echo "dataset not found: $DATA_DIR/$DATASET" >&2; exit 1; }
episodes=()
[[ -n "${EPISODES:-}" ]] && episodes=(--dataset.episodes="$EPISODES")
mkdir -p "$HERE/.home" "$OUT_DIR/train"
OUT_DIR="$(realpath "$OUT_DIR")"

docker run --rm --name "omx-train-$JOB_NAME" \
  --gpus "\"device=$GPU\"" \
  --user "$(id -u):$(id -g)" \
  --shm-size 16g \
  -v "$HERE:/workspace" -v "$DATA_DIR:/data:ro" -v "$OUT_DIR:/outputs" \
  "$IMAGE" \
  lerobot-train \
    --dataset.repo_id="local/$DATASET" \
    --dataset.root="/data/$DATASET" \
    --policy.type=act \
    --policy.device=cuda \
    --policy.push_to_hub=false \
    --output_dir="/outputs/train/$JOB_NAME" \
    --job_name="$JOB_NAME" \
    --batch_size=8 \
    --steps=100000 \
    --save_freq=20000 \
    --log_freq=200 \
    --num_workers=8 \
    --wandb.enable=false \
    "${episodes[@]}" \
    "$@"
