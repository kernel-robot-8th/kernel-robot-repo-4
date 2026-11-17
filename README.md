cd kernel-robot-repo-4/classification/shoebox_lid
python train.py \
  --data ./dataset_top_closed_verified_strict \
  --device 0 \
  --epochs 40 \
  --output ./runs_top_strict_sweep


git clone --filter=blob:none --sparse --single-branch --branch feature/shoebox-lid-classifier https://github.com/kernel-robot-8th/kernel-robot-repo-4.git shoebox-lid

cd shoebox-lid
git sparse-checkout set classification/shoebox_lid
cd classification/shoebox_lid


python3 train.py --data ./dataset_top_closed_verified_strict --device 0 --epochs 40 --output ./runs_top_strict_sweep_run2
