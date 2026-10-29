#!/usr/bin/env bash
# holdout vs phases open-loop comparison on held-out episodes 5,12,18 -> outputs/eval/cmp_holdout_vs_phases
set -euo pipefail
E=5,12,18
python -I sim/eval_open_loop.py --dataset_root data/omx_heart_box --repo_id Sungah/omx_heart_box --episodes $E \
  --out outputs/eval/cmp_holdout --model holdout=outputs/train/smolvla_omx_heart_box_holdout/checkpoints/020000/pretrained_model
python -I sim/eval_open_loop.py --dataset_root data/omx_heart_box_phases --repo_id Sungah/omx_heart_box_phases --episodes $E \
  --out outputs/eval/cmp_phases --model phases=outputs/train/smolvla_omx_heart_box_phases/checkpoints/020000/pretrained_model
python -I sim/merge_eval.py --out outputs/eval/cmp_holdout_vs_phases outputs/eval/cmp_holdout outputs/eval/cmp_phases
python -I sim/render_comparison.py --eval_dir outputs/eval/cmp_holdout_vs_phases --episodes $E
