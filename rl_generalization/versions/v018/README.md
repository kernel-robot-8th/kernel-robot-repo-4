# v018: thin finger proxy diagnostic

This version replaces the visual gripper collision geometry with two separate
capsule proxies and replays the retargeted `shoebox_D` demonstration against
the v015 stability scene. It is a collision-model diagnostic only. There is no
hardware connection, calibrated gripper width/zero, measured contact force,
cloth compliance, or grasp constraint.

## What was run

The proxy scene was generated from `.local/stability_v015/scene` with
`code/build_finger_proxy.py`. Existing collision geoms on `link6` and `link7`
were disabled and `finger6_proxy`/`finger7_proxy` capsules were added. The
replay used the recorder FK offset and the experimental translation from v016
(`x=+34.972 mm`, `y=-3.428 mm`, `z=-18 mm`) with the uncalibrated normalized
gripper-zero candidate `46.8`.

```bash
.venvs/omx_sim/bin/python \
  versions/v018/code/build_finger_proxy.py \
  .local/stability_v015/scene .local/finger_proxy_v018

.venvs/omx_sim/bin/python \
  versions/v018/code/retarget_contact.py \
  --shift-z -0.018 --out versions/v018/evidence_proxy
```

The recorded command replay produced bilateral contact and an apparent shoe
lift, but the maximum proxy-to-shoe penetration was **8.755 mm**. The peak
simulated normal forces were about 18.85 N and 18.95 N. The apparent lift is
therefore rejected: it is collision interpenetration, not validated grasp or
retention. `evidence/low_proxy_trial` is an additional repeat and has the same
failure mode (about 9.12 mm penetration).

## Acceptance rule

For this diagnostic, a candidate lift is accepted only when the shoe origin
rises over 3 cm, bilateral contact is held for at least 0.5 s, and maximum
finger-to-shoe penetration is at most 1 mm. The v018 trials satisfy the first
two numerical heuristics but fail the collision criterion. Do not report them
as task success or transfer the offsets/forces to the physical OMX.

## Next step

Measure the real finger surfaces, opening and zero, then place collision
proxies at the measured contact surfaces and rerun the same replay. If the
proxy still penetrates, fix geometry/registration before tuning friction or
calling the motion a grasp. Only after a physically valid contact model passes
the diagnostic should the staged shoe→box→lid→tray controller be trained or
tested on hardware.
