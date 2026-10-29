#!/usr/bin/env bash
# 10/27 ACT open-loop comparison on the held-out episode (eval1 ep 0), 30 frames per prediction like
# outputs/eval/act_1027/eval_all.sh, rendered in the 10/27 sim scene -> outputs/eval/cmp_1027
set -euo pipefail
T=outputs/train
python -I sim/eval_open_loop.py --dataset_root data/omx_1027_jihyeok_eval1_grip --repo_id local/omx_1027_jihyeok_eval1_grip \
  --episodes 0 --chunk 30 --out outputs/eval/cmp_1027 \
  --model B0=$T/act_1027_B0/checkpoints/010000/pretrained_model \
  --model C30=$T/act_1027_C30/checkpoints/010000/pretrained_model \
  --model C50=$T/act_1027_C50/checkpoints/010000/pretrained_model \
  --model C50AUG=$T/act_1027_C50AUG/checkpoints/010000/pretrained_model
python -I sim/render_comparison.py --eval_dir outputs/eval/cmp_1027 --dataset_root data/omx_1027_jihyeok_eval1_grip \
  --repo_id local/omx_1027_jihyeok_eval1_grip --episodes 0 --scene workspace_scene_1027.xml --camera top
