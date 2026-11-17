cd kernel-robot-repo-4/classification/shoebox_lid
python train.py \
  --data ./dataset_top_closed_verified_strict \
  --device 0 \
  --epochs 40 \
  --output ./runs_top_strict_sweep
