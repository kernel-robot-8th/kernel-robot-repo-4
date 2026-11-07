#!/usr/bin/env bash
# While a training container runs, delete intermediate checkpoints except the ones to keep.
# A checkpoint is removed only after a newer one has been saved (checkpoints/last points past it),
# so nothing is deleted while it is still being written.
#
# Usage: ./keep_checkpoints.sh <checkpoints_dir> <container_name> <keep_step> [keep_step ...]
#   e.g. ./keep_checkpoints.sh outputs/train/smolvla_box_merged/checkpoints \
#          omx-train-smolvla_box_merged 002000
#   (train.sh starts this automatically when KEEP_STEPS is set)
#   (the final checkpoint is always kept)
set -euo pipefail

CKPT_DIR="$1"; CONTAINER="$2"; shift 2
KEEP=("$@")

prune() {
  [[ -L "$CKPT_DIR/last" ]] || return 0
  local last; last="$(basename "$(readlink "$CKPT_DIR/last")")"
  for d in "$CKPT_DIR"/[0-9]*; do
    [[ -d "$d" ]] || continue
    local step; step="$(basename "$d")"
    [[ "$step" == "$last" ]] && continue
    (( 10#$step < 10#$last )) || continue
    [[ " ${KEEP[*]} " == *" $step "* ]] && continue
    echo "$(date '+%F %T') removing $d"
    rm -rf -- "$d"
  done
}

while docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; do
  prune
  sleep 60
done
prune
echo "$(date '+%F %T') training container gone; kept: $(ls "$CKPT_DIR" | tr '\n' ' ')"
