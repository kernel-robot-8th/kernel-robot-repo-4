#!/usr/bin/env bash
# Run one of this folder's Python tools (eval_policy.py, prepare_box_datasets.py) in the training image.
# Datasets are mounted at /data and outputs at /outputs, same as train.sh.
#
# Usage: ./tools.sh [GPU] <script.py> [args...]
#   e.g. ./tools.sh 0 eval_policy.py --dataset_root /data/box_merged --episodes 5,15,25,35,45 \
#          --model smolvla=/outputs/train/smolvla_box_merged/checkpoints/last/pretrained_model --out /outputs/eval/smolvla.json
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GPU="${1:-0}"; shift || true
SCRIPT="$1"; shift
IMAGE="${IMAGE:-omx-smolvla:0.4.4}"
DATA_DIR="${DATA_DIR:-$HERE/data}"
OUT_DIR="${OUT_DIR:-$HERE/outputs}"
mkdir -p "$HERE/.home" "$DATA_DIR" "$OUT_DIR"

docker run --rm \
  --gpus "\"device=$GPU\"" \
  --user "$(id -u):$(id -g)" \
  --shm-size 8g \
  -e DATA_DIR=/data \
  -v "$HERE:/workspace" -v "$(realpath "$DATA_DIR"):/data" -v "$(realpath "$OUT_DIR"):/outputs" \
  "$IMAGE" \
  python -I "/workspace/$SCRIPT" "$@"
