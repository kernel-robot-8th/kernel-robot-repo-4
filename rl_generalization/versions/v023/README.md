# v023 — explicit demo poses and complete workcell sequence

This version is a visual sequence check built from the two existing OMX
demonstrations. It starts `shoebox_D` with the supplied LeRobot median pose,
keeps the lid open toward the OMX, inserts two shoes, commands the gripper to
normalized value `0` before closing the lid, then resets to the separate
`move_in_success` start pose and carries the closed box to the stationary
logistics robot's circular white tray.

The arm commands are replayed from the local parquet demonstrations. Shoe
insertion and the closed-box payload are kinematic proxies. Consequently a
`PASS_KINEMATIC_ONLY` stage verifies scene geometry and sequence ordering; it
does not mean the physical gripper has grasped the shoe or paper box.

Headless evidence:

```bash
cd ~/dev_ws/Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v023/code/full_sequence_preview.py \
  --out versions/v023/evidence/full_sequence_$(date +%Y%m%d_%H%M%S)
```

Interactive inspection:

```bash
.venvs/omx_sim/bin/python versions/v023/code/full_sequence_preview.py \
  --view --speed 0.5 \
  --out versions/v023/evidence/full_sequence_view_$(date +%Y%m%d_%H%M%S)
```

The summary records the two explicit normalized starts:

* `shoebox_D`: `[-12.97, -17.31, -0.85, 43.59, -0.85, 59.68]`
* `move_in_success`: `[2.22, -34.99, 14.68, 40.37, 1.0, 58.93]`

Before hardware use, calibrate the gripper zero, finger spacing, compliant
shoe/paper contact, attachment/lift criterion and tray placement. This version
does not make a sim-to-real success claim.
