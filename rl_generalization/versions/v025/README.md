# v025 — contact-latch calibration sweep

v025 runs the v024 explicit-pose contact diagnostic over gripper-zero and
vertical registration candidates. It ranks bilateral contact, penetration, and
lift. The sweep is for simulator calibration, not reinforcement learning and
not hardware validation.

```bash
cd ~/dev_ws/Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v025/code/contact_sweep.py \
  --out versions/v025/evidence/contact_sweep_$(date +%Y%m%d_%H%M%S)
```

Inspect `summary.json`. A candidate requires bilateral contact, penetration at
most 1 mm, and at least 30 mm lift. It is expected that the current model may
produce zero candidates; that result identifies a calibration/modeling gap.
