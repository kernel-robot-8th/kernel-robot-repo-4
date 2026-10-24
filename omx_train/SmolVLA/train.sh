#!/usr/bin/env bash
# Fine-tune SmolVLA (lerobot/smolvla_base) on a LeRobot dataset in Docker.
#
# Usage: [DATASET=box_merged] [JOB_NAME=smolvla_<DATASET>] [EPISODES="[0,1,...]"] [KEEP_STEPS="002000"] \
#        ./train.sh [GPU] [extra lerobot-train args...]
#   DATASET     folder name under DATA_DIR (default ./data)
#   EPISODES    episodes to train on (leave out the evaluation episodes); empty = all
#   CAM_RENAME  maps dataset camera names to the base model's camera1/camera2;
#               default top->camera1, wrist->camera2. Set CAM_RENAME= (empty) if the dataset
#               already uses camera1/camera2.
#   KEEP_STEPS  if set, delete every intermediate checkpoint except these (+ the final one),
#               e.g. KEEP_STEPS="002000" with --save_freq=2000 keeps 2k and 20k
#   e.g. DATASET=box_merged_grip KEEP_STEPS=002000 ./train.sh 0 --save_freq=2000
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
GPU="${1:-0}"; shift || true
DATASET="${DATASET:-box_merged}"
JOB_NAME="${JOB_NAME:-smolvla_$DATASET}"
IMAGE="${IMAGE:-omx-smolvla:0.6.1}"
DATA_DIR="$(realpath "${DATA_DIR:-$HERE/data}")"
OUT_DIR="${OUT_DIR:-$HERE/outputs}"
CAM_RENAME="${CAM_RENAME-{\"observation.images.top\": \"observation.images.camera1\", \"observation.images.wrist\": \"observation.images.camera2\"\}}"

[[ -d "$DATA_DIR/$DATASET/meta" ]] || { echo "dataset not found: $DATA_DIR/$DATASET" >&2; exit 1; }
extra=()
[[ -n "${EPISODES:-}" ]] && extra+=(--dataset.episodes="$EPISODES")
[[ -n "$CAM_RENAME" ]] && extra+=(--rename_map="$CAM_RENAME")
mkdir -p "$HERE/.home" "$OUT_DIR/train"
OUT_DIR="$(realpath "$OUT_DIR")"

docker run --rm --name "omx-train-$JOB_NAME" \
  --gpus "\"device=$GPU\"" \
  --user "$(id -u):$(id -g)" \
  --shm-size 16g \
  -v "$HERE:/workspace" -v "$DATA_DIR:/data:ro" -v "$OUT_DIR:/outputs" \
  "$IMAGE" \
  lerobot-train \
    --policy.path=lerobot/smolvla_base \
    --dataset.repo_id="local/$DATASET" \
    --dataset.root="/data/$DATASET" \
    --policy.device=cuda \
    --policy.push_to_hub=false \
    --output_dir="/outputs/train/$JOB_NAME" \
    --job_name="$JOB_NAME" \
    --batch_size=64 \
    --steps=20000 \
    --save_freq=5000 \
    --log_freq=100 \
    --num_workers=8 \
    --wandb.enable=false \
    "${extra[@]}" \
    "$@" &
pid=$!

if [[ -n "${KEEP_STEPS:-}" ]]; then
  sleep 60  # let the container start before watching it
  # shellcheck disable=SC2086
  "$HERE/keep_checkpoints.sh" "$OUT_DIR/train/$JOB_NAME/checkpoints" "omx-train-$JOB_NAME" $KEEP_STEPS &
fi
wait $pid
