# v021 — staged full-sequence smoke check

`code/sequence_check.py` executes the scene-level sequence with the
robot-facing hinged lid:

`open initial → insert shoe 0 → insert shoe 1 → close lid → lift box → load stationary tray`.

The initial hinge angle is configurable. The default `-2.70 rad` is an
oblique open pose (0 is closed, `-π/2` is vertical, `-π` is flat toward the
OMX). The top-camera frames show the lid about 20–30° above the fully-flat
pose, so `-2.70 rad` is a provisional video-based fit; it is not a calibrated
hinge measurement.

The shoe insertion and box transport stages update free-joint poses to test
dimensions and clearances. They are labelled `PASS_GEOMETRY_ONLY` or
`PASS_KINEMATIC_ONLY`; the two arm/gripper pickup stages remain
`NOT_VALIDATED_ARM_GRASP`. Therefore a passing report is not a learned-policy
rollout, real gripper success, or sim-to-real claim.

```bash
cd ~/dev_ws/Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v021/code/sequence_check.py \
  --initial-angle -2.70 \
  --out versions/v021/evidence/sequence_smoke_$(date +%Y%m%d_%H%M%S)
```

For a short interactive preview add `--view`; close the viewer to finish.

To compare the remaining visual uncertainty, run the same check at
`-2.55`, `-2.70`, and `-2.85` rad. All three are recorded under
`evidence/angle_*/summary.json`; the middle value is the current default.

The arm-connected diagnostic replays episode-0 joint/gripper commands through
the MuJoCo actuators and applies the same provisional retarget shift used by
the earlier contact audit:

```bash
PYTHONPATH=versions/v018/code .venvs/omx_sim/bin/python \
  versions/v021/code/arm_replay_attempt.py \
  --seconds 12 \
  --initial-angle -2.70 \
  --out versions/v021/evidence/arm_replay_$(date +%Y%m%d_%H%M%S)
```

The 12-second pickup diagnostic is in `evidence/arm_replay_12s/summary.json`;
the full 45-second demonstration replay is in
`evidence/arm_replay_45s/summary.json`. The arm remains finite and reaches
both shoes, but maximum penetration is 4.20 mm, peak lift is only 1.77 mm, and
`grasp_success` is false. Gripper zero, compliant cardboard/cloth, finger
geometry and a validated attachment/lift criterion are still missing.

A 25-trial gripper-zero/vertical-offset sweep is summarized in
`evidence/calibration_sweep_20261123_210633/summary.json`. The best
low-penetration trial was `0.730 mm`, but its lift was only `0.577 mm` and it
had no bilateral hold. No tested setting reached both the `≤1 mm` penetration
and `≥30 mm` lift criteria. This means parameter tweaking alone cannot repair
the current proxy; the finger/shoe registration and contact geometry must be
calibrated next.
