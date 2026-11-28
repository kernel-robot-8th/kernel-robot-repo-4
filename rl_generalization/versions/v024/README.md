# v024 — explicit-pose contact-latch diagnostic

This version replays the `shoebox_D` arm trajectory from the supplied
LeRobot median pose and stops the gripper when both thin finger proxies touch
the same shoe. It measures penetration, bilateral contact, and lift. It is a
contact diagnostic only: no weld or compliant shoe attachment is added.

```bash
cd ~/dev_ws/Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v024/code/contact_latch_explicit.py \
  --scene .local/robot_facing_hinge_v022/scene.xml \
  --seconds 12 --gripper-zero 46.8 --shift-z -0.004 \
  --out versions/v024/evidence/contact_latch_$(date +%Y%m%d_%H%M%S)
```

The candidate grasp condition is bilateral contact, penetration at most 1 mm,
and shoe lift at least 30 mm. A failed candidate remains useful evidence for
calibrating the gripper zero, finger geometry, and contact registration.
