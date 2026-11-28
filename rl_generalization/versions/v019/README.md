# v019 — contact-safe finger proxy replay

v019 keeps v018 unchanged and addresses the two causes of the false grasp
diagnostic:

* `build_finger_proxy.py` disables the gripper STL collision and adds thin
  boxes whose long axis is the finger body's local **x** axis.  The local y
  direction is the jaw-opening direction.
* `grasp_latch.py` detects bilateral contact with one shoe, freezes the
  gripper closing velocity, and latches its target at the contact position
  plus a small opening backoff.  The arm is held at the contact pose while
  the recorded trajectory is still descending.

This is a simulation diagnostic.  The gripper mapping, zero, motor limits,
and shoe material remain uncalibrated; no real-robot command is generated.

## Reproduce

```bash
cd Project2/rl_generalization
.venvs/omx_sim/bin/python versions/v019/code/build_finger_proxy.py \
  .local/finger_proxy_v018 .local/finger_proxy_v019

.venvs/omx_sim/bin/python versions/v019/code/grasp_latch.py \
  --scene .local/finger_proxy_v019/scene.xml \
  --out versions/v019/evidence/latch_box_run
```

The recorded shoebox demonstration is used only as an arm-path reference and
is retargeted by the existing uncalibrated translation.  In the checked run,
shoe1 reached bilateral contact at 7.504s and the maximum finger–shoe
penetration was 0.000928m (0.93mm), with zero MuJoCo warnings.  This is below
the broad 1mm diagnostic ceiling but above the stricter 0.3mm target derived
from the user's approximately 0.1–0.2mm measurement uncertainty.  The 30mm
lift criterion was not met; the run therefore does not claim a grasp or
sim-to-real transfer.
