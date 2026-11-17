# Shoebox closed-lid classifier (top-view)

This folder contains the training/inference code and the labeled image split required to run the GPU sweep. It uses only `observation.images.top` images. A `closed_verified` frame must show the lid hiding the red interior and the robot gripper head visibly lifted clear of the box. Pressing/contact frames are `not_verified`.

## Download this branch

```bash
git clone --branch feature/shoebox-lid-classifier \
  https://github.com/kernel-robot-8th/kernel-robot-repo-4.git
cd kernel-robot-repo-4/classification/shoebox_lid
```

## GPU setup and training

Use a Python version supported by the installed CUDA PyTorch. Install a CUDA-enabled PyTorch build for the notebook's driver first if one is not already present, then:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -c "import torch; print('CUDA:', torch.cuda.is_available())"
python train.py --data dataset_top_closed_verified_strict --device 0 \
  --epochs 40 --output runs_top_strict_sweep
```

The sweep compares 24 settings: AdamW learning rates 0.0001/0.0003/0.001, SGD learning rates 0.001/0.003/0.01, batch sizes 16/32, and dropout 0/0.15. It saves each epoch checkpoint and evaluates it against the labeled episode-disjoint `test/` image holdout. The best candidate checkpoint is copied to `runs_top_strict_sweep/best.pt`; its parameters and probability threshold are saved in `selected.json`.

This repository includes 1,078 train images and 120 model-selection holdout images. The holdout has only 3 positive images, so its score is unstable and is not an unbiased final performance estimate. The separate human-review MP4 is deliberately not included or read by training.

Outputs include `results.csv`, `checkpoint_results.csv`, per-image predictions, threshold details, and comparison plots. Training uses no `val/` folder and disables Ultralytics validation.

## Run inference

```bash
python infer.py --selection runs_top_strict_sweep/selected.json \
  --source TOP_CAMERA_INDEX --device 0
```

The inference script only reports probabilities. It does not control the robot. `gate.py` and `integration_example.py` show a separate temporal/interlock gate for downstream integration.
