# v017: grasp-contact diagnostics

This version adds contact force logging and a depth sweep to the retargeted demonstration replay. It does not connect to hardware, add a weld, or claim real grasp success.

The apparent lift is sensitive to vertical retargeting: −12 mm gives no sustained lift, −15 mm gives 1.448 s, −18 mm gives 3.626 s, and −21 mm gives 3.622 s. However, all apparent lifts have roughly 9 mm finger-to-shoe collision penetration. Therefore all are rejected by the validation rule: lift above 3 cm, bilateral hold at least 0.5 s, and collision penetration no more than 1 mm. The result is a collision-model failure, not a validated grasp.

Reproduce the validation:

```bash
.venvs/omx_sim/bin/python versions/v017/code/validate_sweep.py
```

The next fix is to replace the visual gripper meshes used as collision shapes with measured, thin finger contact proxies, then rerun the same sweep. The shoe remains a rigid proxy and the real gripper opening, zero, and force mapping remain unmeasured. Do not transfer the −18 mm offset to the physical robot.
