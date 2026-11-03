#!/usr/bin/env bash
# 3-model open-loop comparison (full / holdout / phases) on episodes 5,12,18 -> outputs/eval/cmp_all
# Reuses outputs/eval/cmp_holdout and outputs/eval/cmp_phases from cmp_run.sh.
set -euo pipefail
E=5,12,18
python -I sim/eval_open_loop.py --dataset_root data/omx_heart_box --repo_id Sungah/omx_heart_box --episodes $E \
  --out outputs/eval/cmp_full --model full=outputs/train/smolvla_omx_heart_box/checkpoints/020000/pretrained_model
python -I sim/merge_eval.py --out outputs/eval/cmp_all outputs/eval/cmp_full outputs/eval/cmp_holdout outputs/eval/cmp_phases
python -I sim/render_comparison.py --eval_dir outputs/eval/cmp_all --episodes $E
