# v026 grasp proxy calibration

This version derives `.local/grasp_proxy_v026` from `robot_facing_hinge_v022` and enlarges the two collision finger proxies from radius 1 mm / half-length 12 mm to radius 2.2 mm / half-length 14 mm. Contact friction is 1.8 with softer solref. It remains a MuJoCo calibration scene; no sim-to-real claim.

Quick diagnostic:
```bash
PYTHONPATH=versions/v018/code .venvs/omx_sim/bin/python \
  versions/v024/code/contact_latch_explicit.py \
  --scene .local/grasp_proxy_v026/scene.xml --seconds 12 \
  --gripper-zero 46.8 --shift-z -0.004 \
  --out versions/v026/evidence/diag
```

Baseline v022 at the same settings gave 0.67 mm peak shoe lift and 239 bilateral contact steps. v026 gave 6.56 mm peak lift and 686 bilateral contact steps, with 0.795 mm peak penetration. This is improved contact, but below the 30 mm lift success criterion; an attachment/force-control curriculum is still required.
