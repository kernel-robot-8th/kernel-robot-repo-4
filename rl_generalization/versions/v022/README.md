# v022 — thin finger collision proxy calibration

v022 keeps the v020 robot-facing hinge and visual arm, but reduces the
collision-only finger capsule radius from 2 mm to 1 mm. The visual meshes stay
disabled for contact. This is an experiment to separate proxy thickness from
trajectory registration; it is not a measured hardware model.

Build the local scene:

```bash
cd ~/dev_ws/Project2/rl_generalization
rm -rf .local/robot_facing_hinge_v022
.venvs/omx_sim/bin/python versions/v022/code/build_calibrated_proxy.py \
  .local/robot_facing_hinge_v020 \
  .local/robot_facing_hinge_v022 \
  --radius-m 0.001
```

The arm replay at `evidence/arm_replay_z0.004/summary.json` reduced maximum
penetration to `0.864 mm`, but peak lift was only `0.666 mm` and no grasp was
validated. The latch diagnostic at `evidence/latch_z0.004/summary.json`
reported no bilateral latch and no 30 mm lift. Therefore thinning the proxy
removed the worst collision artifact but did not create a grasp.

To inspect each version visually, run the interactive arm replay:

```bash
PYTHONPATH=versions/v018/code \
.venvs/omx_sim/bin/python \
versions/v022/code/preview_arm_replay.py \
  --scene .local/robot_facing_hinge_v022/scene.xml \
  --seconds 45 \
  --speed 0.5 \
  --initial-angle -2.70 \
  --shift-z -0.004
```

The window shows the recorded arm and gripper commands. Close it to end the
preview; use `arm_replay_attempt.py` for quantitative evidence.
